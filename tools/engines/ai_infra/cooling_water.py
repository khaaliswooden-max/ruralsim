"""Cooling-water module: how much water would cooling draw, against what local supply?

Screening-grade (D-106). Daily water use over 30 years of weather (NASA POWER daily means at
the county centroid, 1991-2020), per cooling type:

- evaporative: cooling-tower make-up = evaporation + blowdown. Evaporation is the latent share
  of rejected heat over the latent heat of water (0.681 kWh/kg); the latent share rises with
  wet-bulb temperature; blowdown = evaporation / (cycles of concentration - 1).
- adiabatic_hybrid: dry coolers, with evaporative pre-cooling only on days whose daily-mean
  dry-bulb temperature reaches a set point; on those days a share of heat is rejected by
  evaporation.
- dry: no water. Hot days raise PUE instead (reported, not fed back into power flow in v1).

Rejected heat is the facility's average load (IT load x PUE). Withdrawal = make-up water;
consumption = evaporation. Daily means understate hourly design wet-bulb, so peak days are
labelled as daily-mean peaks.

Compared with: county water use in 2015 (USGS, Dieter et al. 2018), community water systems
(EPA SDWIS), and stream low flow at a USGS gauge (NWIS day-of-year statistics). The source gauge
is the largest-drainage gauge with low-flow statistics within the search radius of the site;
the nearest gauge is reported alongside. Flow is taken at the gauge (drainage-area scale factor
1.0): the site's own drainage area needs NHDPlus, which is not a layer yet.
"""
from __future__ import annotations

import math

import numpy as np

from .power_flow import u

LATENT_KWH_PER_KG = 0.681     # 2.45 MJ/kg
M3_PER_MGAL = 3785.41
CFS_TO_M3_PER_DAY = 0.0283168 * 86400
COOLING_TYPES = ("evaporative", "adiabatic_hybrid", "dry")


def haversine_km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(a))


def pick_gauges(gauges, lat, lon, radius_km):
    """Source gauge: the largest drainage area within radius that has a low-flow statistic.
    Nearest gauge: the closest with a low-flow statistic. Either may be None."""
    g = gauges.dropna(subset=["dec_lat_va", "dec_long_va"]).copy()
    g["km"] = [haversine_km(lat, lon, a, b) for a, b in zip(g.dec_lat_va, g.dec_long_va)]
    near = g[(g.km <= radius_km) & g.p10_min_cfs.notna() & g.mean_flow_cfs.notna()]
    if near.empty:
        return None, None
    src = near.sort_values(["drain_area_sqmi", "km"], ascending=[False, True]).iloc[0]
    nst = near.sort_values("km").iloc[0]

    def rec(r):
        return {"site_no": r.site_no, "station_nm": r.station_nm, "km": float(r.km),
                "drain_area_sqmi": float(r.drain_area_sqmi) if r.drain_area_sqmi == r.drain_area_sqmi else None,
                "mean_flow_cfs": float(r.mean_flow_cfs), "p10_min_cfs": float(r.p10_min_cfs),
                "county_fips5": r.fips5, "drainage_area_scale_factor": 1.0}
    return rec(src), rec(nst)


