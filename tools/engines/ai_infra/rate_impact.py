"""Rate-impact module: what happens to residential rates for the lowest-income households?

No retail service-territory polygons exist, so the serving utility at a point is unknown.
The module runs every utility EIA-861 lists for the county, as if it served the site, and
reports each. Utility revenue, sales, customers and ownership are observed (EIA-861 2024);
costs, cost recovery and cost allocation are assumed and drawn per seed.

Rate change = net annual cost landing on the utility's customers, times the residential
share of its energy sales, divided by its residential revenue. Under a single residential
tariff the lowest quintile sees the same percentage change; its income effect uses incomes
calibrated to SAIPE (D-008).
"""
from __future__ import annotations

import math
import re

import numpy as np
from scipy.stats import norm

from .power_flow import cost_band, u

ALLOCATIONS = ("direct_assignment", "large_load_tariff", "socialized")

# The SAIPE-calibrated lognormal shared with tools/harness/households.py puts the lowest
# quintile's mean income at ~$1,200 in Wilcox AL and ~$500 in McDowell WV (sigma 2.7-3.4),
# far below what ACS reports. Until ACS B19081 (mean income by quintile) is a layer (LR-11),
# the income-share output is withheld rather than reported from that tail.
INCOME_SHARE_STATUS = "indeterminate: lowest-quintile income model implausible in high-poverty counties (LR-11)"


def _ownership_from_name(name: str) -> str:
    n = name.lower()
    if re.search(r"co-?op|cooperative|\be ?m ?c\b|elec(tric)? member|r ?e ?c\b|rural elec|\brrl\b|\brea\b", n):
        return "Cooperative"
    if re.search(r"^city of|^town of|^village of|municipal|utilities commission|light & power", n):
        return "Municipal"
    if re.search(r"public power|p ?u ?d\b|power district|public utility district", n):
        return "Political Subdivision"
    return "unknown"


def candidates(fips5: str, state: str, eia) -> list[dict]:
    terr = eia("eia861_service_territory")
    sales = eia("eia861_sales_ult_cust")
    ud = eia("eia861_utility_data")
    rows = terr[terr.county_fips == fips5].drop_duplicates("utility_number")
    out = []
    for _, t in rows.iterrows():
        un = int(t.utility_number)
        s = sales[(sales.utility_number == un) & (sales.state == state)]
        s = s[s.part == "A"] if (s.part == "A").any() else s
        d = ud[ud.utility_number == un]
        own = d.ownership_type.iloc[0] if len(d) else None
        c = {"utility_number": un, "utility_name": t.utility_name, "short_form": t.short_form == "Y"}
        if own:
            c["ownership"], c["ownership_provenance"] = own, "observed (EIA-861 Utility_Data)"
            c["transmission_owner"] = bool((d.transmission == "Y").any())
        else:
            c["ownership"], c["ownership_provenance"] = _ownership_from_name(t.utility_name), "derived (name)"
            c["transmission_owner"] = False
        if len(s) and s.residential_revenue_kusd.sum() > 0 and s.residential_mwh.sum() > 0:
            g = s.sum(numeric_only=True)
            c.update(
                residential_revenue_usd=float(g.residential_revenue_kusd) * 1000,
                residential_mwh=float(g.residential_mwh),
                residential_customers=float(g.residential_customers),
                total_mwh=float(g.total_mwh),
                residential_avg_rate_usd_per_kwh=float(g.residential_revenue_kusd / g.residential_mwh),
                residential_kwh_per_customer=float(g.residential_mwh * 1000 / max(g.residential_customers, 1)),
                industrial_avg_rate_usd_per_kwh=(float(g.industrial_revenue_kusd / g.industrial_mwh)
                                                 if g.industrial_mwh > 0 else float(g.total_revenue_kusd / g.total_mwh)),
                data="observed (EIA-861 Sales_Ult_Cust 2024)")
        else:
            c["data"] = ("missing: EIA-861 short-form utility, no Sales_Ult_Cust row (layer request LR-10)"
                         if c["short_form"] else "missing: no Sales_Ult_Cust row for this state")
        out.append(c)
    return out


