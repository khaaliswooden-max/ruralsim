"""Score back-test v2 runs against the v2 pre-registration. Committed before any v2 run (D-210).

Applies v2 PREREGISTRATION.md §4.2 (two mask bounds), §5 and §6 (bars), §7 (grading) and the run plan
in §13 (D-210). Reads the engine's ledger records from the GitHub runner (D-209), v2/sites.yaml and
v2/observed/observed_values.json. Writes v2/RESULTS_<date>.json and .md, misses first.

  python3 score_run_v2.py --date 2026-11-24 \
      --power V2-01@2000=<ledger.json> --power V2-01@0=<ledger.json> ... \
      --water V2-01=<ledger.json> --water V2-02=<ledger.json> \
      [--context V2-01@2000=<run_context.txt> ...]

A run is admissible only if (D-210): its data host is https://data.ruralsim.io (D-116); it ran 20 seeds;
it is the declared v2 back-test of that site at the declared mask radius; it was not refused; and its
engine directory is identical to the frozen engine (FROZEN_ENGINE). An inadmissible run scores nothing.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
V2 = HERE.parent
ROOT = V2.parents[2]
SITES = ["V2-01", "V2-02", "V2-03"]
CHANNELS = ["G1", "R1", "W1"]
ALLOCS = ("direct_assignment", "large_load_tariff", "socialized")
BOUNDS = {2000.0: "lower", 0.0: "upper"}            # §4.2: 2000 m = lower-bound network, 0 m = upper-bound network
DATA_HOST = "https://data.ruralsim.io"               # D-066, D-116
FROZEN_ENGINE = "56b306b1844484eef2619c910ac081879a200707"   # last change to tools/engines/ai_infra on main e8cf12f (§5.1, D-210)
SEEDS = 20
FLOOR = 0.05                                          # §5.5(a)
DISCLOSURE = ["RuralSim is a free, open-source project by Aldrich K. Wooden, Sr., founder of Get Rural America Done.",
              "Simulated, screening-grade results with assumed parameters. Decision support, not a finding."]


def ns(reason, **kw):
    return {"status": "NOT SCORED", "reason": reason, **kw}


def engine_identical(commit: str) -> tuple[bool, str]:
    c = commit.removesuffix("-dirty")
    if commit.endswith("-dirty"):
        return False, f"engine tree dirty at {c}"
    r = subprocess.run(["git", "-C", str(ROOT), "diff", "--quiet", FROZEN_ENGINE, c, "--", "tools/engines/ai_infra"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        return True, f"tools/engines/ai_infra at {c[:12]} identical to frozen {FROZEN_ENGINE[:12]}"
    return False, (f"tools/engines/ai_infra at {c[:12]} differs from frozen {FROZEN_ENGINE[:12]}" if r.returncode == 1
                   else f"cannot compare engine at {c[:12]}: {r.stderr.strip()}")


def admit(led: dict, sid: str, radius: float | None) -> tuple[dict | None, dict]:
    """Return (county record or None, run summary). None means the run scores nothing."""
    info = {"run_id": led.get("run_id"), "card_id": led.get("card_id"), "engine_version": led.get("engine_version"),
            "params_sha256": led.get("params_sha256"), "data_host": led.get("data_host"), "seeds": led.get("seeds"),
            "refused": led.get("refused"), "eia_tables": led.get("eia_tables"),
            "data_downloads": led.get("data_downloads")}
    why = []
    if led.get("data_host") != DATA_HOST:
        why.append(f"data host {led.get('data_host')!r} is not {DATA_HOST}")
    if led.get("seeds") != SEEDS:
        why.append(f"{led.get('seeds')} seeds, not {SEEDS}")
    ok, msg = engine_identical(str(led.get("engine_version")))
    info["engine_check"] = msg
    if not ok:
        why.append(msg)
    recs = led.get("counties") or []
    rec = recs[0] if len(recs) == 1 else None
    if rec is None:
        why.append(f"engine refused or no single county record: {led.get('refused')}")
    else:
        bt = rec.get("backtest") or {}
        info["backtest"] = bt
        info["eia_year"] = rec.get("eia_year")
        if bt.get("site_id") != sid or bt.get("version") != "v2":
            why.append(f"record is back-test {bt.get('site_id')}/{bt.get('version')}, not {sid}/v2")
        if radius is not None and float(bt.get("mask_radius_m", -1)) != radius:
            why.append(f"mask radius {bt.get('mask_radius_m')} m, not the declared {radius:g} m")
    info["admissible"] = not why
    if why:
        info["inadmissible_because"] = why
        return None, info
    return rec, info


# ---------- G1 (§6.1) ----------

def g1_bound(rec, scen):
    s = (rec["scenarios"].get(scen) or {}).get("summary")
    if not s:
        return {"verdict": "indeterminate", "reason": f"no scenario {scen}"}
    pf = s["power_flow"]
    hh = rec.get("county_households_input") or {}
    out = {"share_seeds_new_substation": pf.get("share_seeds_new_substation"),
           "share_seeds_new_line_ge_69kv": pf.get("share_seeds_new_line_ge_69kv"),
           "status_counts": pf.get("status_counts"), "masked_features": len(rec.get("masked_features") or [])}
    if not hh.get("vintage_ok", False):
        return {**out, "verdict": "indeterminate", "reason": "county load not of T0-1 vintage (§4.1)"}
    # §6.1 "yes when at least 50% of seeds include it", counted over all 20 seeds (D-210): a seed whose power
    # flow is not computed counts for neither answer, so the call is made only if it holds whatever those seeds did.
    p = pf.get("share_seeds_new_substation") or 0.0
    comp = (pf.get("status_counts") or {}).get("computed", 0)
    n_sub = round(p * comp)
    out.update(seeds_computed=comp, seeds_with_substation=n_sub)
    if n_sub >= SEEDS / 2:
        return {**out, "predicted_new_substation": True}
    if n_sub + (SEEDS - comp) < SEEDS / 2:
        return {**out, "predicted_new_substation": False}
    return {**out, "verdict": "indeterminate",
            "reason": f"power flow computed in {comp} of {SEEDS} seeds; the call depends on the rest (§5.2)"}


def combine_bounds(lo, up):
    """§4.2/§6.1: scored only when both bounds give the same verdict."""
    if "indeterminate" in (lo, up):
        return "NOT SCORED", "a bound is indeterminate"
    if lo != up:
        return "NOT SCORED", "mask bounds disagree: the pre-T0 grid decides and cannot be observed (§4.2)"
    return lo, None


def worst(vs):
    """Every candidate E must pass (§6): any MISS is a MISS, else any NOT SCORED is NOT SCORED."""
    return "MISS" if "MISS" in vs else "NOT SCORED" if "NOT SCORED" in vs else "PASS"


def score_g1(site, recs):
    obs = site["observed"]["G1_grid_build"]
    o_sub = obs.get("new_substation")
    if o_sub is None:
        return ns("no documented substation record")
    if any(recs.get(b) is None for b in ("lower", "upper")):
        return ns("a mask-bound run is missing or inadmissible", bounds={b: recs.get(b) is not None for b in ("lower", "upper")})
    by_E = []
    for E in site["E"]:
        sc = f"g1_E{E}"
        bd = {b: g1_bound(recs[b], sc) for b in ("lower", "upper")}
        v = {}
        for b, x in bd.items():
            v[b] = x["verdict"] if x.get("verdict") == "indeterminate" else ("PASS" if x["predicted_new_substation"] == bool(o_sub) else "MISS")
        final, why = combine_bounds(v["lower"], v["upper"])
        by_E.append({"E": E, "scenario": sc, "observed_new_substation": bool(o_sub), "bounds": bd,
                     "bound_verdicts": v, "verdict": final, **({"reason": why} if why else {})})
    st = worst([x["verdict"] for x in by_E])
    out = {"status": st, "observed": obs, "line_ge_69kv": "not compared: no site documents one (§6.1)", "by_E": by_E}
    if st == "NOT SCORED":
        out["reason"] = "; ".join(sorted({x.get("reason", "") for x in by_E if x["verdict"] == "NOT SCORED"}))
    return out


# ---------- R1 (§5.5, §6.2) ----------

def r1_interval(o):
    peer, state = o["R1_obs_pp"], o["R1_state_pp"]
    lo, hi = min(peer, state) - 5.0, max(peer, state) + 5.0
    sign = 1 if peer > 0 else -1
    if not ((peer > 0) == (state > 0) and abs(peer) >= 5 and abs(state) >= 5):
        sign = None
    return lo, hi, sign, peer, state


def passes(v, lo, hi, sign):
    return lo <= v <= hi and (sign is None or (v > 0) == (sign > 0))


def r1_alloc(u, use_large_load):
    """One allocation on one bound -> status and values. use_large_load: §5.5(b)."""
    if not u or u.get("status") != "computed":
        return {"status": "indeterminate", "reason": (u or {}).get("reason", "utility not in run")}
    if use_large_load:
        ll = u.get("large_load")
        if not ll or not ll.get("valid_for_site_share"):
            return {"status": "indeterminate", "reason": "no large_load output valid for the site's share (§5.5(b))",
                    "share_seeds_outside_validity": u.get("share_seeds_outside_validity")}
        cases = ll.get("lowest_quintile_rate_change_pct_by_case")
        bands = cases or {"single": ll["lowest_quintile_rate_change_pct"]}
        return {"status": "values", "source": "large_load", "bands": bands,
                "share_seeds_above_limit": ll.get("share_seeds_above_limit")}
    if (u.get("share_seeds_outside_validity") or 0) > 0:
        ll = u.get("large_load")
        if ll and ll.get("valid_for_site_share"):
            return r1_alloc(u, True)
        return {"status": "indeterminate", "reason": "outside the rate model's validity domain (D-102, D-202)"}
    cases = u.get("lowest_quintile_rate_change_pct_by_case")
    return {"status": "values", "source": "main model",
            "bands": cases or {"single": u["lowest_quintile_rate_change_pct"]}}


def r1_eval(rec, scen, uid, o, use_large_load):
    s = (rec["scenarios"].get(scen) or {}).get("summary")
    if not s:
        return "indeterminate", {"reason": f"no scenario {scen}"}
    lo, hi, sign, peer, state = r1_interval(o)
    per = {}
    for al in ALLOCS:
        a = r1_alloc(s["rate_impact"][al]["per_utility"].get(str(uid)), use_large_load)
        if a["status"] == "values":
            p50 = {k: b["p50"] for k, b in a["bands"].items()}
            ok = {k: passes(v, lo, hi, sign) for k, v in p50.items()}
            st = "pass" if all(ok.values()) else "miss" if not any(ok.values()) else "indeterminate"
            # §5.1: a pass whose observed values (peer, state) both lie outside the p10-p90 band
            imiss = st == "pass" and all(not (b["p10"] <= peer <= b["p90"]) and not (b["p10"] <= state <= b["p90"])
                                         for b in a["bands"].values())
            a = {**a, "p50_by_case": p50, "case_passes": ok, "status": st,
                 **({"interval_miss": True} if imiss else {}),
                 **({"reason": "range straddles the bar (D-113)"} if st == "indeterminate" else {})}
        per[al] = a
    sts = [x["status"] for x in per.values()]
    v = "MISS" if "miss" in sts else "indeterminate" if "indeterminate" in sts else "PASS"
    return v, {"interval_pp": [round(lo, 2), round(hi, 2)], "sign_required": sign, "per_allocation": per}


def score_r1(site, recs, obs_site):
    uid = site["observed"]["R1_rate_utility"]["eia_id"]
    r1s = [x for x in obs_site["R1"] if "R1_obs_pp" in x]
    if not r1s:
        return ns("no observed R1 value")
    below = [x for x in r1s if x.get("site_share_of_T0m1_sales", 0) < FLOOR]
    by_E = []
    for o in r1s:
        E, sc = o["E"], f"r1_E{o['E']}"
        floor_ok = o.get("site_share_of_T0m1_sales", 0) >= FLOOR
        bd, v = {}, {}
        for b in ("lower", "upper"):
            if recs.get(b) is None:
                v[b], bd[b] = "indeterminate", {"reason": "run missing or inadmissible"}
                continue
            v[b], bd[b] = r1_eval(recs[b], sc, uid, o, use_large_load=floor_ok)
        final, why = combine_bounds(v["lower"], v["upper"])   # D-210: R1 also needs both bounds to agree
        entry = {"E": E, "scenario": sc, "utility_eia_id": uid, "observed_peer_pp": o["R1_obs_pp"],
                 "observed_state_pp": o["R1_state_pp"], "peer_n": o.get("peer_n"),
                 "site_share_of_T0m1_sales": o.get("site_share_of_T0m1_sales"), "bounds": bd, "bound_verdicts": v}
        if not floor_ok:
            entry.update(verdict="NOT SCORED", reason="below the attribution floor, not scored (§5.5(a))",
                         unscored_comparison=final)
        else:
            entry.update(verdict=final, **({"reason": why} if why else {}))
        by_E.append(entry)
    if below and len(below) == len(r1s):
        return {"status": "NOT SCORED", "reason": "below the attribution floor, not scored (§5.5(a)); "
                "computed and published as §12 requires", "by_E": by_E}
    st = worst([x["verdict"] for x in by_E])
    out = {"status": st, "by_E": by_E}
    if st == "NOT SCORED":
        out["reason"] = "; ".join(sorted({x.get("reason", "") for x in by_E if x["verdict"] == "NOT SCORED"}))
    return out


# ---------- W1 (§6.3) ----------

def score_w1(site, rec):
    obs = site["observed"].get("W1_water") or []
    if not obs:
        return ns("no site-scope water record")
    if rec is None:
        return ns("water run missing or inadmissible")
    years = []
    for w in obs:
        y, m3 = int(w["year"]), float(w["m3"])
        s = (rec["scenarios"].get(f"y{y}") or {}).get("summary") or {}
        b = s.get("annual_withdrawal_m3") or {}
        p = b.get("p50")
        if p is None:
            years.append({"year": y, "observed_m3": m3, "status": "NOT SCORED", "reason": "engine gave no withdrawal"})
            continue
        r = p / m3
        st = "PASS" if 0.5 <= r <= 2.0 else "MISS"
        years.append({"year": y, "observed_m3": m3, "predicted_p50_m3": round(p), "band_m3": b, "ratio": round(r, 3),
                      "status": st, **({"interval_miss": True} if st == "PASS" and not (b["p10"] <= m3 <= b["p90"]) else {}),
                      "cooling_type": s.get("cooling_type"), "wue_l_per_it_kwh": s.get("wue_l_per_it_kwh")})
    scored = [y for y in years if y["status"] in ("PASS", "MISS")]
    if not scored:
        return {**ns("no year scored"), "years": years}
    share = sum(y["status"] == "PASS" for y in scored) / len(scored)
    return {"status": "PASS" if share >= 0.7 else "MISS", "share_years_pass": round(share, 3),
            "years_scored": len(scored), "years": years}


def grade(per_site):
    out = {}
    for ch in CHANNELS:
        sts = [per_site[s][ch]["status"] for s in SITES]
        n_sc = sum(x in ("PASS", "MISS") for x in sts)
        n_p, n_m = sts.count("PASS"), sts.count("MISS")
        ok = n_sc >= 3 and n_p >= 3 and n_m <= 1
        out[ch] = {"scored": n_sc, "passes": n_p, "misses": n_m,
                   "grade": "PLAUSIBLE for the v2 back-test sites" if ok else "SPECULATIVE"}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--power", action="append", default=[], help="SITE@RADIUS=ledger.json")
    ap.add_argument("--water", action="append", default=[], help="SITE=ledger.json")
    ap.add_argument("--context", action="append", default=[], help="KEY=run_context.txt")
    ap.add_argument("--actions-run", action="append", default=[], help="KEY=GitHub Actions run URL")
    ap.add_argument("--date", required=True)
    a = ap.parse_args()
    sites = {s["id"]: s for s in yaml.safe_load((V2 / "sites.yaml").read_text())["scored_sites"]}
    obs = json.loads((V2 / "observed" / "observed_values.json").read_text())["sites"]
    ctx = dict(x.split("=", 1) for x in a.context)
    urls = dict(x.split("=", 1) for x in a.actions_run)
    runs, power, water = {}, {}, {}
    for x in a.power:
        key, path = x.split("=", 1)
        sid, rad = key.split("@")
        rec, info = admit(json.loads(Path(path).read_text()), sid, float(rad))
        info.update(ledger=Path(path).name, bound=BOUNDS[float(rad)], run_context=_read(ctx.get(key)),
                    actions_run=urls.get(key))
        runs[f"{sid} power {BOUNDS[float(rad)]} bound ({float(rad):g} m)"] = info
        power.setdefault(sid, {})[BOUNDS[float(rad)]] = rec
    for x in a.water:
        sid, path = x.split("=", 1)
        rec, info = admit(json.loads(Path(path).read_text()), sid, None)
        info.update(ledger=Path(path).name, run_context=_read(ctx.get(sid)), actions_run=urls.get(sid))
        runs[f"{sid} water"] = info
        water[sid] = rec
    per_site = {}
    for sid in SITES:
        s = sites[sid]
        per_site[sid] = {"G1": score_g1(s, power.get(sid, {})),
                         "R1": score_r1(s, power.get(sid, {}), obs[sid]),
                         "W1": score_w1(s, water.get(sid))}
    g = grade(per_site)
    out = {"date": a.date, "preregistration": "validation/backtest/v2/PREREGISTRATION.md (D-207; run plan D-210)",
           "frozen_engine": FROZEN_ENGINE, "data_host_required": DATA_HOST, "grade_rule": "§7", "grades": g,
           "per_site": per_site, "runs": runs, "disclosure": DISCLOSURE}
    (V2 / f"RESULTS_{a.date}.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps({"grades": g, "status": {s: {c: per_site[s][c]["status"] for c in CHANNELS} for s in SITES},
                      "admissible": {k: v["admissible"] for k, v in runs.items()}}, indent=1))


def _read(p):
    return Path(p).read_text().strip().splitlines() if p and Path(p).exists() else None


if __name__ == "__main__":
    main()
