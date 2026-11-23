"""Rate-impact module: what happens to residential rates for the lowest-income households?

No retail service-territory polygons exist, so the serving utility at a point is unknown.
The module runs every utility EIA-861 lists for the county, as if it served the site, and
reports each. Utility revenue, sales, customers and ownership are observed (EIA-861 of the run's year: 2024, or T0-1 in a back-test);
costs, cost recovery and cost allocation are assumed and drawn per seed.

Rate change = net annual cost landing on the utility's customers, times the residential
share of its energy sales, divided by its residential revenue. Under a single residential
tariff the lowest quintile sees the same percentage change.

Short-form utilities (EIA-861S, LR-10) report totals only. For them the rate base, average
rate and kWh per customer are all-sector figures, used as stand-ins for residential ones and
labelled `rate_basis: all_sectors_stand_in` wherever they appear (D-102).

The income effect divides the lowest-quintile bill change by ACS 2020-2024 mean income of the
lowest quintile (B19081, LR-11), drawn per seed inside its margin of error (D-102).
"""
from __future__ import annotations

import math
import re

import numpy as np
from scipy.stats import norm

from .power_flow import cost_band, u

ALLOCATIONS = ("direct_assignment", "large_load_tariff", "socialized")

INCOME_MISSING = "indeterminate: ACS has no lowest-quintile mean income for this county"

def _ownership_from_name(name: str) -> str:
    n = name.lower()
    if re.search(r"co-?op|cooperative|\be ?m ?c\b|elec(tric)? member|r ?e ?c\b|rural elec|\brrl\b|\brea\b", n):
        return "Cooperative"
    if re.search(r"^city of|^town of|^village of|municipal|utilities commission|light & power", n):
        return "Municipal"
    if re.search(r"public power|p ?u ?d\b|power district|public utility district", n):
        return "Political Subdivision"
    return "unknown"


def candidates(fips5: str, state: str, eia, year: int = 2024) -> list[dict]:
    terr = eia("eia861_service_territory")
    sales = eia("eia861_sales_ult_cust")
    ud = eia("eia861_utility_data")
    sf = eia("eia861_short_form")
    rows = terr[terr.county_fips == fips5].drop_duplicates("utility_number")
    out = []
    for _, t in rows.iterrows():
        un = int(t.utility_number)
        s = sales[(sales.utility_number == un) & (sales.state == state)]
        s = s[s.part == "A"] if (s.part == "A").any() else s
        d = ud[ud.utility_number == un]
        f = sf[(sf.utility_number == un) & (sf.state == state)]
        if not len(f):
            f = sf[sf.utility_number == un]
        c = {"utility_number": un, "utility_name": t.utility_name, "short_form": t.short_form == "Y"}
        if len(d):
            c["ownership"], c["ownership_provenance"] = d.ownership_type.iloc[0], f"observed (EIA-861 Utility_Data {year})"
            tv = d.transmission.dropna()
            # EIA marks activities "Y"; most other utilities leave the field blank. Blank is unknown
            # (D-110): transmission_owner is None and run() carries both cost-share cases.
            if len(tv):
                c["transmission_owner"] = bool((tv == "Y").any())
                c["transmission_owner_provenance"] = f"observed (EIA-861 Utility_Data {year}: {'Y' if c['transmission_owner'] else 'N'})"
            else:
                c["transmission_owner"] = None
                c["transmission_owner_provenance"] = f"assumed (EIA-861 Utility_Data {year}: transmission blank: unknown; both cases carried)"
        elif len(f) and f.ownership.iloc[0]:
            c["ownership"], c["ownership_provenance"] = f.ownership.iloc[0], f"observed (EIA-861 Short_Form {year})"
            c["transmission_owner"] = False
            c["transmission_owner_provenance"] = "assumed (short-form filers are small distribution utilities)"
        else:
            c["ownership"], c["ownership_provenance"] = _ownership_from_name(t.utility_name), "derived (name)"
            c["transmission_owner"] = False
            c["transmission_owner_provenance"] = "assumed (utility not in EIA-861 Utility_Data)"
        if len(s) and s.residential_revenue_kusd.sum() > 0 and s.residential_mwh.sum() > 0:
            g = s.sum(numeric_only=True)
            c.update(
                rate_basis="residential",
                residential_revenue_usd=float(g.residential_revenue_kusd) * 1000,
                residential_mwh=float(g.residential_mwh),
                residential_customers=float(g.residential_customers),
                total_mwh=float(g.total_mwh),
                residential_avg_rate_usd_per_kwh=float(g.residential_revenue_kusd / g.residential_mwh),
                residential_kwh_per_customer=float(g.residential_mwh * 1000 / max(g.residential_customers, 1)),
                industrial_avg_rate_usd_per_kwh=(float(g.industrial_revenue_kusd / g.industrial_mwh)
                                                 if g.industrial_mwh > 0 else float(g.total_revenue_kusd / g.total_mwh)),
                data=f"observed (EIA-861 Sales_Ult_Cust {year})")
        elif len(f) and f.total_revenue_thousand_dollars.iloc[0] > 0 and f.total_sales_mwh.iloc[0] > 0:
            g = f.iloc[0]
            c.update(
                rate_basis="all_sectors_stand_in",
                all_sector_revenue_usd=float(g.total_revenue_thousand_dollars) * 1000,
                all_sector_mwh=float(g.total_sales_mwh),
                all_sector_customers=float(g.total_customers),
                avg_rate_all_sectors_usd_per_kwh=float(g.avg_rate_all_sectors_usd_per_kwh),
                kwh_per_customer_all_sectors=float(g.kwh_per_customer_all_sectors),
                data=f"observed (EIA-861 Short_Form {year}), all-sector totals used as residential stand-ins")
        else:
            c["data"] = ("missing: short-form utility not in EIA-861 Short_Form" if c["short_form"]
                         else "missing: no Sales_Ult_Cust row for this state")
        out.append(c)
    return out


