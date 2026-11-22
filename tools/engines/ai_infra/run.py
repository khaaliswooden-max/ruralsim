"""Run the AI-infrastructure screening engine (power_flow + rate_impact) on a card.

    python3 -m tools.engines.ai_infra.run EXP-0011 --seeds 20
    python3 -m tools.engines.ai_infra.run EXP-0011 --county 01131 --seeds 5

Writes one immutable ledger record per run to experiments/ledger/<card>/. Every result is
graded SPECULATIVE. Misses and indeterminate criteria are listed before anything else.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from shapely.geometry import Point, Polygon
from shapely.ops import nearest_points, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.engines.ai_infra import cooling_water, data, fiber, flood, gate, network, power_flow, rate_impact  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LEDGER = ROOT / "experiments" / "ledger"
CARDS = ROOT / "experiments" / "ai_infra_cards.yaml"
DISCLOSURE = "Simulated, screening-grade results with assumed parameters. Decision support, not a finding."


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git_commit() -> str:
    try:
        c = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                           check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "tools/engines"],
                               capture_output=True, text=True).stdout.strip()
        return c + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


def environment() -> dict:
    """Library versions that produced the record (D-103)."""
    import importlib.metadata as md
    import platform
    out = {"python": platform.python_version()}
    for p in ("pandapower", "pandas", "numpy", "scipy", "pyarrow", "networkx", "shapely", "pyproj", "PyYAML"):
        try:
            out[p] = md.version(p)
        except md.PackageNotFoundError:
            out[p] = None
    return out


def band(xs):
    xs = [x for x in xs if isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x))]
    if not xs:
        return None
    return {"p10": float(np.percentile(xs, 10)), "p50": float(np.percentile(xs, 50)),
            "p90": float(np.percentile(xs, 90)), "n": len(xs)}


def site_point(county, poly, tribal_polys, spec):
    """Card site rule. Returns (x, y, note)."""
    if spec.get("rule") == "point":
        f, _ = county.enu
        x, y = f(spec["lon"], spec["lat"])
        note = "given point"
    else:
        c = poly.representative_point() if not poly.contains(poly.centroid) else poly.centroid
        x, y, note = c.x, c.y, "county centroid"
    p = Point(x, y)
    tribal = unary_union(tribal_polys) if tribal_polys else None
    if tribal is not None and tribal.contains(p):
        allowed = poly.difference(tribal.buffer(100))
        if allowed.is_empty:
            return None, None, "county is entirely tribal land: no site (siting constraint)"
        q = nearest_points(allowed, p)[0]
        return q.x, q.y, note + " was on tribal land (siting constraint); moved to the nearest county point outside it"
    return x, y, note


def county_load(fips5, cands, tier, cfg, rng):
    row = tier[tier.fips5 == fips5].iloc[0]
    hh = row.pop_2024_estimate / row.avg_hh_size
    have = [c for c in cands if "residential_mwh" in c]
    if not have:
        return None, {"status": "indeterminate", "reason": "no candidate utility has EIA-861 sales"}
    kwh = sum(c["residential_mwh"] for c in have) * 1000 / sum(c["residential_customers"] for c in have)
    ratio = sum(c["total_mwh"] for c in have) / sum(c["residential_mwh"] for c in have)
    avg_mw = hh * kwh * ratio / 8760 / 1000
    lf = power_flow.u(rng, cfg["load"]["county_load_factor"])
    return avg_mw / lf, {"households_derived": hh, "residential_kwh_per_customer": kwh,
                         "total_to_residential_ratio": ratio, "county_avg_mw": avg_mw}


def run_county(card, fips5, seeds, cfg, activsg, backtest_id=None):
    bt = gate.check(fips5, backtest_id, data.eia_available)
    county = data.County(fips5)
    tier = data.tier_a()
    trow = tier[tier.fips5 == fips5].iloc[0]
    state = trow.state_abbr
    f_enu, f_wgs = county.enu
    b = county.json("viewer_data/boundaries.json")
    poly = unary_union([Polygon(p).buffer(0) for p in b["county_parts"]])
    tribal = []
    for t in b.get("tribal") or []:
        rings = t.get("rings") if isinstance(t, dict) else t
        for r in (rings if rings and isinstance(rings[0][0], (list, tuple)) else [rings]):
            try:
                tribal.append(Polygon(r).buffer(0))
            except Exception:
                pass
    sx, sy, site_note = site_point(county, poly, tribal, card.get("site", {}))
    modules = card.get("modules", ["power_flow", "rate_impact"])
    power = "power_flow" in modules
    rec = {"county": {**county.record(), "state": state, "rucc_2023": int(trow.rucc_2023)},
           "modules": modules, "backtest": bt}
    if power:
        feats = county.json("layers_raw/osm/power.geojson")["features"]
        masked = []
        net = network.build(feats, f_enu, poly, cfg["network"], masked_sub_ids=[m["osm_id"] for m in masked])
        cands = rate_impact.candidates(fips5, state, data.eia)
        acs = data.acs_income_quintiles()
        arow = acs[acs.fips5 == fips5]
        arow = arow.iloc[0].to_dict() if len(arow) else None
        rec.update(network=net.summary, candidate_utilities=cands)
    if sx is None:
        rec["site"] = {"note": site_note}
        rec["scenarios"] = {}
        return rec
    lon, lat = f_wgs(sx, sy)
    rec["site"] = {"lon": lon, "lat": lat, "enu_m": [sx, sy], "note": site_note, "provenance": "hypothetical"}
    if "cooling_water" in modules:
        wctx = water_context(county, fips5, lat, lon, cfg)
        rec["water_context"] = {k: v for k, v in wctx.items() if k != "weather"}
    if "fiber" in modules:
        asof = cfg["fiber"]["bdc_as_of"]
        _hex = _fiber_hexes(asof)
        crow = data.bdc_fiber(asof, "fiber_county")
        crow = crow[crow.fips5 == fips5]
        fib = fiber.run(lat, lon, _hex, crow.iloc[0].to_dict() if len(crow) else None, cfg["fiber"]["search_radius_km"])
        rec["fiber_context"] = {"bdc_as_of": asof}
    if "flood" in modules:
        fstat = flood.county_status(data.nfhl_status(), fips5)
        fzones = flood.prepare(data.nfhl_zones(fips5), f_enu, (sx, sy), cfg["flood"]["search_m"]) \
            if fstat and fstat["status"] != "none" else []
        rec["flood_context"] = {"county_status": fstat, "zones_within_search": len(fzones)}

    scen_out = {}
    for si, sc in enumerate(card["scenarios"]):
        per_seed = []
        for seed in range(seeds):
            # Common random numbers: one stream per component, keyed on (county, seed) only, so
            # both scenarios and all three allocations see identical draws except the on-site ones.
            r_load, r_on, r_cty, r_pf = (np.random.default_rng([int(fips5), seed, k]) for k in (1, 2, 3, 4))
            rng = r_load
            L = cfg["load"]
            pue = power_flow.u(rng, L["pue"])
            lf = power_flow.u(rng, L["facility_load_factor"])
            pf = power_flow.u(rng, L["facility_power_factor"])
            if card.get("load_input") == "facility_avg_mw":  # conditional back-test (D-201)
                it = sc["facility_avg_mw"] / (pue * lf)
            else:
                it = sc["it_load_mw"]
            peak = it * pue
            avg = peak * lf
            on = sc.get("onsite") or {}
            o = cfg["onsite"]
            st_credit = on.get("storage_mwh", 0) / o["storage_duration_h"] * power_flow.u(r_on, o["storage_peak_availability"])
            net_peak = max(peak - on.get("firm_mw", 0) - st_credit - on.get("solar_mw", 0) * o["solar_peak_credit"], 0.0)
            solar_mwh = on.get("solar_mw", 0) * 8760 * power_flow.u(r_on, cfg["onsite"]["solar_capacity_factor"])
            grid_mwh = max(avg * 8760 - solar_mwh, 0.0)
            onsite_capex = (on.get("solar_mw", 0) * power_flow.u(r_on, cfg["costs"]["solar_musd_per_mw"])
                            + on.get("storage_mwh", 0) * power_flow.u(r_on, cfg["costs"]["storage_musd_per_mwh"])
                            + on.get("firm_mw", 0) * power_flow.u(r_on, cfg["costs"]["firm_musd_per_mw"])) * 1e6
            if "fiber" in modules:
                per_seed.append({"seed": seed, "fiber": fib})
                continue
            if "flood" in modules:
                fo = flood.run(fstat, fzones, (sx, sy), cfg, np.random.default_rng([int(fips5), seed, 7]))
                per_seed.append({"seed": seed, "flood": fo})
                continue
            if not power:
                cw = cooling_water.run(wctx["weather"], avg / pue, pue, sc["cooling"], wctx["county_use"],
                                       (wctx["source_gauge"], wctx["nearest_gauge"]), wctx["community_water_systems"],
                                       cfg, np.random.default_rng([int(fips5), seed, 6]))
                per_seed.append({"seed": seed, "inputs": {"it_load_mw": it, "pue": pue, "facility_load_factor": lf,
                                                          "it_avg_mw": avg / pue}, "cooling_water": cw})
                continue
            cpeak, cinfo = county_load(fips5, cands, tier, cfg, r_cty)
            cpf = power_flow.u(r_cty, L["county_power_factor"])
            if cpeak is None:
                pfo = {"status": "blocked", "reason": cinfo["reason"]}
            else:
                pfo = power_flow.run(net, (sx, sy), net_peak, pf, cpeak, cpf, cfg, activsg, state, r_pf)
            rates = {}
            for ai, alloc in enumerate(rate_impact.ALLOCATIONS):
                rr = np.random.default_rng([int(fips5), seed, 5])  # same draws for every allocation and scenario
                if pfo.get("status") == "computed":
                    rates[alloc] = rate_impact.run(cands, pfo.get("required_upgrades"),
                                                   {"peak_mw_net": net_peak, "grid_mwh": grid_mwh},
                                                   {"capex_usd": onsite_capex}, alloc, arow, cfg, rr)
                else:
                    rates[alloc] = {"status": "blocked", "reason": f"power_flow {pfo.get('status')}"}
            per_seed.append({"seed": seed, "inputs": {"it_load_mw": it, "pue": pue, "facility_load_factor": lf,
                                                      "facility_peak_mw": peak, "net_peak_mw": net_peak,
                                                      "grid_mwh": grid_mwh, "county_peak_mw": cpeak,
                                                      "county_load_info": cinfo, "onsite_capex_usd": onsite_capex},
                             "power_flow": pfo, "rate_impact": rates})
        summ = (summarise(per_seed, cands) if power else
                {"fiber": True, **per_seed[0]["fiber"]} if "fiber" in modules else
                summarise_flood(per_seed) if "flood" in modules else summarise_water(per_seed))
        scen_out[sc["name"]] = {"scenario": sc, "summary": summ, "seeds": per_seed}
    rec["scenarios"] = scen_out
    return rec


def water_context(county, fips5, lat, lon, cfg):
    """Per-county inputs for cooling_water, fixed across seeds."""
    w = data.usgs_wateruse_2015()
    row = w[w.fips5_2024 == fips5]
    cu = None
    if len(row):
        r = row.iloc[0]
        cu = {"ps_wfrto": float(r.ps_wfrto), "to_wfrto": float(r.to_wfrto), "ps_topop_thousands": float(r.ps_topop),
              "ps_per_capita_gpd": float(r.ps_wfrto * 1e6 / (r.ps_topop * 1000)) if r.ps_topop else None,
              "year": 2015, "units": "Mgal/d"}
    src, near = cooling_water.pick_gauges(data.nwis_gauges(), lat, lon, cfg["cooling"]["source_gauge_radius_km"])
    cws = {"status": "indeterminate: county SDWIS file not in snapshot"}
    try:
        ids = pd.read_csv(county.path(f"layers_raw/water_systems/sdwis_systems_{fips5}.csv"), dtype=str).pwsid
        q = data.sdwis_systems()
        a = q[q.pwsid.isin(ids) & (q.pws_activity_code == "A") & (q.pws_type_code == "CWS")]
        top = a.nlargest(1, "population_served_count")
        cws = {"active_cws": int(len(a)), "population_served": int(a.population_served_count.sum()),
               "by_source": {str(k): int(v) for k, v in a.gw_sw_code.value_counts().items()},
               "largest": (None if top.empty else {"pwsid": top.pwsid.iloc[0], "pws_name": top.pws_name.iloc[0],
                                                   "population_served": int(top.population_served_count.iloc[0]),
                                                   "gw_sw_code": top.gw_sw_code.iloc[0]})}
    except FileNotFoundError:
        pass
    return {"weather": data.power_daily(fips5), "county_use": cu, "source_gauge": src, "nearest_gauge": near,
            "community_water_systems": cws, "flow_note": "flow at the gauge; drainage-area scale factor 1.0 (site drainage "
                                                          "area needs NHDPlus, not a layer)"}


_HEX = {}


def _fiber_hexes(asof):
    if asof not in _HEX:
        _HEX[asof] = fiber.hex_table(data.bdc_fiber(asof, "fiber_h3"))
    return _HEX[asof]


def summarise_flood(per_seed):
    fo = [s["flood"] for s in per_seed]
    st = _counts([x["status"] for x in fo])
    comp = [x for x in fo if x["status"] == "computed"]

    def b(k):
        return band([x[k] for x in comp if isinstance(x.get(k), (int, float))])
    return {"flood": True, "status_counts": st, "map_status": fo[0].get("map_status"),
            "reason": next((x.get("reason") for x in fo if x["status"] != "computed"), None),
            "site_point_zone": comp[0].get("site_point_zone") if comp else None,
            "site_point_in_sfha": comp[0].get("site_point_in_sfha") if comp else None,
            "footprint_area_ha": b("footprint_area_ha"), "footprint_share_sfha": b("footprint_share_sfha"),
            "footprint_share_x_shaded": b("footprint_share_x_shaded"), "footprint_share_zone_d": b("footprint_share_zone_d"),
            "distance_to_sfha_m": comp[0].get("distance_to_sfha_m") if comp else None,
            "flags": sorted({f for x in fo for f in x.get("flags", [])}),
            "effective_dates": fo[0].get("effective_dates")}


def summarise_water(per_seed):
    cws = [s["cooling_water"] for s in per_seed]

    def b(key, scale=1.0):
        return band([c[key] * scale for c in cws if isinstance(c.get(key), (int, float)) and math.isfinite(c[key])])

    lf = [c.get("share_of_source_low_flow_peak_day") for c in cws]
    return {"cooling_type": cws[0]["cooling_type"],
            "annual_withdrawal_m3": b("annual_withdrawal_m3"), "annual_withdrawal_gallons": b("annual_withdrawal_gallons"),
            "annual_consumption_m3": b("annual_consumption_m3"), "peak_day_withdrawal_m3": b("peak_day_withdrawal_m3"),
            "wue_l_per_it_kwh": b("wue_l_per_it_kwh"), "pue_effective_annual": b("pue_effective_annual"),
            "share_of_county_public_supply": b("share_of_county_public_supply"),
            "share_of_county_fresh_withdrawals": b("share_of_county_fresh_withdrawals"),
            "equivalent_people_at_county_public_supply_rate": b("equivalent_people_at_county_public_supply_rate"),
            "share_of_source_low_flow_peak_day": b("share_of_source_low_flow_peak_day"),
            "share_seeds_source_low_flow_zero_and_withdrawal": sum(1 for x in lf if x == math.inf) / len(lf),
            "source_low_flow_status": next((x for x in lf if isinstance(x, str)), None),
            "share_of_nearest_low_flow_peak_day_unscored": b("share_of_nearest_low_flow_peak_day_unscored"),
            "water_within_recharge": "indeterminate"}


def summarise(per_seed, cands):
    pfs = [s["power_flow"] for s in per_seed]
    st = {}
    for p in pfs:
        st[p.get("status")] = st.get(p.get("status"), 0) + 1
    comp = [p for p in pfs if p.get("status") == "computed"]

    def share(pred):
        return sum(1 for p in comp if pred(p)) / len(comp) if comp else None

    pf = {"status_counts": st,
          "interconnection_class_counts": _counts([p.get("interconnection_class") for p in pfs]),
          "poi_type_counts": _counts([(p.get("poi") or {}).get("type") for p in comp]),
          "poi_kv": band([(p.get("poi") or {}).get("kv") for p in comp]),
          "poi_distance_km": band([(p.get("poi") or {}).get("dist_km") for p in comp]),
          "new_line_km": band([p.get("new_line_km") for p in comp]),
          "thermal_overloads_n0": band([p.get("thermal_overloads_n0") for p in comp]),
          "voltage_violations_n0": band([p.get("voltage_violations_n0") for p in comp]),
          "max_loading_pct": band([p.get("max_loading_pct") for p in comp]),
          "min_voltage_pu": band([p.get("min_voltage_pu") for p in comp]),
          "share_seeds_any_voltage_violation": share(lambda p: isinstance(p.get("voltage_violations_n0"), int)
                                                     and p["voltage_violations_n0"] > 0),
          "share_seeds_voltage_indeterminate": share(lambda p: not isinstance(p.get("voltage_violations_n0"), int)),
          "share_seeds_any_thermal_overload": share(lambda p: isinstance(p.get("thermal_overloads_n0"), int)
                                                    and p["thermal_overloads_n0"] > 0),
          "share_seeds_new_substation": share(lambda p: any(u["type"] == "substation" for u in p.get("required_upgrades", []))),
          "share_seeds_new_line_ge_69kv": share(lambda p: (p.get("new_line_km") or 0) > 0 and (p.get("poi") or {}).get("kv", 0) >= 69),
          "n1_contingency": "indeterminate",
          "sensitivity_spearman_max_loading": _pf_sens(per_seed, "max_loading_pct"),
          "sensitivity_spearman_min_voltage": _pf_sens(per_seed, "min_voltage_pu")}
    rates = {}
    for alloc in rate_impact.ALLOCATIONS:
        per_u = {}
        cap = []
        for s in per_seed:
            r = s["rate_impact"][alloc]
            if "per_utility" not in r:
                continue
            cap.append(r["upgrade_capex_usd"])
            for x in r["per_utility"]:
                per_u.setdefault(x["utility_number"], []).append(x)
        out_u = {}
        for c in cands:
            xs = per_u.get(c["utility_number"], [])
            comp_u = [x for x in xs if x["status"] == "computed"]
            out_u[str(c["utility_number"])] = {
                "utility_name": c["utility_name"], "ownership": c["ownership"],
                "status": "computed" if comp_u else "indeterminate",
                "reason": None if comp_u else (xs[0]["reason"] if xs else "power_flow not computed"),
                "lowest_quintile_rate_change_pct": band([x["lowest_quintile_rate_change_pct"] for x in comp_u]),
                "lowest_quintile_bill_change_usd_per_yr": band([x["lowest_quintile_bill_change_usd_per_yr"] for x in comp_u]),
                "rate_basis": c.get("rate_basis"),
                "site_share_of_utility_sales": band([x["site_share_of_utility_sales"] for x in comp_u]),
                "share_seeds_outside_validity": (sum(x["outside_validity"] for x in comp_u) / len(comp_u)) if comp_u else None,
                "lowest_quintile_energy_cost_share_change_pp": (
                    band([x["lowest_quintile_energy_cost_share_change_pp"] for x in comp_u])
                    or (rate_impact.INCOME_MISSING if comp_u else None)),
            }
        rates[alloc] = {"upgrade_capex_usd": band(cap), "per_utility": out_u,
                        "sensitivity_spearman": sensitivity(per_seed, alloc, cands)}
    return {"power_flow": pf, "rate_impact": rates}


def sensitivity(per_seed, alloc, cands):
    """Spearman rank correlation, across seeds, between each sampled input and the
    lowest-quintile rate change, per candidate utility. Card schema: an assumed-floor
    result needs a sensitivity analysis over its assumed inputs."""
    from scipy.stats import spearmanr
    out = {}
    for c in cands:
        ys, xs = [], {}
        for s in per_seed:
            r = s["rate_impact"][alloc]
            x = next((x for x in r.get("per_utility", []) if x["utility_number"] == c["utility_number"]
                      and x["status"] == "computed"), None)
            if x is None:
                continue
            ys.append(x["lowest_quintile_rate_change_pct"])
            d = dict(r["draws"])
            d["pue"] = s["inputs"]["pue"]
            d["facility_load_factor"] = s["inputs"]["facility_load_factor"]
            d["background_utilisation"] = s["power_flow"].get("background_utilisation")
            for k, v in d.items():
                xs.setdefault(k, []).append(v)
        if len(ys) < 5 or np.std(ys) == 0:
            continue
        rho = {}
        for k, v in xs.items():
            if len(set(v)) > 1 and None not in v:
                r_ = spearmanr(v, ys).statistic
                if not np.isnan(r_):
                    rho[k] = round(float(r_), 2)
        out[str(c["utility_number"])] = dict(sorted(rho.items(), key=lambda kv: -abs(kv[1])))
    return out


def _pf_sens(per_seed, key):
    from scipy.stats import spearmanr
    ys, xs = [], {}
    for s in per_seed:
        p = s["power_flow"]
        if p.get("status") != "computed" or not isinstance(p.get(key), (int, float)):
            continue
        d = dict(p.get("draws") or {})
        d.update(pue=s["inputs"]["pue"], facility_load_factor=s["inputs"]["facility_load_factor"],
                 county_peak_mw=s["inputs"]["county_peak_mw"])
        ys.append(p[key])
        for k, v in d.items():
            xs.setdefault(k, []).append(v)
    if len(ys) < 5 or np.std(ys) == 0:
        return None
    out = {}
    for k, v in xs.items():
        if len(v) == len(ys) and len(set(v)) > 1:
            r_ = spearmanr(v, ys).statistic
            if not np.isnan(r_):
                out[k] = round(float(r_), 2)
    return dict(sorted(out.items(), key=lambda kv: -abs(kv[1])))


def _counts(xs):
    d = {}
    for x in xs:
        d[str(x)] = d.get(str(x), 0) + 1
    return d


def judge(card, rec):
    """Card success criterion -> misses (incl. indeterminate) and passes."""
    crit = card["criterion"]
    misses, passes = [], []
    f = rec["county"]["fips5"]
    if not rec["scenarios"]:
        misses.append({"county": f, "criterion": "site", "status": "blocked", "value": rec["site"]["note"]})
    for name, sc in rec["scenarios"].items():
        if sc["summary"].get("fiber"):
            w = sc["summary"]
            km, need = w.get("nearest_fiber_hex_km"), crit["nearest_fiber_hex_km_max"]
            item = {"county": f, "scenario": name, "criterion": "fiber at or near the site (hexagon level)",
                    "threshold": f"fiber in the site hexagon or a fiber hexagon within {need} km (centroid to centroid)"}
            v = {"fiber_in_site_hex": w["fiber_in_site_hex"], "nearest_fiber_hex_km": km}
            (passes if km is not None and km <= need else misses).append(
                {**item, "status": "pass" if km is not None and km <= need else "miss", "value": v})
            n, pmin = w["county_fiber_providers"], crit["county_fiber_providers_min"]
            item = {"county": f, "scenario": name, "criterion": "fiber providers in the county",
                    "threshold": f">= {pmin} distinct providers"}
            (passes if n >= pmin else misses).append({**item, "status": "pass" if n >= pmin else "miss",
                                                      "value": {"providers": n, "brands": w.get("county_fiber_brands")}})
            misses.append({"county": f, "scenario": name, "criterion": "middle-mile / long-haul fiber",
                           "status": "indeterminate", "value": "not observed in any public layer"})
            continue
        if sc["summary"].get("flood"):
            w = sc["summary"]
            bar = crit["footprint_share_sfha_max"]
            item = {"county": f, "scenario": name, "criterion": "site footprint in the 1% annual-chance flood zone (SFHA)",
                    "threshold": f"site point outside the SFHA and p50 footprint share <= {bar:.0%}", "flags": w["flags"]}
            if w["status_counts"].get("computed", 0) < sum(w["status_counts"].values()):
                misses.append({**item, "status": "indeterminate", "value": w["reason"]})
            elif w["site_point_in_sfha"] or round(w["footprint_share_sfha"]["p50"], 9) > bar:
                misses.append({**item, "status": "miss", "value": {"site_point_zone": w["site_point_zone"],
                                                                     "footprint_share_sfha": w["footprint_share_sfha"]}})
            else:
                passes.append({**item, "status": "pass", "value": {"site_point_zone": w["site_point_zone"],
                                                                     "footprint_share_sfha": w["footprint_share_sfha"],
                                                                     "distance_to_sfha_m": w["distance_to_sfha_m"]}})
            continue
        if "power_flow" not in sc["summary"]:
            w = sc["summary"]
            for key, label, bar in (("share_of_source_low_flow_peak_day", "peak-day withdrawal vs source-gauge low flow (p10_min)",
                                     crit["peak_day_share_of_low_flow_max"]),
                                    ("share_of_county_public_supply", "annual withdrawal vs county public supply (USGS 2015)",
                                     crit["annual_share_of_public_supply_max"])):
                item = {"county": f, "scenario": name, "criterion": label, "threshold": f"p50 <= {bar:.0%}"}
                bnd = w.get(key)
                if key == "share_of_source_low_flow_peak_day" and w["share_seeds_source_low_flow_zero_and_withdrawal"] > 0.5:
                    misses.append({**item, "status": "miss", "value": "source low flow (p10_min) is 0 cfs and the site withdraws water"})
                elif key == "share_of_source_low_flow_peak_day" and w.get("source_low_flow_status"):
                    misses.append({**item, "status": "indeterminate", "value": w["source_low_flow_status"]})
                elif bnd is None:
                    misses.append({**item, "status": "indeterminate", "value": "no data"})
                elif round(bnd["p50"], 9) > bar:
                    misses.append({**item, "status": "miss", "value": bnd})
                else:
                    passes.append({**item, "status": "pass", "value": bnd})
            misses.append({"county": f, "scenario": name, "criterion": "water_within_recharge", "status": "indeterminate",
                           "value": "no modelled sustainable yield"})
            continue
        pf = sc["summary"]["power_flow"]
        n = sum(pf["status_counts"].values())
        comp = pf["status_counts"].get("computed", 0)
        if comp < n:
            misses.append({"county": f, "scenario": name, "criterion": "power_flow computed in every seed",
                           "status": "indeterminate", "value": pf["status_counts"]})
        for key, label in (("share_seeds_any_voltage_violation", "voltage"), ("share_seeds_any_thermal_overload", "thermal")):
            v = pf[key]
            thr = round(1 - crit["grid_clean_seed_share"], 9)  # 1 - 0.9 is 0.0999... in floating point
            item = {"county": f, "scenario": name, "criterion": f"no {label} violation in >= {crit['grid_clean_seed_share']:.0%} of seeds",
                    "threshold": f"share of seeds with a violation <= {thr:.0%}", "value": v}
            if v is None:
                misses.append({**item, "status": "indeterminate"})
            elif label == "voltage" and (pf["share_seeds_voltage_indeterminate"] or 0) > 0:
                misses.append({**item, "status": "indeterminate",
                               "note": f"voltage indeterminate in {pf['share_seeds_voltage_indeterminate']:.0%} of computed seeds (DC fallback)"})
            elif round(v, 9) > thr:
                misses.append({**item, "status": "miss"})
            else:
                passes.append({**item, "status": "pass"})
        for alloc, r in sc["summary"]["rate_impact"].items():
            for un, x in r["per_utility"].items():
                item = {"county": f, "scenario": name, "allocation": alloc, "utility": f"{x['utility_name']} ({un})",
                        "rate_basis": x.get("rate_basis"),
                        "criterion": "protect_lowest_income_quintile", "threshold": f"p50 <= {crit['rate_change_pct_max']}%"}
                b = x["lowest_quintile_rate_change_pct"]
                ov = x.get("share_seeds_outside_validity")
                if b is None:
                    misses.append({**item, "status": "indeterminate", "value": x["reason"]})
                elif ov and ov > 0.5:
                    sh = x["site_share_of_utility_sales"]["p50"]
                    lim = yaml.safe_load((HERE / "params" / "assumed.yaml").read_text())["rates"]["max_site_share_of_utility_sales"]
                    misses.append({**item, "status": "indeterminate", "value": b,
                                   "note": f"site would be {sh:.2f}x this utility's annual sales, above the rate "
                                           f"model's validity limit of {lim}; the outcome depends on the large-load "
                                           "contract, which is not modelled"})
                elif b["p50"] > crit["rate_change_pct_max"]:
                    misses.append({**item, "status": "miss", "value": b})
                else:
                    passes.append({**item, "status": "pass", "value": b})
    order = {"miss": 0, "indeterminate": 1, "blocked": 1}
    misses.sort(key=lambda m: order.get(m["status"], 2))
    return misses, passes


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("card")
    ap.add_argument("--county", action="append")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--backtest")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)
    cards = {c["id"]: c for c in yaml.safe_load(CARDS.read_text())}
    card = cards[a.card]
    cfg = yaml.safe_load((HERE / "params" / "assumed.yaml").read_text())
    activsg = json.loads((HERE / "params" / "activsg_distributions.json").read_text())
    counties = a.county or card["counties"]
    t0 = dt.datetime.now(dt.UTC)
    recs, misses, passes, refused = [], [], [], []
    for fips5 in counties:
        try:
            r = run_county(card, fips5, a.seeds, cfg, activsg, a.backtest)
        except gate.Refused as e:
            refused.append({"county": fips5, "reason": str(e)})
            continue
        m, p = judge(card, r)
        misses += m
        passes += p
        recs.append(r)
    rank = {"miss": 0, "indeterminate": 1, "blocked": 1}
    misses.sort(key=lambda m: rank.get(m["status"], 2))   # misses first across all counties, not only within each
    out = {
        "run_id": f"{card['id']}/{t0.strftime('%Y%m%dT%H%M%SZ')}",
        "card_id": card["id"], "supersedes": card.get("supersedes"),
        "engine": "tools/engines/ai_infra", "engine_version": git_commit(), "spec_version": "0.1",
        "params_sha256": sha(HERE / "params" / "assumed.yaml"),
        "activsg_sha256": sha(HERE / "params" / "activsg_distributions.json"),
        "eia_tables": {"year": 2024, "meta": data.eia_meta(2024)},
        "acs_tables": {"year": 2024, "meta": data.acs_meta(2024)},
        "water_tables": data.water_meta() if "cooling_water" in card.get("modules", []) else None,
        "flood_tables": data.nfhl_meta() if "flood" in card.get("modules", []) else None,
        "bdc_tables": data.bdc_meta(cfg["fiber"]["bdc_as_of"]) if "fiber" in card.get("modules", []) else None,
        "environment": environment(),
        "grade": "SPECULATIVE", "disclosure": DISCLOSURE,
        "seeds": a.seeds, "mode": ("deterministic (no sampled input; one evaluation)" if card.get("deterministic")
                                   else "promotable-count" if a.seeds >= 20 else "screening"),
        "provenance_floor": "assumed",
        "criterion": card["criterion"],
        "misses": misses, "refused": refused, "passes": passes,
        "counties": recs,
        "not_modelled": ["N-1 contingency", "regional through-flow (background_utilisation stands in)",
                         "local tax effects and abatements", "middle-mile and long-haul fiber",
                         "drainage-area scaling between gauge and site (needs NHDPlus)",
                         "which utility actually serves the site (all candidates run)"],
    }
    if not a.no_write:
        d = LEDGER / card["id"]
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{t0.strftime('%Y%m%dT%H%M%S')}_{a.seeds}seeds.json"
        p.write_text(json.dumps(out, indent=1, default=float))
        print("wrote", p.relative_to(ROOT))
    print(f"misses/indeterminate: {len(misses)}  passes: {len(passes)}  refused: {len(refused)}")
    return out


if __name__ == "__main__":
    main()
