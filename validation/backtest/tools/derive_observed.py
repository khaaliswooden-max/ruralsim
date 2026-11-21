"""Compute the pre-registered quantities L_obs and R1 from EIA-861.

Rules are PREREGISTRATION.md §6.1 (L_obs, the load input of the conditional run),
§6.3 (R1) and §6.4 (load for each water-observation year); this file implements them
and nothing else. It reads sites.yaml and the EIA-861 annual zips, and writes
observed/observed_values.json. It never reads engine output.

  L_obs_aMW   = (mean retail MWh of the serving utility over E+1..E+2
                 - mean over T0-3..T0-1) / 8760
  R1_obs_pp   = 100 * [ (p_u(E+5) / p_u(T0-1) - 1) - (p_peer(E+5) / p_peer(T0-1) - 1) ]
                p_u    = the rate utility's bundled residential revenue / sales
                p_peer = same quantity pooled over same-state utilities of the same
                         EIA ownership class, the rate utility excluded, restricted to
                         utilities reporting residential sales in BOTH endpoint years
                         (a balanced panel)
  R1_state_pp = as R1_obs_pp with the all-utility state average in place of the
                peers; reported for context, not scored.

Usage: python3 derive_observed.py --zips DIR [--sites ../sites.yaml] [--out ../observed/observed_values.json]
"""
import argparse, json, os, sys
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eia861_series as e  # noqa: E402

_cache = {}


def year(zips, y):
    if y not in _cache:
        df = e.read_year(os.path.join(zips, f"f861_{y}.zip"), y)
        _cache[y] = df[df["part"].str.upper().str.startswith("A")]
    return _cache[y]


def tot_mwh(zips, uid, y):
    d = year(zips, y)
    v = d[d["utility_id"] == uid]["tot_mwh"].sum(min_count=1)
    return None if v != v else float(v)


def res_price(rows):
    rows = rows[rows["res_mwh"].notna() & (rows["res_mwh"] > 0) & rows["res_rev_k"].notna()]
    if rows.empty:
        return None
    return 100 * rows["res_rev_k"].sum() / rows["res_mwh"].sum()  # $k / MWh -> cents/kWh


def r1(zips, uid, y_a, y_b):
    a, b = year(zips, y_a), year(zips, y_b)
    ua, ub = a[a["utility_id"] == uid], b[b["utility_id"] == uid]
    if ua.empty or ub.empty:
        return None
    st, own = ua["state"].iloc[0], ua["ownership"].iloc[0]

    def has_res(d):
        return set(d[(d["state"] == st) & (d["ownership"] == own) & (d["utility_id"] != uid)
                     & d["res_mwh"].notna() & (d["res_mwh"] > 0) & d["res_rev_k"].notna()]["utility_id"])
    panel = has_res(a) & has_res(b)
    pa = res_price(a[(a["state"] == st) & a["utility_id"].isin(panel)])
    pb = res_price(b[(b["state"] == st) & b["utility_id"].isin(panel)])
    sa = res_price(a[a["state"] == st])
    sb = res_price(b[b["state"] == st])
    u_a, u_b = res_price(ua), res_price(ub)
    if None in (u_a, u_b, pa, pb):
        return None
    du = u_b / u_a - 1
    return {
        "years": [y_a, y_b], "utility_cents_kwh": [round(u_a, 3), round(u_b, 3)],
        "peer_cents_kwh": [round(pa, 3), round(pb, 3)], "peer_n": len(panel),
        "peer_class": own, "state": st,
        "state_cents_kwh": [round(sa, 3), round(sb, 3)],
        "R1_obs_pp": round(100 * (du - (pb / pa - 1)), 2),
        "R1_state_pp": round(100 * (du - (sb / sa - 1)), 2),
    }


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--zips", required=True)
    ap.add_argument("--sites", default=os.path.join(here, "..", "sites.yaml"))
    ap.add_argument("--out", default=os.path.join(here, "..", "observed", "observed_values.json"))
    a = ap.parse_args()
    sites = yaml.safe_load(open(a.sites))
    out = {"rules": "PREREGISTRATION.md §6.1, §6.3, §6.4", "source": "EIA Form 861, Part A (bundled) rows", "sites": {}}
    for s in sites["scored_sites"] + sites.get("contrast_sites", []):
        sid, t0, es = s["id"], s.get("T0"), s.get("E") or []
        obs = s.get("observed", {})
        rec = {"fips5": s["fips5"], "T0": t0, "E": es, "L_obs": [], "R1": [], "W1_load": []}
        uid = obs.get("load_utility_eia_id")
        if isinstance(uid, int) and t0:
            pre = [tot_mwh(a.zips, uid, y) for y in range(t0 - 3, t0)]
            for E in es:
                post = [tot_mwh(a.zips, uid, y) for y in (E + 1, E + 2)]
                if None in pre or None in post:
                    rec["L_obs"].append({"E": E, "status": "NOT SCORED: missing EIA year"})
                    continue
                d = (sum(post) / 2 - sum(pre) / 3) / 8760
                rec["L_obs"].append({"E": E, "utility_eia_id": uid, "pre_years": [t0 - 3, t0 - 1],
                                  "post_years": [E + 1, E + 2], "pre_mean_mwh": round(sum(pre) / 3),
                                  "post_mean_mwh": round(sum(post) / 2), "L_obs_aMW": round(d, 1)})
        else:
            rec["L_obs"].append({"status": f"NO LOAD INPUT, site cannot run: load utility {uid!r}"})
        # §6.4: load for each water-observation year (utility increment over the pre-T0 mean)
        if isinstance(uid, int) and t0:
            pre_mean = sum(tot_mwh(a.zips, uid, y) for y in range(t0 - 3, t0)) / 3
            for w in obs.get("W1_water") or []:
                yrs = [2024, 2025] if str(w["period"]).startswith("FY2025") else [int(w["period"])]
                vals = [v for v in (tot_mwh(a.zips, uid, y) for y in yrs if y <= 2024) if v is not None]
                rec["W1_load"].append({"period": w["period"], "years_used": [y for y in yrs if y <= 2024],
                                       "load_aMW": round((sum(vals) / len(vals) - pre_mean) / 8760, 1)})
        ru = obs.get("R1_rate_utility")
        rid = ru.get("eia_id") if isinstance(ru, dict) else None
        if isinstance(rid, int) and t0:
            for E in es:
                if E + 5 > 2024:
                    rec["R1"].append({"E": E, "status": "NOT SCORED: E+5 after latest EIA-861 year (2024)"})
                    continue
                v = r1(a.zips, rid, t0 - 1, E + 5)
                rec["R1"].append({"E": E, "utility_eia_id": rid,
                                  **(v or {"status": "NOT SCORED: utility or peers missing"})})
                if isinstance(ru, dict) and ru.get("condition"):
                    rec["R1"][-1]["condition"] = ru["condition"]
        else:
            rec["R1"].append({"status": f"NOT SCORED: rate utility {ru!r}"})
        out["sites"][sid] = rec
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
