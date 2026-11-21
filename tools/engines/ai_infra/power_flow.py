"""Power-flow module: can the local grid serve the load, at which voltage, and what breaks?

Reduced-order and screening-grade. Topology is observed (network.py, from OSM). Ratings,
impedances, transformer sizes, existing load and the strength of the grid beyond the county
are assumed and drawn per seed. AC power flow (pandapower, Newton-Raphson), N-0 only.
"""
from __future__ import annotations

import math
import warnings

import numpy as np
import pandapower as pp
from shapely.geometry import LineString, Point

WEST = {"WA", "OR", "CA", "ID", "NV", "UT", "AZ", "MT", "WY", "CO", "NM"}
ACTIVSG_KV = [69, 100, 115, 138, 161, 230, 345, 500, 765]


def u(rng, r):
    return float(r) if not isinstance(r, (list, tuple)) else float(rng.uniform(r[0], r[1]))


def kv_band(kv: float) -> str:
    return "<=69" if kv <= 70 else ("100-230" if kv < 300 else ">=345")


def cost_band(kv: float) -> str:
    return "<=69" if kv <= 70 else ("100-170" if kv <= 170 else ("200-300" if kv <= 300 else ">=345"))


def _quantile(rng, pcts):
    """Draw from a distribution given by its p10/p25/p50/p75/p90 (piecewise-linear CDF)."""
    qs = [0.1, 0.25, 0.5, 0.75, 0.9]
    return float(np.interp(rng.uniform(0.1, 0.9), qs, pcts))


class Params:
    """Per-seed draws of every assumed electrical parameter."""

    def __init__(self, cfg, activsg, state, rng):
        self.cfg, self.rng = cfg, rng
        case = "case_ACTIVSg10k" if state in WEST else "case_ACTIVSg70k"
        self.case = case
        self.lines = activsg[case]["lines"]
        self.trafos = activsg[case]["transformers"]
        n = cfg["network"]
        self.bg = u(rng, n["background_utilisation"])
        self.vm_ext = u(rng, n["ext_grid_vm_pu"])
        self.xkm = {k: u(rng, v) for k, v in n["x_ohm_per_km"].items()}
        self._rating = {}
        self._xr = {}
        self.vk = u(rng, n["transformer_vk_percent"])
        self.reg_vm = u(rng, n["regulation_vm_pu"])
        self.reg_q_share = u(rng, n["regulation_q_share_of_load"])

    def rating_mva(self, kv):
        if kv not in self._rating:
            n = self.cfg["network"]
            if kv < 69:
                key = "34.5" if abs(kv - 34.5) < 3 else ("46" if 40 <= kv < 60 else "<34.5")
                self._rating[kv] = u(self.rng, n["ratings_below_69kv_mva"][key])
            else:
                near = min(ACTIVSG_KV, key=lambda a: abs(a - kv))
                d = self.lines.get(str(near)) or self.lines[min(self.lines, key=lambda a: abs(int(a) - kv))]
                self._rating[kv] = _quantile(self.rng, d["rateA_MVA_p10_25_50_75_90"])
        return self._rating[kv]

    def x_over_r(self, kv):
        if kv not in self._xr:
            near = min(ACTIVSG_KV, key=lambda a: abs(a - kv))
            d = self.lines.get(str(near)) or self.lines[min(self.lines, key=lambda a: abs(int(a) - kv))]
            lo, mid, hi = d["x_over_r_p10_50_90"]
            if kv < 69:
                lo, mid, hi = 1.5, 2.0, 2.5  # assumed: low-voltage conductors are more resistive
            self._xr[kv] = float(self.rng.uniform(lo, hi))
        return self._xr[kv]

    def trafo_mva(self, hv, lv):
        best = None
        for k, d in self.trafos.items():
            a, b = (float(x) for x in k.split("/"))
            if abs(a - hv) <= 5 and abs(b - lv) <= 5:
                best = d
        if best is None:
            return u(self.rng, self.cfg["network"]["transformer_mva_fallback"]), "assumed fallback"
        p10, p50, p90 = best["rateA_MVA_p10_50_90"]
        return float(np.interp(self.rng.uniform(0.1, 0.9), [0.1, 0.5, 0.9], [p10, p50, p90])), "ACTIVSg"


def interconnection_class(peak_mw, cfg, rng):
    ic = cfg["interconnection"]
    t = ic["thresholds_mw"]
    s = [u(rng, ic["threshold_scale"]) for _ in range(3)]
    if peak_mw <= t["distribution_max"] * s[0]:
        return "distribution"
    if peak_mw <= t["subtransmission_max"] * s[1]:
        return "subtransmission"
    if peak_mw <= t["hv_max"] * s[2]:
        return "hv"
    return "ehv"