def daily_withdrawal_m3(weather, it_avg_mw, pue, cooling, cfg, rng):
    """Per-day withdrawal and consumption (m3) over the weather record, plus effective PUE."""
    c = cfg["cooling"]
    heat_kwh_day = it_avg_mw * pue * 1000 * 24
    tw = weather["t2mwet_c"].to_numpy()
    tdb = weather["t2m_c"].to_numpy()
    draws = {}
    if cooling == "evaporative":
        lo, hi = c["evaporative_latent_share_range"]
        off = u(rng, c["evaporative_latent_share_offset"])
        t0, t1 = c["evaporative_latent_share_tw_c"]
        share = np.clip(lo + (hi - lo) * (tw - t0) / (t1 - t0) + off, 0.0, 1.0)
        coc = u(rng, c["cycles_of_concentration"])
        evap = heat_kwh_day * share / LATENT_KWH_PER_KG / 1000           # m3
        wd = evap * (1 + 1 / (coc - 1))
        pue_eff = np.full_like(tw, pue)
        draws = {"latent_share_offset": off, "cycles_of_concentration": coc}
    elif cooling == "adiabatic_hybrid":
        set_c = u(rng, c["adiabatic_setpoint_daily_mean_c"])
        frac = u(rng, c["adiabatic_evaporated_share_of_heat"])
        coc = u(rng, c["cycles_of_concentration"])
        on = tdb >= set_c
        evap = np.where(on, heat_kwh_day * frac / LATENT_KWH_PER_KG / 1000, 0.0)
        wd = evap * (1 + 1 / (coc - 1))
        pue_eff = np.full_like(tw, pue)
        draws = {"setpoint_c": set_c, "evaporated_share": frac, "cycles_of_concentration": coc,
                 "days_per_year_spraying": float(on.mean() * 365.25)}
    elif cooling == "dry":
        hot_c = u(rng, c["dry_hot_day_daily_mean_c"])
        dpue = u(rng, c["dry_pue_penalty_on_hot_days"])
        evap = np.zeros_like(tw)
        wd = np.zeros_like(tw)
        pue_eff = np.where(tdb >= hot_c, pue + dpue, pue)
        draws = {"hot_day_c": hot_c, "pue_penalty": dpue}
    else:
        raise ValueError(cooling)
    return wd, evap, pue_eff, draws


def run(weather, it_avg_mw, pue, cooling, county_use, gauges_pick, cws, cfg, rng):
    wd, evap, pue_eff, draws = daily_withdrawal_m3(weather, it_avg_mw, pue, cooling, cfg, rng)
    years = len(wd) / 365.25
    annual = float(wd.sum() / years)
    annual_cons = float(evap.sum() / years)
    peak = float(np.max(wd))
    p996 = float(np.percentile(wd, 99.6))
    avg_day = annual / 365.25
    out = {"cooling_type": cooling, "status": "computed", "draws": draws,
           "annual_withdrawal_m3": annual, "annual_consumption_m3": annual_cons,
           "annual_withdrawal_gallons": annual * 264.172,
           "peak_day_withdrawal_m3": peak, "p996_day_withdrawal_m3": p996,
           "peak_basis": "daily-mean weather; hourly design peaks are higher",
           "wue_l_per_it_kwh": annual * 1000 / (it_avg_mw * 1000 * 8766) if it_avg_mw else None,
           "pue_effective_annual": float(np.mean(pue_eff))}
    if county_use is not None:
        ps = county_use.get("ps_wfrto")
        to = county_use.get("to_wfrto")
        out["share_of_county_public_supply"] = (avg_day / (ps * M3_PER_MGAL)) if ps else None
        out["share_of_county_fresh_withdrawals"] = (avg_day / (to * M3_PER_MGAL)) if to else None
        pc = county_use.get("ps_per_capita_gpd")
        out["equivalent_people_at_county_public_supply_rate"] = (avg_day * 264.172 / pc) if pc else None
    else:
        out["county_comparison"] = "indeterminate: no USGS 2015 row for this county"
    src, nearest = gauges_pick
    if src is not None:
        lf = src["p10_min_cfs"] * CFS_TO_M3_PER_DAY
        out["source_gauge"] = src
        out["share_of_source_low_flow_peak_day"] = (peak / lf) if lf > 0 else (math.inf if peak > 0 else 0.0)
        out["share_of_source_mean_flow_annual"] = avg_day / (src["mean_flow_cfs"] * CFS_TO_M3_PER_DAY)
    else:
        out["source_gauge"] = None
        out["share_of_source_low_flow_peak_day"] = "indeterminate: no gauge with low-flow statistics within radius"
    if nearest is not None:
        lfn = nearest["p10_min_cfs"] * CFS_TO_M3_PER_DAY
        out["nearest_gauge"] = nearest
        out["share_of_nearest_low_flow_peak_day_unscored"] = (peak / lfn) if lfn > 0 else (math.inf if peak > 0 else 0.0)
    out["community_water_systems"] = cws
    out["water_within_recharge"] = "indeterminate: no modelled sustainable yield"
    return out