def q1_income(acs_row, rng):
    """ACS 2020-2024 mean income of the lowest quintile (B19081), drawn from a normal with the
    Census 90% margin of error (sd = MOE / 1.645), floored at a quarter of the estimate."""
    if acs_row is None or acs_row.get("mean_q1") is None or not np.isfinite(acs_row.get("mean_q1", np.nan)):
        return None
    m = float(acs_row["mean_q1"])
    sd = float(acs_row.get("mean_q1_moe") or 0) / 1.645
    return max(rng.normal(m, sd), 0.25 * m)


def unit_costs(cfg, rng):
    """Draw every unit cost once, in a fixed order, so two upgrade lists priced in the same
    seed use the same unit costs (common random numbers)."""
    c = cfg["costs"]
    return {"line": {k: u(rng, v) for k, v in c["line_musd_per_km"].items()},
            "rebuild_share": u(rng, c["line_rebuild_share_of_new"]),
            "substation": {k: u(rng, v) for k, v in c["new_substation_musd"].items()},
            "trafo_per_mva": u(rng, c["transformer_expansion_usd_per_mva"]),
            "var_per_mvar": u(rng, c["voltage_support_usd_per_mvar"])}


def upgrade_cost_usd(upgrades, cfg, rng):
    uc = unit_costs(cfg, rng)
    total, items = 0.0, []
    for up in upgrades or []:
        t, kv = up["type"], up.get("kv", 0)
        if t == "line_new":
            usd = up["km"] * uc["line"][cost_band(kv)] * 1e6
        elif t == "line_rebuild":
            usd = up["km"] * uc["line"][cost_band(kv)] * 1e6 * uc["rebuild_share"]
        elif t == "substation" and up.get("subtype") == "transformer expansion":
            usd = up["mva"] * uc["trafo_per_mva"]
        elif t == "substation":
            usd = uc["substation"][cost_band(kv)] * 1e6
        elif t == "voltage_support":
            usd = up["mvar"] * uc["var_per_mvar"]
        else:
            usd = 0.0
        items.append({**up, "usd": usd})
        total += usd
    return total, items


LARGE_LOAD_METHOD = (
    "back-test v2 §5.5(b), D-115: the site is its own rate class and pays its incremental supply cost in "
    "full (no unrecovered capacity, no margin on its sales); the cost left to other customers is the grid "
    "upgrade cost under the allocation (direct assignment: none; large-load tariff: the drawn ratepayer "
    "share; socialized: all), times the share landing on this utility's retail customers; residential "
    "share by energy, as in the main model")


def large_load(cases, cap, crf, alloc, share, rev, bill, inc, site_share):
    """Rate effect for a site above the validity limit (D-102), from the same draws as the main model.
    Valid at any site share: nothing in it scales with the site's sales."""
    by_case = {}
    for name, retail in cases.items():
        net = cap * crf * alloc * retail
        d_rate = 100 * net * share / rev
        d_bill = bill * d_rate / 100
        by_case[name] = {"lowest_quintile_rate_change_pct": d_rate, "lowest_quintile_bill_change_usd_per_yr": d_bill,
                         "lowest_quintile_energy_cost_share_change_pp": (100 * d_bill / inc) if inc else INCOME_MISSING,
                         "net_annual_cost_to_other_customers_usd": net}
    top = max(by_case.values(), key=lambda v: v["lowest_quintile_rate_change_pct"])
    out = {**top, "valid_for_site_share": True, "site_share_of_utility_sales": site_share, "method": LARGE_LOAD_METHOD}
    if len(by_case) > 1:
        out["cases"] = by_case
    return out