def q1_income(county_row, rng):
    """Mean income of the lowest quintile, lognormal calibrated to SAIPE median and poverty,
    each drawn inside its 90% interval (D-008). Same calibration as tools/harness/households.py."""
    med = rng.uniform(county_row["median_hh_income_2023_ci90_lo"], county_row["median_hh_income_2023_ci90_hi"])
    pov = rng.uniform(county_row["poverty_rate_2023_ci90_lo"], county_row["poverty_rate_2023_ci90_hi"]) / 100
    p = min(max(pov, 0.02), 0.48)
    sigma = math.log(1 / 0.30) / abs(norm.ppf(p))
    mu = math.log(med)
    q20 = math.exp(mu + sigma * norm.ppf(0.2))
    return math.exp(mu + sigma ** 2 / 2) * norm.cdf((math.log(q20) - mu - sigma ** 2) / sigma) / 0.2


def upgrade_cost_usd(upgrades, cfg, rng):
    c = cfg["costs"]
    total, items = 0.0, []
    for up in upgrades or []:
        t, kv = up["type"], up.get("kv", 0)
        if t == "line_new":
            usd = up["km"] * u(rng, c["line_musd_per_km"][cost_band(kv)]) * 1e6
        elif t == "line_rebuild":
            usd = up["km"] * u(rng, c["line_musd_per_km"][cost_band(kv)]) * 1e6 * u(rng, c["line_rebuild_share_of_new"])
        elif t == "substation" and up.get("subtype") == "transformer expansion":
            usd = up["mva"] * u(rng, c["transformer_expansion_usd_per_mva"])
        elif t == "substation":
            usd = u(rng, c["new_substation_musd"][cost_band(kv)]) * 1e6
        elif t == "voltage_support":
            usd = up["mvar"] * u(rng, c["voltage_support_usd_per_mvar"])
        else:
            usd = 0.0
        items.append({**up, "usd": usd})
        total += usd
    return total, items


def run(cands, upgrades, site, onsite, allocation, county_row, cfg, rng):
    """site: {peak_mw_net, grid_mwh}. Returns one result per candidate utility."""
    r = cfg["rates"]
    cap, items = upgrade_cost_usd(upgrades, cfg, rng)
    crf = u(rng, r["capital_recovery_factor"])
    alloc = {"direct_assignment": 0.0, "large_load_tariff": u(rng, r["large_load_tariff_ratepayer_share"]),
             "socialized": 1.0}[allocation]
    capacity = site["peak_mw_net"] * u(rng, r["capacity_cost_usd_per_mw_yr"]) * u(rng, r["capacity_cost_unrecovered_share"])
    margin_share = u(rng, r["margin_on_new_sales_share"])
    q1_share = u(rng, r["lowest_quintile_kwh_share"])
    inc = q1_income(county_row, rng)  # kept in the record for diagnosis; not used for any output
    dist_share = u(rng, r["retail_share_if_distribution_only"])
    res = []
    for c in cands:
        if "residential_revenue_usd" not in c:
            res.append({"utility_number": c["utility_number"], "status": "indeterminate", "reason": c["data"]})
            continue
        retail = r["retail_share_if_transmission_owner"] if c["transmission_owner"] else dist_share
        margin = site["grid_mwh"] * 1000 * c["industrial_avg_rate_usd_per_kwh"] * margin_share
        net = cap * crf * alloc * retail + capacity - margin
        res_share = c["residential_mwh"] / c["total_mwh"] if c["total_mwh"] else 1.0
        d_rate = 100 * net * res_share / c["residential_revenue_usd"]
        bill = c["residential_kwh_per_customer"] * q1_share * c["residential_avg_rate_usd_per_kwh"]
        res.append({"utility_number": c["utility_number"], "status": "computed",
                    "lowest_quintile_rate_change_pct": d_rate,
                    "lowest_quintile_bill_change_usd_per_yr": bill * d_rate / 100,
                    "lowest_quintile_energy_cost_share_change_pp": INCOME_SHARE_STATUS,
                    "net_annual_cost_to_customers_usd": net,
                    "components_usd_per_yr": {"upgrades": cap * crf * alloc * retail, "capacity_unrecovered": capacity,
                                              "margin_on_site_sales": -margin}})
    draws = {"capital_recovery_factor": crf, "allocation_ratepayer_share": alloc,
             "margin_on_new_sales_share": margin_share, "lowest_quintile_kwh_share": q1_share,
             "retail_share_if_distribution_only": dist_share, "capacity_cost_unrecovered_usd": capacity,
             "upgrade_capex_usd": cap}
    return {"upgrade_capex_usd": cap, "upgrade_items": items, "crf": crf, "allocation": allocation, "draws": draws,
            "allocation_ratepayer_share": alloc, "q1_mean_income_usd": inc, "per_utility": res,
            "onsite_capex_usd_site_owned": onsite.get("capex_usd", 0.0),
            "local_tax_effect": "not_modelled"}