def choose_poi(network, site_xy, cls, cfg):
    """Point of interconnection: nearest supplied substation bus in the class; else nearest
    supplied substation bus above it; else a tap on the nearest supplied line at or above
    the class floor (a new switching station)."""
    lo, hi = cfg["interconnection"]["classes_kv"][cls]
    sx, sy = site_xy
    subs = [b for b in network.buses if b["kind"] == "substation" and b.get("supplied")]

    def nearest(cands):
        return min(cands, key=lambda b: math.hypot(b["x"] - sx, b["y"] - sy)) if cands else None

    for pick in ([b for b in subs if lo <= b["kv"] <= hi], [b for b in subs if b["kv"] > hi]):
        b = nearest(pick)
        if b is not None:
            return {"type": "substation", "bus": b["id"], "kv": b["kv"],
                    "dist_km": math.hypot(b["x"] - sx, b["y"] - sy) / 1000, "sub_osm_id": b["sub_osm_id"]}
    best = None
    for i, l in enumerate(network.lines):
        if l["kv"] < lo or not network.buses[l["f"]].get("supplied"):
            continue
        a, c = network.buses[l["f"]], network.buses[l["t"]]
        seg = LineString([(a["x"], a["y"]), (c["x"], c["y"])])
        d = seg.distance(Point(sx, sy))
        if best is None or d < best[0]:
            best = (d, i, seg.project(Point(sx, sy), normalized=True))
    if best is None:
        return None
    d, i, frac = best
    return {"type": "line_tap", "line": i, "frac": frac, "kv": network.lines[i]["kv"], "dist_km": d / 1000}


def _build_pp(network, P, county_peak_mw, county_pf, load_buses):
    net = pp.create_empty_network(sn_mva=100.0)
    for b in network.buses:
        pp.create_bus(net, vn_kv=b["kv"], index=b["id"], in_service=bool(b.get("supplied")))
    for i, l in enumerate(network.lines):
        if not network.buses[l["f"]].get("supplied"):
            continue
        kv, km = l["kv"], max(l["km"], 0.05)
        x = P.xkm[kv_band(kv)]
        r = x / P.x_over_r(kv)
        i_ka = P.rating_mva(kv) / (math.sqrt(3) * kv)
        pp.create_line_from_parameters(net, l["f"], l["t"], km, r, x, P.cfg["network"]["b_uS_per_km"] / (2 * math.pi * 60) * 1e3,
                                       i_ka, index=i, name=str(l["osm_id"]))
    for j, t in enumerate(network.trafos):
        if not network.buses[t["hv"]].get("supplied"):
            continue
        mva, _ = P.trafo_mva(t["kv_hv"], t["kv_lv"])
        pp.create_transformer_from_parameters(net, t["hv"], t["lv"], mva, t["kv_hv"], t["kv_lv"], 0.4, P.vk, 0.0, 0.0,
                                              index=j)
    for b in network.buses:
        if b.get("supplied") and not b["in_county"]:
            pp.create_ext_grid(net, b["id"], vm_pu=P.vm_ext)
    if load_buses:
        p_each = county_peak_mw / len(load_buses)
        q_each = p_each * math.tan(math.acos(county_pf))
        for b in load_buses:
            pp.create_load(net, b, p_each, q_each, name="county")
            q = P.reg_q_share * math.hypot(p_each, q_each)
            pp.create_gen(net, b, 0.0, vm_pu=P.reg_vm, min_q_mvar=-q, max_q_mvar=q, name="existing regulation")
    return net


def _solve(net):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            pp.runpp(net, algorithm="nr", init="dc", max_iteration=40, calculate_voltage_angles=True, numba=False,
                      enforce_q_lims=True)
            return "ac"
        except Exception:
            try:
                pp.rundcpp(net)
                return "dc"
            except Exception:
                return None


def load_buses_for(network):
    """Existing county load sits at the lowest-voltage bus of each supplied in-county
    substation (a distribution-serving proxy)."""
    out = []
    for s in network.substations:
        if not s["in_county"]:
            continue
        bs = [b for b in network.buses if b["node"] == s["node"] and b.get("supplied")]
        if bs:
            out.append(min(bs, key=lambda b: b["kv"])["id"])
    if not out:  # no supplied substation in the county: nearest supplied buses carry it
        out = [b["id"] for b in network.buses if b.get("supplied") and b["kind"] == "substation"][:1]
    return out


