"""Back-test v2: compute the pre-registered observed quantities (PREREGISTRATION.md §6) from
EIA-861 and the operator disclosures recorded in sites.yaml. Never reads engine output.

Differences from v1's derive_observed.py, each a v2 rule (D-207):
  * every utility quantity is filtered to the site's state (v1's sites were single-state
    utilities; PacifiCorp is not);
  * load from EIA is delivered energy, Parts A + B (bundled + delivery-only), so a
    retail-choice state still shows the load (fix 3);
  * load is taken in the year of the comparison it feeds: G1 at E+2, R1 at E+5, W1 at year Y
    (v1 used E+1..E+2 for every channel); an EIA load at year Y is mean(Y-1, Y) minus the
    T0-3..T0-1 mean, an operator-disclosed load is that year's figure;
  * an EIA load is used only if it is detectable: increment >= 3 x the standard deviation of
    the utility's year-on-year changes over T0-7..T0-1; otherwise the operator disclosure
    for that year is the only allowed load, and without one the comparison cannot run.

  python3 derive_observed_v2.py --zips DIR
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
V2 = HERE.parent
sys.path.insert(0, str(V2.parent / "tools"))
import eia861_series as e  # noqa: E402

_C = {}


def year(zips, y):
    if y not in _C:
        _C[y] = e.read_year(os.path.join(zips, f"f861_{y}.zip"), y)
    return _C[y]


def rows(zips, uid, st, y, parts):
    d = year(zips, y)
    return d[(d.utility_id == uid) & (d.state == st) & d.part.str.upper().str[:1].isin(list(parts))]


def delivered_mwh(zips, uid, st, y):
    r = rows(zips, uid, st, y, "AB")
    v = r.tot_mwh.sum(min_count=1)
    return None if v != v else float(v)


def price(r):
    r = r[r.res_mwh.notna() & (r.res_mwh > 0) & r.res_rev_k.notna()]
    return None if r.empty else 100 * r.res_rev_k.sum() / r.res_mwh.sum()


def r1(zips, uid, st, ya, yb):
    a = year(zips, ya); b = year(zips, yb)
    a, b = a[(a.state == st) & a.part.str.upper().str.startswith("A")], b[(b.state == st) & b.part.str.upper().str.startswith("A")]
    ua, ub = a[a.utility_id == uid], b[b.utility_id == uid]
    if ua.empty or ub.empty:
        return None
    own = ua.ownership.iloc[0]

    def has(d):
        return set(d[(d.ownership == own) & (d.utility_id != uid) & d.res_mwh.notna() & (d.res_mwh > 0)
                     & d.res_rev_k.notna()].utility_id)
    panel = has(a) & has(b)
    pu_a, pu_b = price(ua), price(ub)
    pp_a, pp_b = price(a[a.utility_id.isin(panel)]), price(b[b.utility_id.isin(panel)])
    ps_a, ps_b = price(a), price(b)
    if None in (pu_a, pu_b, pp_a, pp_b):
        return None
    du = pu_b / pu_a - 1
    return {"years": [ya, yb], "state": st, "peer_class": own, "peer_n": len(panel),
            "utility_cents_kwh": [round(pu_a, 3), round(pu_b, 3)], "peer_cents_kwh": [round(pp_a, 3), round(pp_b, 3)],
            "state_cents_kwh": [round(ps_a, 3), round(ps_b, 3)],
            "R1_obs_pp": round(100 * (du - (pp_b / pp_a - 1)), 2), "R1_state_pp": round(100 * (du - (ps_b / ps_a - 1)), 2)}


def eia_load(zips, uid, st, t0, y):
    """Average MW at year y: mean delivered MWh of (y-1, y) minus mean of T0-3..T0-1; with the
    detectability test against year-on-year noise over T0-7..T0-1."""
    pre = [delivered_mwh(zips, uid, st, k) for k in range(t0 - 3, t0)]
    post = [delivered_mwh(zips, uid, st, k) for k in (y - 1, y)]
    hist = [delivered_mwh(zips, uid, st, k) for k in range(t0 - 7, t0)]
    if None in pre + post or None in hist:
        return {"status": "no EIA data for a needed year"}
    inc = sum(post) / 2 - sum(pre) / 3
    sd = statistics.stdev([b - a for a, b in zip(hist, hist[1:])])
    ratio = inc / sd if sd else float("inf")
    return {"year": y, "pre_years": [t0 - 3, t0 - 1], "post_years": [y - 1, y], "increment_mwh": round(inc),
            "noise_sd_mwh": round(sd), "detect_ratio": round(ratio, 1), "detectable": ratio >= 3,
            "load_aMW": round(inc / 8760, 1), "share_of_T0m1_sales": round(inc / delivered_mwh(zips, uid, st, t0 - 1), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zips", required=True)
    a = ap.parse_args()
    sites = yaml.safe_load((V2 / "sites.yaml").read_text())["scored_sites"]
    out = {"rules": "v2 PREREGISTRATION.md §5-§6", "sites": {}}
    for s in sites:
        t0, es, st = s["T0"], s["E"], s["state"]
        rec = {"fips5": s["fips5"], "T0": t0, "E": es, "loads": {}, "R1": [], "W1": []}
        lu = s["load"].get("eia_utility")
        disc = {int(k): v for k, v in (s["load"].get("operator_disclosed_mwh") or {}).items()}

        def load_at(y):
            if y in disc:
                return {"year": y, "source": "operator disclosure", "load_aMW": round(disc[y] / 8760, 1),
                        "mwh": disc[y], "ref": s["load"].get("operator_source")}
            if isinstance(lu, int):
                x = eia_load(a.zips, lu, st, t0, y)
                x["source"] = f"EIA-861 Parts A+B, utility {lu}"
                if x.get("detectable") is False:
                    x["status"] = "NOT DETECTABLE: comparison cannot run"
                return x
            return {"year": y, "status": "no load source"}
        for E in es:   # G1: load at E+2, the end of the build window (§6.2)
            rec["loads"][f"G1_E{E}"] = load_at(E + 2)
        ru = s["observed"].get("R1_rate_utility")
        rid = ru.get("eia_id") if isinstance(ru, dict) else None
        for E in es:
            ld = load_at(E + 5)
            rec["loads"][f"R1_E{E}"] = ld
            if isinstance(rid, int):
                v = r1(a.zips, rid, st, t0 - 1, E + 5)
                if v and isinstance(ld.get("mwh") or ld.get("increment_mwh"), (int, float)):
                    sales = delivered_mwh(a.zips, rid, st, t0 - 1)
                    v["site_share_of_T0m1_sales"] = round((ld.get("mwh") or ld["increment_mwh"]) / sales, 4)
                rec["R1"].append({"E": E, "utility_eia_id": rid, **(v or {"status": "utility or peers missing"})})
            else:
                rec["R1"].append({"E": E, "status": f"NOT SCORED: rate utility {ru!r}"})
        for w in s["observed"].get("W1_water") or []:
            y = int(w["year"])
            rec["W1"].append({"year": y, "observed_gallons": float(w["m3"]) * 264.172, "observed_m3": float(w["m3"]),
                              "load": load_at(y)})
        out["sites"][s["id"]] = rec
    (V2 / "observed").mkdir(exist_ok=True)
    (V2 / "observed" / "observed_values.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
