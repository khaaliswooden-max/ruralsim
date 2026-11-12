"""Run experiment cards against pilot county twins.

Usage:
    python3 -m tools.harness.run_experiment EXP-0002 --seeds 5
    python3 -m tools.harness.run_experiment --county 54047 --seeds 20   # all cards for a county

Baselines depend only on (county, seed), never on the card, so they are cached to
experiments/baseline_cache/ and shared across cards. Screening runs (seeds < 20) can
never be promoted. Negative and null results are recorded with the same prominence
as wins; pending engines are registered, never silently skipped.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.harness import constraints, engines, households, rqli
from tools.harness.roads import RoadNet

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "experiments" / "ledger"
CACHE = ROOT / "experiments" / "baseline_cache"
CACHE.mkdir(exist_ok=True)

_NETS: dict[str, RoadNet] = {}


def get_net(fips: str) -> RoadNet:
    if fips not in _NETS:
        _NETS[fips] = RoadNet(str(engines.viewer_dir(fips) / "roads.json"))
    return _NETS[fips]


_BASE: dict = {}


def get_baseline(fips: str, seed: int, n: int = 2000):
    """(households, baseline indicators, tags) — cached, card-independent."""
    key = (fips, seed, n)
    if key in _BASE:
        return _BASE[key]
    p = CACHE / f"{fips}_s{seed}_n{n}.pkl"
    if p.exists():
        try:
            with open(p, "rb") as f:
                blob = pickle.load(f)
            _BASE[key] = blob
            return blob
        except Exception:
            pass  # truncated by a portal drop; recompute
    hh = households.make_households(fips, n=n, seed=seed)
    vals, tags = engines.baseline_indicators(fips, get_net(fips), hh)
    blob = (hh, vals, tags)
    _BASE[key] = blob
    try:
        with open(p, "wb") as f:
            pickle.dump(blob, f)
    except Exception:
        pass  # cache is a convenience, not a result
    return blob


def load_card(card_id: str) -> dict:
    cards = yaml.safe_load(open(ROOT / "experiments" / "seed_experiments.yaml"))
    for c in cards:
        if c["id"] == card_id:
            return c
    raise KeyError(card_id)


def score_table(vals: pd.DataFrame) -> np.ndarray:
    return np.array([rqli.rqli(row.to_dict())[0] for _, row in vals.iterrows()])


def run_one_seed(card: dict, fips: str, seed: int) -> dict:
    card_num = int(card["id"].split("-")[1])
    rng = np.random.default_rng((int(fips), seed, card_num))
    hh, base_vals, tags = get_baseline(fips, seed)
    base_scores = score_table(base_vals)
    params = card["intervention"]["parameters"]
    cid = card["id"]
    int_vals = base_vals.copy()
    extra = {}

    if cid == "EXP-0001":
        r = engines.eng_exp0001_ems(fips, get_net(fips), hh, base_vals, params, rng)
        ratio = r["p90_intervention_min"] / max(r["p90_baseline_min"], 1e-9)
        int_vals["ems_response_minutes_p90"] = base_vals["ems_response_minutes_p90"] * ratio
        primary = {"metric": "ems_response_minutes_p90", **r}
        tags["ems_response_minutes_p90"] = "derived approximation (aggregate p90 ratio applied per household)"
    elif cid == "EXP-0002":
        int_vals = engines.apply_exp0002_telehealth(base_vals, params, rng)
        pb = float(np.nanmean(base_vals["minutes_to_primary_care"]))
        pi = float(np.nanmean(int_vals["minutes_to_primary_care"]))
        primary = {"metric": "minutes_to_primary_care", "baseline_mean": pb,
                   "intervention_mean": pi,
                   "change_pct": 100 * (pi - pb) / pb if pb else None,
                   "unreachable_share_graph_disconnected": float(
                       np.mean(~np.isfinite(base_vals["minutes_to_primary_care"]))),
                   "excluded_share_by_quintile": (
                       int_vals.assign(q=hh["income_quintile"])
                       .groupby("q")["excluded_by_bandwidth"].mean().round(3).to_dict())}
    elif cid == "EXP-0003":
        r = engines.eng_exp0003_battery(fips, hh, params, rng)
        primary = {"metric": "outage_hours_per_year (hospital feeder)", **r,
                   "note": "feeder-level metric; household RQLI outage channel unchanged (battery serves the hospital)"}
    elif cid == "EXP-0004":
        r = engines.eng_exp0004_fixed_wireless(fips, hh, params, rng)
        primary = {"metric": "share of unserved households at 100/20 Mbps", **r}
    elif cid == "EXP-0005":
        r = engines.eng_exp0005_robot(fips, params, rng)
        primary = {"metric": "mission_completion_rate (percent)", **r}
    elif cid == "EXP-0006":
        r = engines.apply_exp0006_drone(fips, hh, params, rng)
        t_hosp = base_vals["minutes_to_emergency_care"].to_numpy()
        primary = {"metric": "share_of_households_reachable_within_30_min",
                   "road_baseline": float(np.mean(t_hosp <= 30.0)),
                   "drone_intervention": r["share_reachable_30min"],
                   "share_grounded_today": r["share_grounded_today"]}
    elif cid == "EXP-0007":
        r = engines.eng_exp0007_datacenter(fips, hh, params, rng)
        primary = {"metric": "change_in_utility_rates_and_local_taxes (lowest quintile)", **r}
        extra["lowest_quintile_rate_change_pct"] = r["lowest_quintile_rate_change_pct_with_onsite"]
    elif cid == "EXP-0008":
        r = engines.eng_exp0008_microgrid(fips, params, rng)
        primary = {"metric": "hours of critical load served during 72-hour outage", **r}
    elif cid == "EXP-0009":
        r = engines.eng_exp0009_edge(fips, params, rng)
        primary = {"metric": "service availability during backhaul outages (percent)", **r}
    elif cid == "EXP-0010":
        r = engines.eng_exp0010_hypothetical(fips, params, rng)
        primary = {"metric": "net present cost versus feeder upgrade (USD)", **r}
    else:
        raise KeyError(cid)

    int_scores = score_table(int_vals)
    cons = constraints.check_all(card, base_vals, int_vals, base_scores, int_scores, extra=extra)
    return {
        "seed": seed, "primary": primary,
        "rqli_baseline": rqli.distribution_report(base_scores),
        "rqli_intervention": rqli.distribution_report(int_scores),
        "constraints": cons,
        "constraints_passed": all(v["passed"] for v in cons.values()),
        "provenance_floor": rqli.weakest_tag(list(tags.values()) + [card["provenance_floor"]]),
        "indicator_provenance": tags,
    }


def effect_of(primary: dict) -> float | None:
    if "change_pct" in primary and primary["change_pct"] is not None:
        return primary["change_pct"]
    if "drone_intervention" in primary:
        return 100 * (primary["drone_intervention"] - primary["road_baseline"])
    if "mission_completion_rate" in primary:
        return primary["mission_completion_rate"]
    if "share_unserved_covered" in primary:
        return 100 * primary["share_unserved_covered"]
    if "share_served" in primary:
        return 100 * primary["share_served"]
    if "availability_during_outages_pct" in primary:
        return primary["availability_during_outages_pct"]
    if "lowest_quintile_rate_change_pct_with_onsite" in primary:
        return primary["lowest_quintile_rate_change_pct_with_onsite"]
    return None


def run_card(card: dict, seeds: int, seed_offset: int = 0) -> dict:
    fips = card["counties"][0]
    rows = [run_one_seed(card, fips, seed_offset + s) for s in range(seeds)]
    eff = np.array([e for e in (effect_of(r["primary"]) for r in rows) if e is not None])
    interval90 = [float(np.percentile(eff, 5)), float(np.percentile(eff, 95))] if len(eff) >= 2 else None
    # worst-off decile across seeds at 90% confidence: lower bound of per-seed deltas >= 0
    deltas = np.array([r["rqli_intervention"]["worst_off_decile_mean"]
                       - r["rqli_baseline"]["worst_off_decile_mean"] for r in rows])
    wod_ok = bool(np.percentile(deltas, 5) >= -1e-9) if len(deltas) >= 2 else bool(deltas[0] >= 0)
    for r in rows:
        if not wod_ok:
            r["constraints"]["worst_off_decile_must_gain"] = {
                "passed": False, "note": "90% lower bound across seeds falls below baseline"}
            r["constraints_passed"] = False
    return {
        "card_id": card["id"], "title": card["title"],
        "run_date": dt.datetime.now().isoformat(timespec="seconds"),
        "mode": "screening" if seeds < 20 else "promotion-eligible",
        "seeds": seeds, "fidelity_tier": card["fidelity_tier"],
        "provenance_floor": card["provenance_floor"],
        "seed_results": rows,
        "effect_summary": {
            "effect_sizes": [float(x) for x in eff],
            "interval_90": interval90,
            "worst_off_decile_delta_p05": float(np.percentile(deltas, 5)) if len(deltas) else None,
        },
        "constraints_passed_all_seeds": all(r["constraints_passed"] for r in rows),
        "promoted": False,
        "promotion_note": "screening run (seeds<20): cannot be promoted per promotion_rule"
                          if seeds < 20 else
                          "promotion additionally requires full-physics confirmation; engines here are reduced-order",
        "guardrails": {
            "synthetic_population": True, "no_address_level_records": True,
            "political_variables_excluded": True, "rqli_reported_as_distribution": True,
            "negative_results_recorded": True,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("card", nargs="?", help="EXP-XXXX")
    ap.add_argument("--county", help="run all cards for this fips5")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--seed-offset", type=int, default=0)
    args = ap.parse_args()

    cards = yaml.safe_load(open(ROOT / "experiments" / "seed_experiments.yaml"))
    if args.county:
        todo = [c for c in cards if c["counties"][0] == args.county]
    elif args.card:
        todo = [load_card(args.card)]
    else:
        ap.error("give a card id or --county")

    for card in todo:
        out = run_card(card, args.seeds, args.seed_offset)
        out["status"] = "ran"
        dest = LEDGER / card["id"]
        dest.mkdir(parents=True, exist_ok=True)
        rid = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        path = dest / f"{rid}_{args.seeds}seeds.json"
        path.write_text(json.dumps(out, indent=1))
        print(f"{card['id']}: {path.relative_to(ROOT)}  mode={out['mode']}  "
              f"constraints_all={out['constraints_passed_all_seeds']}  "
              f"effect_interval90={out['effect_summary']['interval_90']}", flush=True)


if __name__ == "__main__":
    main()