def run(network, site_xy, site_peak_mw, site_pf, county_peak_mw, county_pf, cfg, activsg, state, rng):
    P = Params(cfg, activsg, state, rng)
    ic = cfg["interconnection"]
    cls = interconnection_class(site_peak_mw, cfg, rng)
    lo, hi = ic["classes_kv"][cls]
    out = {"interconnection_class": cls, "interconnection_voltage_class_kv": [lo, hi], "activsg_case": P.case,
           "background_utilisation": P.bg}
    upgrades = []
    site_mva = site_peak_mw / site_pf
    q_site = site_peak_mw * math.tan(math.acos(site_pf))
    load_buses = load_buses_for(network)
    if not any(b.get("supplied") for b in network.buses):
        out.update(status="blocked", reason="no OSM transmission connected to a source in or around the county")
        return out

    # distribution class: new feeder from the nearest supplied substation, analytic drop
    if cls == "distribution":
        poi = choose_poi(network, site_xy, "subtransmission", cfg) or choose_poi(network, site_xy, "hv", cfg)
        if poi is None or poi["type"] != "substation":
            out.update(status="indeterminate", reason="no supplied substation for a distribution feeder")
            return out
        route = poi["dist_km"] * u(rng, ic["routing_factor"])
        v = 24.9
        x, r = 0.40 * route, 0.20 * route  # assumed 25 kV overhead feeder, ohm
        dv = (r * site_peak_mw + x * q_site) / v ** 2
        out.update(status="computed", poi=poi, new_line_km=route, new_line_kv=v,
                   min_voltage_pu=1.0 - dv, voltage_violations_n0=int(1.0 - dv < cfg["network"]["voltage_band_pu"][0]),
                   thermal_overloads_n0="indeterminate", max_loading_pct="indeterminate",
                   n1_contingency="indeterminate",
                   note="distribution class: 25 kV feeder, analytic voltage drop; substation loading not solved")
        upgrades.append({"type": "line_new", "kv": v, "km": route})
        out["required_upgrades"] = upgrades
        return out

    poi = choose_poi(network, site_xy, cls, cfg)
    if poi is None:
        out.update(status="indeterminate", reason=f"no supplied line or substation at or above {lo} kV")
        return out
    route = poi["dist_km"] * u(rng, ic["routing_factor"])
    out["poi"] = poi
    out["draws"] = {"background_utilisation": P.bg, "ext_grid_vm_pu": P.vm_ext, "regulation_vm_pu": P.reg_vm,
                    "regulation_q_share_of_load": P.reg_q_share, "x_ohm_per_km_poi_class": P.xkm[kv_band(poi["kv"])],
                    "rating_mva_poi_kv": P.rating_mva(poi["kv"]), "transformer_vk_percent": P.vk}
    out["new_line_km"] = route if poi["dist_km"] * 1000 >= ic["new_line_min_km"] * 1000 else 0.0

    net = _build_pp(network, P, county_peak_mw, county_pf, load_buses)
    base_mode = _solve(net)
    if base_mode is None:
        out.update(status="indeterminate", reason="base case did not solve")
        return out

    def snapshot(n):
        lim = 1.0 - P.bg
        lo_v, hi_v = cfg["network"]["voltage_band_pu"]
        ll = n.res_line.loading_percent / 100.0 if len(n.res_line) else []
        tl = n.res_trafo.loading_percent / 100.0 if len(n.res_trafo) else []
        over_l = {int(i) for i, v in zip(n.res_line.index, ll) if v > lim}
        over_t = {int(i) for i, v in zip(n.res_trafo.index, tl) if v > lim}
        inc = [b["id"] for b in network.buses if b["in_county"] and b.get("supplied")]
        vm = n.res_bus.vm_pu.reindex(inc).dropna() if base_mode == "ac" else None
        bad_v = set() if vm is None else {int(i) for i, v in vm.items() if v < lo_v or v > hi_v}
        mx = max([0.0] + [float(x) for x in ll] + [float(x) for x in tl]) / max(lim, 1e-6)
        return over_l, over_t, bad_v, mx, (float(vm.min()) if vm is not None and len(vm) else None)

    b_ol, b_ot, b_v, _, b_vmin = snapshot(net)
    # Calibrate existing regulation to an observed operating fact: today's grid serves today's
    # load inside ANSI Range A. Scale the reactive limits until the base case is in band.
    scale = 1.0
    for _ in range(cfg["network"]["regulation_calibration_steps"]):
        if not b_v or base_mode != "ac" or not len(net.gen):
            break
        scale *= 1.5
        net.gen["min_q_mvar"] *= 1.5
        net.gen["max_q_mvar"] *= 1.5
        base_mode = _solve(net)
        if base_mode is None:
            break
        b_ol, b_ot, b_v, _, b_vmin = snapshot(net)
    base_ok = base_mode == "ac" and not b_v
    out["base_case"] = {"solve": base_mode, "voltage_violations": len(b_v), "thermal_overloads": len(b_ol) + len(b_ot),
                        "min_voltage_pu": b_vmin, "regulation_scale": scale, "in_band": base_ok}
    if base_mode is None:
        out.update(status="indeterminate", reason="base case did not solve after regulation calibration")
        return out

    origin = {i: i for i in range(len(network.lines))}  # pandapower line index -> network line

    # connect the site
    if poi["type"] == "line_tap":
        li = poi["line"]
        l = network.lines[li]
        a, c = network.buses[l["f"]], network.buses[l["t"]]
        tx, ty = a["x"] + poi["frac"] * (c["x"] - a["x"]), a["y"] + poi["frac"] * (c["y"] - a["y"])
        tap = pp.create_bus(net, vn_kv=l["kv"], name="switching station")
        row = net.line.loc[li]
        net.line.at[li, "in_service"] = False
        for f_, t_, share in ((l["f"], tap, poi["frac"]), (tap, l["t"], 1 - poi["frac"])):
            pp.create_line_from_parameters(net, f_, t_, max(row.length_km * share, 0.05), row.r_ohm_per_km,
                                           row.x_ohm_per_km, row.c_nf_per_km, row.max_i_ka, name=row["name"])
        for k in net.line.index[net.line.name == row["name"]]:
            if k != li:
                origin[int(k)] = li
        poi_bus = tap
        upgrades.append({"type": "substation", "subtype": "new switching station on existing line", "kv": l["kv"],
                         "mva": site_mva})
    else:
        poi_bus = poi["bus"]
    site_bus = pp.create_bus(net, vn_kv=poi["kv"], name="site")
    kv = poi["kv"]
    x = P.xkm[kv_band(kv)]
    pp.create_line_from_parameters(net, poi_bus, site_bus, max(route, 0.05), x / P.x_over_r(kv), x,
                                   cfg["network"]["b_uS_per_km"] / (2 * math.pi * 60) * 1e3,
                                   max(P.rating_mva(kv), 2 * site_mva) / (math.sqrt(3) * kv), name="site tap")
    pp.create_load(net, site_bus, site_peak_mw, q_site, name="site")
    mode = _solve(net)
    if mode is None:
        out.update(status="computed", solve="diverged", voltage_violations_n0=1, thermal_overloads_n0="indeterminate",
                   max_loading_pct="indeterminate", min_voltage_pu=None, n1_contingency="indeterminate",
                   note="AC and DC power flow failed with the site connected: treated as one voltage violation "
                        "(the grid model cannot carry the load), not as a pass")
        upgrades.append({"type": "voltage_support", "mvar": site_peak_mw * 0.5})
        out["required_upgrades"] = upgrades
        return out

    s_ol, s_ot, s_v, mx, vmin = snapshot(net)
    site_vm = float(net.res_bus.vm_pu.at[site_bus]) if mode == "ac" else None
    lo_v, hi_v = cfg["network"]["voltage_band_pu"]
    new_ol, new_ot = s_ol - b_ol, s_ot - b_ot
    new_v = s_v - b_v
    site_v_bad = site_vm is not None and not (lo_v <= site_vm <= hi_v)

    upgrades.insert(0, {"type": "substation", "subtype": "new customer substation", "kv": kv, "mva": site_mva})
    if out["new_line_km"] > 0:
        upgrades.append({"type": "line_new", "kv": kv, "km": out["new_line_km"]})
    rebuilt = set()
    for i in sorted(new_ol):
        li = origin.get(i)
        if li is not None and li not in rebuilt:
            rebuilt.add(li)
            l = network.lines[li]
            upgrades.append({"type": "line_rebuild", "kv": l["kv"], "km": l["km"], "osm_id": l["osm_id"]})
    for j in sorted(new_ot):
        t = network.trafos[j]
        lim = 1.0 - P.bg
        loading = float(net.res_trafo.loading_percent.at[j]) / 100.0
        mva = float(net.trafo.sn_mva.at[j]) * (loading - lim)
        upgrades.append({"type": "substation", "subtype": "transformer expansion", "kv": t["kv_hv"],
                         "mva": max(mva, 0.0)})
    nviol = len(new_v) + int(site_v_bad)
    if nviol:
        upgrades.append({"type": "voltage_support", "mvar": site_peak_mw * u(rng, [0.2, 0.5])})

    out.update(status="computed", solve=mode,
               thermal_overloads_n0=len(new_ol) + len(new_ot),
               thermal_overloads_n0_including_preexisting=len(s_ol) + len(s_ot),
               max_loading_pct=100 * mx,
               voltage_violations_n0=nviol if (mode == "ac" and base_ok) else "indeterminate",
               voltage_note=None if base_ok else "base case out of band after calibration: voltage not attributable",
               voltage_violations_n0_including_preexisting=(len(s_v) + int(site_v_bad)) if mode == "ac" else "indeterminate",
               min_voltage_pu=min([v for v in (vmin, site_vm) if v is not None], default=None),
               site_voltage_pu=site_vm,
               n1_contingency="indeterminate",
               required_upgrades=upgrades)
    return out