def run(cands, upgrades, site, onsite, allocation, acs_row, cfg, rng):
    """site: {peak_mw_net, grid_mwh}. Returns one result per candidate utility."""
    r = cfg["rates"]
    r_cost, rng = rng.spawn(2)
    cap, items = upgrade_cost_usd(upgrades, cfg, r_cost)
    crf = u(rng, r["capital_recovery_factor"])
    alloc = {"direct_assignment": 0.0, "large_load_tariff": u(rng, r["large_load_tariff_ratepayer_share"]),
             "socialized": 1.0}[allocation]
    capacity = site["peak_mw_net"] * u(rng, r["capacity_cost_usd_per_mw_yr"]) * u(rng, r["capacity_cost_unrecovered_share"])
    margin_share = u(rng, r["margin_on_new_sales_share"])
    q1_share = u(rng, r["lowest_quintile_kwh_share"])
    inc = q1_income(acs_row, rng)
    dist_share = u(rng, r["retail_share_if_distribution_only"])
    res = []
    for c in cands:
        if "rate_basis" not in c:
            res.append({"utility_number": c["utility_number"], "status": "indeterminate", "reason": c["data"]})
            continue
        owner = c.get("transmission_owner")
        cases = ({"transmission_owner": r["retail_share_if_transmission_owner"], "distribution_only": dist_share}
                 if owner is None else
                 {("transmission_owner" if owner else "distribution_only"):
                  r["retail_share_if_transmission_owner"] if owner else dist_share})
        if c["rate_basis"] == "residential":
            ind_rate, rev, share = c["industrial_avg_rate_usd_per_kwh"], c["residential_revenue_usd"], (
                c["residential_mwh"] / c["total_mwh"] if c["total_mwh"] else 1.0)
            rate, kwh = c["residential_avg_rate_usd_per_kwh"], c["residential_kwh_per_customer"]
        else:  # all-sector stand-in: costs spread evenly across sectors by energy
            ind_rate, rev, share = c["avg_rate_all_sectors_usd_per_kwh"], c["all_sector_revenue_usd"], 1.0
            rate, kwh = c["avg_rate_all_sectors_usd_per_kwh"], c["kwh_per_customer_all_sectors"]
        util_mwh = c["total_mwh"] if c["rate_basis"] == "residential" else c["all_sector_mwh"]
        site_share = site["grid_mwh"] / util_mwh if util_mwh else float("inf")
        margin = site["grid_mwh"] * 1000 * ind_rate * margin_share
        bill = kwh * q1_share * rate
        by_case = {}
        for name, retail in cases.items():
            net = cap * crf * alloc * retail + capacity - margin
            d_rate = 100 * net * share / rev
            d_bill = bill * d_rate / 100
            by_case[name] = {
                "retail_share_of_upgrades": retail,
                "lowest_quintile_rate_change_pct": d_rate,
                "lowest_quintile_bill_change_usd_per_yr": d_bill,
                "lowest_quintile_energy_cost_share_change_pp": (100 * d_bill / inc) if inc else INCOME_MISSING,
                "net_annual_cost_to_customers_usd": net,
                "components_usd_per_yr": {"upgrades": cap * crf * alloc * retail, "capacity_unrecovered": capacity,
                                          "margin_on_site_sales": -margin}}
        # Headline fields: the single case, or, when ownership is unknown, the case with the larger
        # rate change (the upper end of the range). The range itself is in `cases` (D-110).
        top = max(by_case.values(), key=lambda v: v["lowest_quintile_rate_change_pct"])
        x = {"utility_number": c["utility_number"], "status": "computed", "rate_basis": c["rate_basis"],
             "site_share_of_utility_sales": site_share,
             "outside_validity": site_share > r["max_site_share_of_utility_sales"],
             "transmission_case": "unknown; both cases carried" if owner is None else next(iter(by_case)),
             **{k: v for k, v in top.items() if k != "retail_share_of_upgrades"}}
        if owner is None:
            x["cases"] = by_case
        if x["outside_validity"]:
            x["large_load"] = large_load(cases, cap, crf, alloc, share, rev, bill, inc, site_share)
        res.append(x)
    draws = {"capital_recovery_factor": crf, "allocation_ratepayer_share": alloc,
             "margin_on_new_sales_share": margin_share, "lowest_quintile_kwh_share": q1_share,
             "retail_share_if_distribution_only": dist_share, "capacity_cost_unrecovered_usd": capacity,
             "upgrade_capex_usd": cap}
    return {"upgrade_capex_usd": cap, "upgrade_items": items, "crf": crf, "allocation": allocation, "draws": draws,
            "allocation_ratepayer_share": alloc, "q1_mean_income_usd": inc, "per_utility": res,
            "onsite_capex_usd_site_owned": onsite.get("capex_usd", 0.0),
            "local_tax_effect": "not_modelled"}
