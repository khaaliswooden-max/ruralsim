"""Render v2/RESULTS_<date>.md from v2/RESULTS_<date>.json, misses first (v2 §1). Presentation only:
every verdict comes from score_run_v2.py.

  python3 write_results_md_v2.py --date 2026-11-24
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

V2 = Path(__file__).resolve().parent.parent
SITES = {"V2-01": "Crook OR (Meta)", "V2-02": "Rutherford NC (Meta)", "V2-03": "Morrow OR (AWS)"}
CH = {"G1": "grid build", "R1": "residential rate", "W1": "water withdrawal"}


def f(x, n=2):
    return "–" if x is None else f"{x:,.{n}f}"


def r1_rows(e):
    out = []
    for b, bd in e["bounds"].items():
        for al, a in (bd.get("per_allocation") or {}).items():
            p = a.get("p50_by_case") or {}
            bands = a.get("bands") or {}
            out.append(f"| {e['E']} | {b} | {al} | {a.get('source', '–')} | "
                       + ", ".join(f"{f(v)}" for v in p.values()) + " | "
                       + ", ".join(f"{f(x['p10'])} to {f(x['p90'])}" for x in bands.values()) + " | "
                       + f"{bd['interval_pp'][0]} to {bd['interval_pp'][1]} | {a['status']} |")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    a = ap.parse_args()
    d = json.loads((V2 / f"RESULTS_{a.date}.json").read_text())
    ps, g = d["per_site"], d["grades"]
    L = [f"# Back-test v2 results, {a.date}", "",
         "Rollout step 3 · method `PREREGISTRATION.md` (D-207), run plan D-210, results D-211.",
         f"Engine frozen at `{d['frozen_engine'][:7]}` (run from `1c60a12`, engine directory identical). Eight runs on the "
         "GitHub \"Back-test run\" workflow (D-209), 20 seeds each. Every run record names "
         f"`{d['data_host_required']}` as its data host.", "",
         "**Every result here is screening-grade. Nothing is a finding.** v2 is now frozen (§8).", "",
         "## 1. Grades (§7)", "",
         "| Channel | Sites scored | Passes | Misses | Grade |", "|---|---|---|---|---|"]
    for c in ("W1", "R1", "G1"):
        x = g[c]
        L.append(f"| {c} {CH[c]} | {x['scored']} of 3 | {x['passes']} | {x['misses']} | {x['grade']} |")
    L += ["",
          "**Read G1 with §5 below. Its passes were guaranteed.** The engine adds a new customer substation to every "
          "computed seed (`power_flow.py`, the site connection), so it cannot answer \"no\". All three sites "
          "documented a substation, so all three passed. The registered rule grades this PLAUSIBLE and the grade is "
          "recorded as the rule gives it. It is not evidence that the engine predicts grid builds. Do not cite it as such.", "",
          "## 2. Misses", ""]
    # W1
    for s in ("V2-01", "V2-02"):
        w = ps[s]["W1"]
        if w["status"] != "MISS":
            continue
        L += [f"### W1 · {s} {SITES[s]}: MISS ({int(round(w['share_years_pass'] * w['years_scored']))} of "
              f"{w['years_scored']} years within 0.5–2.0×; the bar is 70%)", "",
              "| Year | Observed m³ | Engine p50 m³ | p10–p90 m³ | Ratio | Verdict |", "|---|---|---|---|---|---|"]
        for y in w["years"]:
            b = y.get("band_m3") or {}
            L.append(f"| {y['year']} | {f(y['observed_m3'], 0)} | {f(y.get('predicted_p50_m3'), 0)} | "
                     f"{f(b.get('p10'), 0)}–{f(b.get('p90'), 0)} | {f(y.get('ratio'), 3)} | {y['status']}"
                     + (" (interval miss)" if y.get("interval_miss") else "") + " |")
        wue = (w["years"][0].get("wue_l_per_it_kwh") or {}).get("p50")
        L += ["", f"Cooling run: `adiabatic_hybrid` (§5.4). Engine water intensity p50 {f(wue, 3)} L per IT kWh.", ""]
    L += ["What the W1 misses show:",
          "- **V2-01 Crook:** the engine is 4–15× low in every year, and the gap grows as the site grows: Meta's "
          "reported withdrawal rose faster than its electricity. The §5.4 mapping to `adiabatic_hybrid` gives "
          "evaporation only above a temperature setpoint. Prineville's withdrawal is far above that. §12 recorded "
          "that this mapping was a judgment.",
          "- **V2-02 Rutherford:** low by about half in 2014–2016, then within the bar for 2017–2020 as reported "
          "water fell while load rose. The same design, mapped the same way, misses at one Meta site by an order of "
          "magnitude and comes close at the other. One cooling design does not describe both sites' "
          "reported water.", ""]
    r = ps["V2-03"]["R1"]
    L += [f"### R1 · V2-03 {SITES['V2-03']}: MISS", "",
          "Every candidate E must pass (§6). E = 2011 passes on both bounds. E = 2013 misses on both bounds: the "
          "socialized allocation gives +2.3 to +3.2 pp, above the bar's ceiling of +1.1 pp. UEC's observed "
          "peer-differenced change to 2018 is −3.9 pp, state-differenced −7.8 pp. The large-load output (§5.5(b)) "
          "applied, with `valid_for_site_share: true`. The site is 1.7× UEC's 2007 sales at E+5, and its load "
          "covers every AWS campus UEC serves (§10.3).", "",
          "| E | Bound | Allocation | Source | p50 pp | p10 to p90 pp | Bar pp | Verdict |", "|---|---|---|---|---|---|---|---|"]
    for e in r["by_E"]:
        L += r1_rows(e)
    L += ["", "Observed: E = 2011 peer +1.98, state −0.01 pp; E = 2013 peer −3.86, state −7.83 pp (peer n = 17 "
          "cooperatives). Residential prices at UEC fell relative to Oregon co-ops while the data-center load "
          "arrived. Under socialized allocation the engine says they rise.", "",
          "## 3. Not scored", "",
          "| Site | Channel | Why |", "|---|---|---|"]
    for s in SITES:
        for c in ("G1", "R1", "W1"):
            x = ps[s][c]
            if x["status"] == "NOT SCORED":
                L.append(f"| {s} | {c} | {x['reason']} |")
    L += ["", "### Below the attribution floor, published as §12 requires", "",
          "These would have been misses. The engine gives about zero, because the site is 0.6–2.4% of its "
          "utility's sales. The observed changes are PacifiCorp's and Duke's system-wide rate paths.", "",
          "| E | Bound | Allocation | Source | p50 pp | p10 to p90 pp | Bar pp | Unscored verdict |",
          "|---|---|---|---|---|---|---|---|"]
    for s in ("V2-01", "V2-02"):
        L.append(f"| **{s}** | | | | | | | |")
        for e in ps[s]["R1"]["by_E"]:
            L += r1_rows(e)
    L += ["", "## 4. Passes", "", "| Site | E | Lower bound (2000 m): seeds with a substation | Upper bound (0 m) | "
          "Observed | Verdict |", "|---|---|---|---|---|---|"]
    for s in SITES:
        for e in ps[s]["G1"]["by_E"]:
            lo, up = e["bounds"]["lower"], e["bounds"]["upper"]
            L.append(f"| {s} | {e['E']} | {lo.get('seeds_with_substation')} of {lo.get('seeds_computed')} "
                     f"({lo['masked_features']} masked) | {up.get('seeds_with_substation')} of {up.get('seeds_computed')} "
                     f"({up['masked_features']} masked) | substation | {e['verdict']} |")
    L += ["", "Lines ≥ 69 kV were not compared (§6.1). The engine's share of seeds with a new ≥ 69 kV line is in the JSON.", "",
          "## 5. What G1's PLAUSIBLE does and does not mean", "",
          "- **The test could not fail in the direction it was run.** `power_flow.run` adds "
          "`{\"type\": \"substation\", \"subtype\": \"new customer substation\"}` to `required_upgrades` for every "
          "computed seed. `share_seeds_new_substation` is 1.0 whenever the power flow computes. Every site had a "
          "documented substation, so every site passes on both bounds.",
          "- **This was knowable before the run and was not caught.** D-208 said v1's G1 pass \"would carry no "
          "information\" because the engine called a substation in 100% of seeds. D-210 mapped G1 to the same field "
          "without checking whether the engine can return \"no\". That is a run-plan error. The grade stands because "
          "§8 freezes the method after the first run.",
          "- **What would make G1 informative (v3):** a G1 output the engine can answer both ways, such as an "
          "expansion versus new-build distinction or a transmission upgrade beyond the customer tap, and held-out "
          "sites where no build was needed.", "",
          "## 6. Runs", "", "| Run | Actions run | Data host | Engine check | Retried / failed downloads |", "|---|---|---|---|---|"]
    for k, v in d["runs"].items():
        dl = v.get("data_downloads") or {}
        L.append(f"| {k} | [{v['actions_run'].rsplit('/', 1)[1]}]({v['actions_run']}) | {v['data_host']} | "
                 f"{'ok' if v['admissible'] else 'FAIL'} | {len(dl.get('retried', []))} / {len(dl.get('failed', []))} |")
    L += ["", "Ledger records: `experiments/ledger/BACKTEST-2-*/`. Logs and run context: `validation/backtest/v2/runs/<run id>/`. "
          "One dispatch (V2-02 power, 0 m, run 45519189125) was cancelled by the workflow's one-pending-run-per-site "
          "rule before it started. It was dispatched again as run 45519482089, unchanged. Run 45518793141 was started by Khaalis; the other seven were started from his GitHub session in the desktop app's browser, at his request.", "",
          "---", "", f"*{d['disclosure'][0]}*", f"*{d['disclosure'][1]}*", ""]
    (V2 / f"RESULTS_{a.date}.md").write_text("\n".join(L))


if __name__ == "__main__":
    main()
