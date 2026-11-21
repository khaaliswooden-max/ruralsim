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
import yaml
from shapely.geometry import Point, Polygon
from shapely.ops import nearest_points, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.engines.ai_infra import data, gate, network, power_flow, rate_impact  # noqa: E402
from tools.harness import households  # noqa: E402  (county_row strips political columns, D-007)

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
    feats = county.json("layers_raw/osm/power.geojson")["features"]
    masked = []
    net = network.build(feats, f_enu, poly, cfg["network"], masked_sub_ids=[m["osm_id"] for m in masked])
    cands = rate_impact.candidates(fips5, state, data.eia)
    crow = households.county_row(fips5)

    rec = {"county": {**county.record(), "state": state, "rucc_2023": int(trow.rucc_2023)},
           "network": net.summary, "candidate_utilities": cands, "backtest": bt}
    if sx is None:
        rec["site"] = {"note": site_note}
        rec["scenarios"] = {}
        return rec
    lon, lat = f_wgs(sx, sy)
    rec["site"] = {"lon": lon, "lat": lat, "enu_m": [sx, sy], "note": site_note, "provenance": "hypothetical"}

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
                                                   {"capex_usd": onsite_capex}, alloc, crow, cfg, rr)
                else:
                    rates[alloc] = {"status": "blocked", "reason": f"power_flow {pfo.get('status')}"}
            per_seed.append({"seed": seed, "inputs": {"it_load_mw": it, "pue": pue, "facility_load_factor": lf,
                                                      "facility_peak_mw": peak, "net_peak_mw": net_peak,
                                                      "grid_mwh": grid_mwh, "county_peak_mw": cpeak,
                                                      "county_load_info": cinfo, "onsite_capex_usd": onsite_capex},
                             "power_flow": pfo, "rate_impact": rates})
        scen_out[sc["name"]] = {"scenario": sc, "summary": summarise(per_seed, cands), "seeds": per_seed}
    rec["scenarios"] = scen_out
    return rec


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
                "lowest_quintile_energy_cost_share_change_pp": rate_impact.INCOME_SHARE_STATUS,
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
                        "criterion": "protect_lowest_income_quintile", "threshold": f"p50 <= {crit['rate_change_pct_max']}%"}
                b = x["lowest_quintile_rate_change_pct"]
                if b is None:
                    misses.append({**item, "status": "indeterminate", "value": x["reason"]})
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
    out = {
        "run_id": f"{card['id']}/{t0.strftime('%Y%m%dT%H%M%SZ')}",
        "card_id": card["id"], "supersedes": card.get("supersedes"),
        "engine": "tools/engines/ai_infra", "engine_version": git_commit(), "spec_version": "0.1",
        "params_sha256": sha(HERE / "params" / "assumed.yaml"),
        "activsg_sha256": sha(HERE / "params" / "activsg_distributions.json"),
        "eia_tables": {"year": 2024, "meta": data.eia_meta(2024)},
        "grade": "SPECULATIVE", "disclosure": DISCLOSURE,
        "seeds": a.seeds, "mode": "promotable-count" if a.seeds >= 20 else "screening",
        "provenance_floor": "assumed",
        "criterion": card["criterion"],
        "misses": misses, "refused": refused, "passes": passes,
        "counties": recs,
        "not_modelled": ["N-1 contingency", "regional through-flow (background_utilisation stands in)",
                         "local tax effects and abatements", "cooling water, fiber, flood (later PRs)",
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
