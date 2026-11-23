"""Render RESULTS_<date>.json (from score_run.py) as RESULTS_<date>.md, in the order §10 requires:
misses, NOT SCORED, passes, grades, deviations. No number is typed by hand."""
import json
import sys
from pathlib import Path

BT = Path(__file__).resolve().parents[1]
NAMES = {"BT-01": "Mayes OK", "BT-02": "Jackson AL", "BT-03": "Wasco OR", "BT-04": "Grant WA"}
CH = {"G1": "grid build", "R1": "residential rate", "W1": "water"}


def f(x, d=1):
    return "—" if x is None else (f"{x:,.{d}f}" if isinstance(x, (int, float)) else str(x))


def r1_lines(r):
    out = []
    for e in r.get("by_E", []):
        lo, hi = e["interval_pp"]
        out.append(f"  - E={e['E']}: pass interval {f(lo)} to {f(hi)} pp (observed {f(e['observed_peer_pp'],2)} pp vs "
                   f"peers, {f(e['observed_state_pp'],2)} pp vs state){'' if e['sign_required'] is None else '; sign required'}.")
        for al, a in e["per_allocation"].items():
            if "p50_by_case" in a:
                cases = ", ".join(f"{k} {f(v,2)}%" for k, v in a["p50_by_case"].items())
                out.append(f"    - {al}: {a['status']} (p50 {cases})")
            else:
                extra = f"; p50 {f(a['p50_unscored'],2)}% not scored" if "p50_unscored" in a else ""
                out.append(f"    - {al}: {a['status']} ({a.get('reason','')}{extra})")
    return out


def w1_lines(w):
    out = []
    for y in w.get("years", []):
        if "ratio" in y:
            out.append(f"  - {y['period']}: predicted p50 {f(y['predicted_p50_gallons']/1e6)} Mgal vs observed "
                       f"{f(y['observed_gallons']/1e6)} Mgal, ratio {f(y['ratio'],2)} → {y['status']}")
        else:
            out.append(f"  - {y['period']}: {y['status']} ({y.get('reason','')})")
    return out


def g1_lines(g):
    p = g.get("predicted_share_of_seeds") or {}
    if not p:
        return []
    return [f"  - engine, share of seeds: new substation {f(p.get('new_substation'),2)}, new line ≥69 kV "
            f"{f(p.get('new_line_ge_69kv'),2)}; substations masked {g.get('masked_substations')}; "
            f"power-flow status {g.get('status_counts')}. Recorded, not scored."]


def main(date):
    d = json.loads((BT / f"RESULTS_{date}.json").read_text())
    ps = d["per_site"]
    rows = [(s, c, ps[s][c]) for s in ps for c in ("G1", "R1", "W1")]
    L = [f"# Back-test run 1 results — {date}", "",
         "Rollout step 3 · scored by `PREREGISTRATION.md` (D-200 to D-205) and D-113 · produced by `tools/score_run.py` "
         "from the ledger records listed at the end.", "",
         "**Grade: every channel stays SPECULATIVE.** No result here is a finding, validated, or decision-grade.", ""]
    for title, key in (("1. Misses", "MISS"), ("2. Not scored", "NOT SCORED"), ("3. Passes", "PASS")):
        L += [f"## {title}", ""]
        hit = [(s, c, r) for s, c, r in rows if r["status"] == key]
        if not hit:
            L += ["None.", ""]
            continue
        for s, c, r in hit:
            L.append(f"- **{s} {NAMES[s]} · {c} {CH[c]}**: {key}" + (f" — {r['reason']}" if r.get("reason") else ""))
            if c == "R1":
                L += r1_lines(r)
            if c == "W1":
                L += w1_lines(r)
            if c == "G1":
                L += g1_lines(r)
        L.append("")
    L += ["## 4. Grades (§7)", "", "| Channel | Scored | Passes | Misses | Grade |", "|---|---|---|---|---|"]
    for c, g in d["grades"].items():
        L.append(f"| {c} {CH[c]} | {g['scored']} of 4 | {g['passes']} | {g['misses']} | {g['grade']} |")
    L += ["", "A channel needs at least 3 of 4 sites scored, at least 3 passes and at most 1 miss.", "",
          "## 5. Contrast site", "", "BT-C1 Licking OH cannot run (D-202): no load input under the Part A rule.", "",
          "## 6. Runs", ""]
    for k, r in d["runs"].items():
        L.append(f"- {k}: `{r['ledger']}` · run `{r['run_id']}` · engine `{r['engine_version']}` · params sha256 "
                 f"`{r['params_sha256'][:12]}…` · EIA year {r.get('eia_year', '—')}")
    L += ["", "---", ""] + [f"*{x}*" for x in d["disclosure"]]
    (BT / f"RESULTS_{date}.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main(sys.argv[1])
