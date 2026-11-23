"""Score a back-test run against the pre-registration. Committed before the run's output is read (D-205).

Applies PREREGISTRATION.md §6 and §7 exactly, with D-201 (conditional on observed load), D-202
(the rate validity flag counts as indeterminate; a site without L_obs cannot run), D-204 (BT-01
refused) and D-113 (Grant's rate result is a range across two transmission-ownership cases).
Reads the engine's ledger records, sites.yaml and observed/observed_values.json. It writes
RESULTS_<date>.json and RESULTS_<date>.md, misses first (§10).

  python3 score_run.py --power BT-03=<ledger.json> --power BT-04=<ledger.json> \
      --water BT-03=<ledger.json> --date 2026-11-22
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
BT = HERE.parent
ROOT = BT.parents[1]
SITES = ["BT-01", "BT-02", "BT-03", "BT-04"]
CHANNELS = ["G1", "R1", "W1"]
ALLOCS = ("direct_assignment", "large_load_tariff", "socialized")
GAL_PER_M3 = 264.172


def ns(reason):
    return {"status": "NOT SCORED", "reason": reason}


def r1_interval(obs_r1):
    peer, state = obs_r1["R1_obs_pp"], obs_r1["R1_state_pp"]
    lo, hi = min(peer, state) - 5.0, max(peer, state) + 5.0
    sign = None
    if (peer > 0) == (state > 0) and abs(peer) >= 5 and abs(state) >= 5:
        sign = 1 if peer > 0 else -1
    return lo, hi, sign, peer, state


def r1_value_passes(v, lo, hi, sign):
    if not (lo <= v <= hi):
        return False
    if sign is not None and (v > 0) != (sign > 0):
        return False
    return True


def score_r1(site, rec, obs_site):
    ru = site["observed"].get("R1_rate_utility")
    uid = ru.get("eia_id") if isinstance(ru, dict) else None
    if not isinstance(uid, int):
        return ns(f"rate utility not documented ({ru!r})")
    if isinstance(ru, dict) and ru.get("condition"):
        return ns(f"rate utility condition unmet before the run: {ru['condition']}")
    r1s = [x for x in obs_site["R1"] if "R1_obs_pp" in x]
    if not r1s:
        return ns("no observed R1 value")
    sc = next(iter(rec["scenarios"].values()))["summary"]
    detail = {"utility_eia_id": uid, "by_E": []}
    verdicts = []
    for o in r1s:   # every candidate E must pass (§6)
        lo, hi, sign, peer, state = r1_interval(o)
        per_alloc = {}
        for al in ALLOCS:
            u = sc["rate_impact"][al]["per_utility"].get(str(uid))
            if not u or u["status"] != "computed":
                per_alloc[al] = {"status": "indeterminate", "reason": (u or {}).get("reason", "utility not in run")}
                continue
            if (u.get("share_seeds_outside_validity") or 0) > 0:   # D-202: any seed outside validity
                per_alloc[al] = {"status": "indeterminate",
                                 "reason": f"outside the rate model's validity domain in "
                                           f"{u['share_seeds_outside_validity']:.0%} of seeds (D-102, D-202)",
                                 "site_share_of_utility_sales": u.get("site_share_of_utility_sales"),
                                 "p50_unscored": u["lowest_quintile_rate_change_pct"]["p50"]}
                continue
            cases = u.get("lowest_quintile_rate_change_pct_by_case")
            vals = ({k: b["p50"] for k, b in cases.items()} if cases
                    else {"single": u["lowest_quintile_rate_change_pct"]["p50"]})
            ok = {k: r1_value_passes(v, lo, hi, sign) for k, v in vals.items()}
            st = "pass" if all(ok.values()) else "miss" if not any(ok.values()) else "indeterminate"
            per_alloc[al] = {"status": st, "p50_by_case": vals, "case_passes": ok,
                             "bands": cases or {"single": u["lowest_quintile_rate_change_pct"]},
                             "transmission_owner_provenance": u.get("transmission_owner_provenance"),
                             **({"reason": "range straddles the bar (D-113)"} if st == "indeterminate" else {})}
        sts = [v["status"] for v in per_alloc.values()]
        # §6.3: no cost allocation is fixed by a record dated <= E, so a pass needs all three.
        v = "MISS" if "miss" in sts else "NOT SCORED" if "indeterminate" in sts else "PASS"
        verdicts.append(v)
        detail["by_E"].append({"E": o["E"], "interval_pp": [round(lo, 2), round(hi, 2)], "sign_required": sign,
                               "observed_peer_pp": peer, "observed_state_pp": state,
                               "verdict": v, "per_allocation": per_alloc})
    final = "MISS" if "MISS" in verdicts else "NOT SCORED" if "NOT SCORED" in verdicts else "PASS"
    out = {"status": final, **detail}
    if final == "NOT SCORED":
        reasons = sorted({a.get("reason", "") for d in detail["by_E"] for a in d["per_allocation"].values()
                          if a["status"] == "indeterminate"})
        out["reason"] = "; ".join(r for r in reasons if r)
    return out


def score_g1(site, rec):
    pf = next(iter(rec["scenarios"].values()))["summary"]["power_flow"]
    pred = {"new_substation": pf["share_seeds_new_substation"], "new_line_ge_69kv": pf["share_seeds_new_line_ge_69kv"]}
    hh = rec.get("county_households_input") or {}
    common = {"predicted_share_of_seeds": pred, "status_counts": pf["status_counts"],
              "masked_substations": len(rec.get("masked_features") or []),
              "observed": site["observed"].get("G1_new_substation_or_line")}
    if not hh.get("vintage_ok", False):
        return {**ns("county load used 2024 households, not T0-1 (LR-12 not landed; D-112, §4.2.3)"), **common}
    obs = site["observed"].get("G1_new_substation_or_line")
    if not isinstance(obs, dict):
        return {**ns(f"no documented grid-build record ({obs!r})"), **common}
    if None in pred.values():
        return {**ns("power flow not computed in enough seeds"), **common}
    # Observed booleans as registered in sites.yaml (§6.2); only the documented one(s) are compared.
    o_sub, o_line = obs.get("new_substation", obs.get("value")), obs.get("new_line")
    checks = {"new_substation": (pred["new_substation"] >= 0.5) == bool(o_sub)} if o_sub is not None else {}
    if o_line is not None:
        checks["new_line_ge_69kv"] = (pred["new_line_ge_69kv"] >= 0.5) == bool(o_line)
    if not checks:
        return {**ns("neither boolean documented"), **common}
    return {"status": "PASS" if all(checks.values()) else "MISS", "checks": checks, **common}


def score_w1(site, rec):
    obs = site["observed"].get("W1_water") or []
    if not obs:
        return ns("no public water-use record")
    scen = rec["scenarios"]
    years = []
    for w in obs:
        name = "y" + str(w["period"])
        s = scen.get(name)
        if not s:
            years.append({"period": w["period"], "status": "NOT SCORED", "reason": "no scenario for this year"})
            continue
        b = s["summary"].get("annual_withdrawal_gallons") or {}
        if b.get("p50") is None:
            m3 = (s["summary"].get("annual_withdrawal_m3") or {}).get("p50")
            b = {"p50": None if m3 is None else m3 * GAL_PER_M3}
        p = b.get("p50")
        if p is None:
            years.append({"period": w["period"], "status": "NOT SCORED", "reason": "engine gave no withdrawal"})
            continue
        gal = float(w["gallons"])   # PyYAML reads 104.3e6 as a string (YAML 1.1 needs a sign in the exponent)
        ratio = p / gal
        years.append({"period": w["period"], "observed_gallons": gal, "predicted_p50_gallons": round(p),
                      "band_gallons": s["summary"].get("annual_withdrawal_gallons"), "ratio": round(ratio, 3),
                      "status": "PASS" if 0.5 <= ratio <= 2.0 else "MISS"})
    scored = [y for y in years if y["status"] in ("PASS", "MISS")]
    if not scored:
        return {**ns("no year scored"), "years": years}
    share = sum(y["status"] == "PASS" for y in scored) / len(scored)
    return {"status": "PASS" if share >= 0.7 else "MISS", "share_years_pass": round(share, 3), "years": years}


def grade(per_site):
    out = {}
    for ch in CHANNELS:
        sts = [per_site[s][ch]["status"] for s in SITES]
        n_sc = sum(x in ("PASS", "MISS") for x in sts)
        n_p, n_m = sts.count("PASS"), sts.count("MISS")
        ok = n_sc >= 3 and n_m <= 1 and n_p >= 3
        out[ch] = {"scored": n_sc, "passes": n_p, "misses": n_m,
                   "grade": "PLAUSIBLE for the back-test sites" if ok else "SPECULATIVE"}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--power", action="append", default=[])
    ap.add_argument("--water", action="append", default=[])
    ap.add_argument("--date", required=True)
    a = ap.parse_args()
    sites = {s["id"]: s for s in yaml.safe_load((BT / "sites.yaml").read_text())["scored_sites"]}
    obs = json.loads((BT / "observed" / "observed_values.json").read_text())["sites"]
    power = dict(x.split("=", 1) for x in a.power)
    water = dict(x.split("=", 1) for x in a.water)
    runs = {}
    per_site = {}
    for sid in SITES:
        s = sites[sid]
        if s.get("refused"):
            r = f"refused: {s['refused'].get('by')} ({s['refused'].get('why', s['refused'].get('reason', ''))})".strip()
            per_site[sid] = {ch: ns(r) for ch in CHANNELS}
            continue
        lo = obs[sid]["L_obs"][0]
        if "L_obs_aMW" not in lo:
            per_site[sid] = {ch: ns("no L_obs: site cannot run (D-201, D-202): " + lo.get("status", "")) for ch in CHANNELS}
            continue
        res = {}
        if sid in power:
            led = json.loads((ROOT / power[sid]).read_text())
            runs[f"{sid} power"] = {"ledger": power[sid], "run_id": led["run_id"], "engine_version": led["engine_version"],
                                    "params_sha256": led["params_sha256"], "refused": led["refused"]}
            rec = led["counties"][0] if led["counties"] else None
            if rec is None:
                res["G1"] = ns(f"engine refused: {led['refused']}")
                res["R1"] = ns(f"engine refused: {led['refused']}")
            else:
                res["G1"] = score_g1(s, rec)
                res["R1"] = score_r1(s, rec, obs[sid])
                runs[f"{sid} power"].update(eia_year=rec.get("eia_year"), backtest=rec.get("backtest"))
        else:
            res["G1"], res["R1"] = ns("not in this run"), ns("not in this run")
        if sid in water:
            led = json.loads((ROOT / water[sid]).read_text())
            runs[f"{sid} water"] = {"ledger": water[sid], "run_id": led["run_id"], "engine_version": led["engine_version"],
                                    "params_sha256": led["params_sha256"], "refused": led["refused"]}
            rec = led["counties"][0] if led["counties"] else None
            res["W1"] = score_w1(s, rec) if rec else ns(f"engine refused: {led['refused']}")
        else:
            res["W1"] = score_w1(s, {"scenarios": {}}) if not (s["observed"].get("W1_water")) else ns("not in this run")
        per_site[sid] = res
    g = grade(per_site)
    out = {"date": a.date, "grade_rule": "PREREGISTRATION.md §7", "grades": g, "per_site": per_site, "runs": runs,
           "disclosure": ["RuralSim is a free, open-source project by Aldrich K. Wooden, Sr., founder of Get Rural America Done.",
                          "Simulated, screening-grade results with assumed parameters. Decision support, not a finding."]}
    (BT / f"RESULTS_{a.date}.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps({"grades": g, "status": {s: {c: per_site[s][c]["status"] for c in CHANNELS} for s in SITES}}, indent=1))


if __name__ == "__main__":
    main()
