"""Baseline + intervention engines for the harness.

Only what can be computed honestly from observed layers is computed; everything else
is tagged assumed and reported as such. Missing indicators are omitted from the
geometric mean and listed in `domains_missing` rather than filled with fiction.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def viewer_dir(fips: str) -> Path:
    return next((ROOT / "worlds").glob(f"{fips}_*/viewer_data"))


def load_facilities(fips: str) -> dict:
    return json.load(open(viewer_dir(fips) / "facilities.json"))


# ---------------------------------------------------------------- baselines

def travel_minutes_to(net, hh: pd.DataFrame, targets: list[list[float]]) -> np.ndarray:
    """Minutes from each household to the nearest target over the road graph."""
    if not targets:
        return np.full(len(hh), np.nan)
    dists = []
    pens = []
    for t in targets:
        d, pen = net.times_from(t)
        dists.append(d)
        pens.append(pen)
    node_index = {n: i for i, n in enumerate(net.g.nodes)}
    mat = np.full((len(targets), len(node_index)), np.inf)
    for ti, d in enumerate(dists):
        for n, s in d.items():
            mat[ti, node_index[n]] = s + pens[ti]
    # household snap
    hh_nodes = []
    hh_pens = []
    for x, y in zip(hh["x"].to_numpy(), hh["y"].to_numpy()):
        node, pen = net.snap((x, y))
        hh_nodes.append(node_index[node])
        hh_pens.append(pen)
    cols = mat[:, hh_nodes]  # targets x households
    best = np.min(cols, axis=0) + np.array(hh_pens)
    out = best / 60.0
    out[~np.isfinite(out)] = np.nan  # disconnected OSM subgraph -> honest NaN, not inf
    return out


def baseline_indicators(fips: str, net, hh: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Per-household indicator table + provenance tags per indicator."""
    fac = load_facilities(fips)
    hosp = [h["pos"] for h in fac.get("hospitals", [])]
    schools = [s["pos"] for s in fac.get("schools", [])]

    tags = {}
    out = pd.DataFrame(index=hh.index)

    t_hosp = travel_minutes_to(net, hh, hosp)
    out["minutes_to_emergency_care"] = t_hosp
    tags["minutes_to_emergency_care"] = "derived (OSM road graph to observed hospital; speeds assumed)"
    out["minutes_to_primary_care"] = t_hosp  # proxy: same destination set
    tags["minutes_to_primary_care"] = "derived proxy (hospital used as primary-care destination; clinic layer not fetched)"
    # obstetric care: no OB capability layer -> omit (do not fabricate)

    t_school = travel_minutes_to(net, hh, schools)
    out["school_travel_minutes_one_way"] = t_school
    tags["school_travel_minutes_one_way"] = "derived (OSM road graph to observed schools)"

    # EMS p90 proxy: turnout (assumed 6 min) + travel from hospital to household
    out["ems_response_minutes_p90"] = t_hosp + 6.0
    tags["ems_response_minutes_p90"] = "derived + assumed (turnout 6 min assumed; station=hospital)"

    # connectivity: no FCC BDC layer fetched for pilots -> assumed distribution
    rng = np.random.default_rng(int(fips) + 7)
    out["usable_upload_mbps"] = rng.uniform(0.5, 25, len(hh))  # ASSUMED placeholder
    out["usable_download_mbps"] = out["usable_upload_mbps"] * rng.uniform(4, 10, len(hh))
    tags["usable_upload_mbps"] = "assumed (uniform 0.5-25; FCC BDC layer not in pilot bundle)"
    tags["usable_download_mbps"] = "assumed (scaled from upload; FCC BDC layer not in pilot bundle)"
    out["broadband_cost_share_of_income"] = 80.0 * 12 / hh["income"].clip(lower=1)  # $80/mo assumed
    tags["broadband_cost_share_of_income"] = "assumed ($80/mo plan over calibrated income)"

    # power reliability: county SAIDI not fetched -> assumed
    out["outage_hours_per_year"] = 8.0
    out["longest_outage_hours"] = 24.0
    tags["outage_hours_per_year"] = "assumed (rural SAIDI placeholder; EIA reliability not in bundle)"
    tags["longest_outage_hours"] = "assumed"

    # economic security
    essentials = 0.62 * hh["income"]  # assumed essentials share
    out["income_after_essentials"] = hh["income"] - essentials
    tags["income_after_essentials"] = "calibrated income minus assumed essentials share 0.62"
    out["energy_cost_share_of_income"] = (220.0 * 12) / hh["income"].clip(lower=1)  # assumed $220/mo
    tags["energy_cost_share_of_income"] = "assumed ($220/mo energy over calibrated income)"

    # mobility extras: grocery destinations not fetched -> omit minutes_to_grocery
    det = bridge_detour_minutes(fips, net, hh, hosp)
    out["detour_minutes_from_closed_or_posted_bridges"] = det
    tags["detour_minutes_from_closed_or_posted_bridges"] = "derived (NBI poor bridges removed from OSM graph)"

    # water: SDWIS violation day counts not fetched -> omit days_under_health_based_violation
    out["supply_interruption_hours"] = 6.0
    tags["supply_interruption_hours"] = "assumed placeholder"

    # education extra
    out["household_can_do_remote_learning"] = (out["usable_download_mbps"] >= 25).astype(float)
    tags["household_can_do_remote_learning"] = "derived from assumed bandwidth (25 Mbps threshold)"

    # environment: no noise/PM source -> omit both
    # cost burden: 0 by definition at baseline
    out["change_in_utility_rates_and_local_taxes"] = 0.0
    tags["change_in_utility_rates_and_local_taxes"] = "baseline definition (0)"

    return out, tags


def bridge_detour_minutes(fips: str, net, hh: pd.DataFrame, hosp, sample: int = 200) -> np.ndarray:
    """Mean added minutes to hospital if poor-condition bridges were closed.

    Computed per household as its own detour delta; households unaffected get 0.
    Bridges not on any household->hospital path contribute 0 (honest).
    """
    bridges = json.load(open(viewer_dir(fips) / "bridges.json"))
    poor = [b for b in bridges if str(b.get("cond", "")).upper().startswith("P")]
    if not poor or not hosp:
        return np.zeros(len(hh))
    base = travel_minutes_to(net, hh, hosp)
    # remove graph edges nearest to each poor bridge (one edge per bridge, within 40 m)
    removed = []
    for b in poor:
        xy = b["pos"]
        d, i = net.tree.query(np.atleast_2d(xy))
        if d[0] > 40:
            continue
        n = tuple(net.nodes[i[0]])
        nbrs = list(net.g.neighbors(n))
        if not nbrs:
            continue
        # cut the edge most aligned with the bridge direction is unknown; cut the
        # shortest edge (most likely the crossing segment)
        e = min(nbrs, key=lambda m: net.g[n][m]["w"])
        removed.append((n, e, net.g[n][e]["w"]))
        net.g.remove_edge(n, e)
    try:
        alt = travel_minutes_to(net, hh, hosp)
    finally:
        for n, e, w in removed:
            net.g.add_edge(n, e, w=w)
    delta = np.full(len(hh), 20.0)  # unreachable after closure -> spec floor value
    ok = np.isfinite(alt) & np.isfinite(base)
    delta[ok] = np.maximum(alt[ok] - base[ok], 0)
    delta[~np.isfinite(base)] = 0.0  # already unreachable at baseline: no added detour
    return delta


# ------------------------------------------------------------- interventions

def apply_exp0002_telehealth(base: pd.DataFrame, params: dict, rng) -> pd.DataFrame:
    """EXP-0002: eligible low-acuity visits shift to telehealth for households with
    usable upload >= threshold. Travel minutes to primary care fall by the eligible
    visit share for eligible households only."""
    out = base.copy()
    thr = params.get("min_upload_mbps", 3)
    share = params.get("eligible_visit_share", 0.35)
    eligible = out["usable_upload_mbps"] >= thr
    out["excluded_by_bandwidth"] = (~eligible).astype(float)
    red = np.where(eligible, share, 0.0)
    out["minutes_to_primary_care"] = out["minutes_to_primary_care"] * (1 - red)
    return out


def apply_exp0006_drone(fips: str, hh: pd.DataFrame, params: dict, rng) -> dict:
    """EXP-0006: drone delivery reachability vs road baseline. Geometry observed;
    flight parameters assumed per card."""
    fac = load_facilities(fips)
    hub = fac["hospitals"][0]["pos"]
    rng_km = params.get("range_km", 40)
    cruise = 25.0  # m/s, assumed (card does not specify)
    max_wind = params.get("max_wind_m_s", 12)
    dx = hh["x"].to_numpy() - hub[0]
    dy = hh["y"].to_numpy() - hub[1]
    dist_km = np.hypot(dx, dy) / 1000.0
    flight_min = dist_km * 1000 / cruise / 60.0 + 6.0  # +6 min handling, assumed
    reachable_geo = (dist_km <= rng_km) & (flight_min <= 30.0)
    # weather: Weibull wind (assumed), grounded when wind > max_wind
    wind = rng.weibull(2.0, len(hh)) * 7.0  # scale 7 m/s assumed
    grounded = wind > max_wind
    reachable = reachable_geo & ~grounded
    return {
        "share_reachable_30min": float(np.mean(reachable)),
        "share_grounded_today": float(np.mean(grounded)),
        "hub": hub,
    }


# ============================================================ Tier-2 engines
# Reduced-order but physically motivated. Every parameter not from an observed
# layer is tagged assumed/hypothetical in the run record via the card.

def _climate(fips: str) -> pd.DataFrame:
    p = next((ROOT / "worlds").glob(f"{fips}_*/layers_raw/climate/openmeteo_daily_1991_2020.csv"))
    return pd.read_csv(p, parse_dates=["date"])


def _terrain(fips: str):
    import json as _json
    vd = viewer_dir(fips)
    meta = _json.load(open(vd / "terrain_meta.json"))
    grid = np.fromfile(vd / "terrain_grid.f32", dtype="float32").reshape(meta["shape"])
    return np.array(meta["enu_x"]), np.array(meta["enu_y"]), grid


def _elev_at(ex, ey, grid, x, y):
    ix = np.clip(np.searchsorted(ex, x) - 1, 0, len(ex) - 1)
    iy = np.clip(np.searchsorted(ey, y) - 1, 0, len(ey) - 1)
    return grid[iy, ix]


def _los_clear(ex, ey, grid, a, b, n=40, clearance_m=10.0):
    """True if the link a->b clears terrain. Clearance requirement tapers to zero at
    the endpoints (the line terminates at the antennas) and peaks mid-path —
    simplified first-Fresnel-zone rule."""
    xs = np.linspace(a[0], b[0], n)
    ys = np.linspace(a[1], b[1], n)
    t = np.linspace(0, 1, n)
    za = _elev_at(ex, ey, grid, a[0], a[1]) + 30  # tower height 30 m assumed
    zb = _elev_at(ex, ey, grid, b[0], b[1]) + 5  # rooftop CPE 5 m assumed
    zline = za + t * (zb - za)
    zterr = _elev_at(ex, ey, grid, xs, ys)
    clr = clearance_m * np.sin(np.pi * t)
    return bool(np.all(zline >= zterr + clr))


def eng_exp0001_ems(fips, net, hh, base_vals, params, rng):
    """EXP-0001: EMS pre-positioning. Event simulation over one year of calls.
    Call rate and turnout assumed; geometry observed."""
    pop = len(hh)
    calls_per_day = params.get("calls_per_day", pop * 0.3 / 365 / 2.0)  # 0.3 calls/capita/yr assumed; hh~2 pop
    try:
        n_amb = int(params.get("ambulances", 3))
    except (TypeError, ValueError):
        n_amb = 3  # card says "baseline count"; actual fleet unknown -> assumed 3
    turnout_min = 2.0  # assumed
    hosp = load_facilities(fips)["hospitals"][0]["pos"]
    shift = float(params.get("reposition_interval_min", 30))

    # demand clusters: weighted k-means (k=3) on household points, simple Lloyd iterations
    k = 3
    pts = hh[["x", "y"]].to_numpy()
    centers = pts[rng.choice(len(pts), k, replace=False)].copy()
    for _ in range(12):
        d = ((pts[:, None, :] - centers[None]) ** 2).sum(-1)
        lab = d.argmin(1)
        for j in range(k):
            if (lab == j).any():
                centers[j] = pts[lab == j].mean(0)

    def simulate(stations):
        st_nodes = [net.times_from(s) for s in stations]
        node_index = {n: i for i, n in enumerate(net.g.nodes)}
        st_fields = []
        for d, pen in st_nodes:
            f = np.full(len(node_index), np.inf)
            for n_, s in d.items():
                f[node_index[n_]] = s + pen
            st_fields.append(f)
        # household node indices
        hh_idx = np.array([node_index[net.snap((x, y))[0]] for x, y in pts])
        # calls over a year
        n_calls = rng.poisson(calls_per_day * 365)
        call_hh = rng.integers(0, len(hh), n_calls)
        call_time = np.sort(rng.uniform(0, 365 * 24 * 60, n_calls))  # minute of year
        # demand-driven station choice per shift window: nearest station to call (pre-positioning
        # effect = stations sit near demand; response is from nearest station)
        busy_until = np.zeros(n_amb)
        resp = np.full(n_calls, np.nan)
        unreachable = 0
        for i in range(n_calls):
            node = hh_idx[call_hh[i]]
            t_leg = np.array([f[node] for f in st_fields]) / 60.0  # minutes from each station
            travel = t_leg.min()  # nearest station answers (or pre-positioned unit)
            if not np.isfinite(travel):
                unreachable += 1  # disconnected OSM island: logged, no unit bricked
                continue
            order = np.argsort(busy_until)
            free = order[0]
            start = max(call_time[i], busy_until[free])
            wait = start - call_time[i]
            resp[i] = turnout_min + wait + travel
            busy_until[free] = start + travel + 45.0  # 45 min on-scene+transport, assumed
        return resp, unreachable

    base_resp, base_unr = simulate([hosp])
    int_resp, int_unr = simulate(list(centers))
    return {
        "p90_baseline_min": float(np.nanpercentile(base_resp, 90)),
        "p90_intervention_min": float(np.nanpercentile(int_resp, 90)),
        "change_pct": float(100 * (np.nanpercentile(int_resp, 90) - np.nanpercentile(base_resp, 90))
                            / np.nanpercentile(base_resp, 90)),
        "n_calls": int(len(base_resp)),
        "unreachable_calls_baseline": int(base_unr),
        "unreachable_calls_intervention": int(int_unr),
        "unreachable_note": "calls on disconnected OSM graph islands are excluded from p90, counted here",
    }


def eng_exp0003_battery(fips, hh, params, rng):
    """EXP-0003: battery ride-through on hospital feeder. Outage process assumed
    (Poisson storms, lognormal durations); battery parameters from card (assumed)."""
    power_mw = params.get("power_mw", 2)
    energy_mwh = params.get("energy_mwh", 8)
    rte = params.get("round_trip_efficiency", 0.86)
    crit_load_mw = 0.2  # hospital critical load, assumed
    autonomy_h = energy_mwh / crit_load_mw
    years = 5
    out_hours_base, out_hours_int = 0.0, 0.0
    longest_base = 0.0
    for _ in range(years):
        n_out = rng.poisson(3)  # 3 outage events/yr on feeder, assumed
        durs = rng.lognormal(mean=np.log(2.0), sigma=1.0, size=n_out)  # hours, assumed
        out_hours_base += durs.sum()
        longest_base = max(longest_base, durs.max() if n_out else 0)
        covered = np.minimum(durs, autonomy_h)
        out_hours_int += (durs - covered).sum()
    capex = 400_000 * energy_mwh  # $/kWh 400 assumed
    return {
        "outage_hours_per_year_baseline": out_hours_base / years,
        "outage_hours_per_year_intervention": out_hours_int / years,
        "change_pct": 100 * (out_hours_int - out_hours_base) / max(out_hours_base, 1e-9),
        "longest_outage_hours_baseline": longest_base,
        "battery_autonomy_hours": autonomy_h,
        "capex_usd_assumed": capex,
    }


def eng_exp0004_fixed_wireless(fips, hh, params, rng):
    """EXP-0004: fixed wireless vs fiber. LOS over observed terrain grid; tower
    sites at 3 largest building clusters; costs assumed."""
    ex, ey, grid = _terrain(fips)
    pts = hh[["x", "y"]].to_numpy()
    # tower sites: top-3 building-density clusters (coarse grid histogram)
    H, xe, ye = np.histogram2d(pts[:, 0], pts[:, 1], bins=24)
    top = np.dstack(np.unravel_index(np.argsort(H.ravel())[::-1], H.shape))[0]
    sites, taken = [], set()
    for i, j in top:
        key = (i // 6, j // 6)  # enforce spacing
        if key in taken:
            continue
        taken.add(key)
        sites.append([(xe[i] + xe[i + 1]) / 2, (ye[j] + ye[j + 1]) / 2])
        if len(sites) == int(params.get("tower_sites", 3)):
            break
    unserved = rng.random(len(hh)) < 0.15  # 15% unserved, assumed
    range_m = 12_000  # 3.5 GHz fixed wireless radius, assumed
    covered = np.zeros(len(hh), bool)
    for s in sites:
        for i in np.where(unserved & ~covered)[0]:
            d = np.hypot(pts[i, 0] - s[0], pts[i, 1] - s[1])
            if d <= range_m and _los_clear(ex, ey, grid, s, pts[i]):
                covered[i] = True
    share = float(covered[unserved].mean()) if unserved.any() else float("nan")
    # cost model (assumed): towers + CPE vs fiber along minimum spanning approximation
    n_uns = int(unserved.sum())
    wireless_cost = len(sites) * 250_000 + int(covered.sum()) * 800
    fiber_miles = n_uns * 1.1  # 1.1 route-miles per rural household, assumed
    fiber_cost = fiber_miles * params.get("fiber_cost_per_mile_usd", 60000)
    return {
        "share_unserved_covered": share,
        "n_unserved": n_uns,
        "wireless_cost_usd": wireless_cost,
        "fiber_cost_usd": fiber_cost,
        "wireless_cost_share_of_fiber": wireless_cost / max(fiber_cost, 1),
        "tower_sites": sites,
    }


def eng_exp0005_robot(fips, params, rng):
    """EXP-0005: field robot under link dropout. Reduced-order mission sim."""
    area_acres = params.get("mission_area_acres", 160)
    vmax = params.get("speed_m_s", 1.5)
    drop_max = params.get("link_dropout_max_min", 10)
    row_m = 0.762  # 30-inch rows, assumed
    path_m = area_acres * 4046.86 / row_m
    missions = 200
    done = 0
    interventions_total = 0
    for _ in range(missions):
        drive_h = path_m / vmax / 3600
        if drive_h > 6.0:  # mission window
            continue
        n_drop = rng.poisson(drive_h * 1.5)  # 1.5 dropouts/hr, assumed
        durs = rng.uniform(0, drop_max, n_drop)
        # onboard autonomy handles dropouts <= max; failure prob per dropout assumed 3%
        fails = rng.random(n_drop) < 0.03
        interventions_total += int(fails.sum())
        if fails.sum() <= 2:
            done += 1
    return {
        "mission_completion_rate": 100 * done / missions,
        "interventions_per_mission": interventions_total / missions,
        "mission_path_km": path_m / 1000,
        "drive_hours": path_m / vmax / 3600,
    }


def eng_exp0007_datacenter(fips, hh, params, rng):
    """EXP-0007: 20 MW compute site rate impact. Parametric accounting model —
    ALL economics assumed; voltage/load-flow explicitly NOT modelled."""
    it_mw = params.get("it_load_mw", 20)
    pue = params.get("pue", 1.25)
    solar_mw = params.get("solar_mw", 0)
    storage_mwh = params.get("storage_mwh", 0)
    load_mw = it_mw * pue
    county_hh = len(hh) * 10  # scale synthetic sample to county, assumed factor 10
    base_bill_kwh = 12_000  # per household/yr, assumed
    rate = 0.12  # $/kWh, assumed
    rev_req = county_hh * base_bill_kwh * rate
    def scenario(onsite: bool):
        upgrade = 15e6 if not onsite else 8e6  # grid upgrade capex, assumed
        gen_capex = (solar_mw * 1.1e6 + storage_mwh * 0.4e6) if onsite else 0.0
        annual = (upgrade + gen_capex) * 0.08  # 8% CRF, assumed
        new_sales = load_mw * 8760 * 1000 * rate * 0.9  # revenue from the site
        d_rev = annual - new_sales * 0.15  # 15% of site revenue offsets rates, assumed
        return 100 * d_rev / rev_req
    grid_only = scenario(False)
    with_onsite = scenario(True)
    return {
        "lowest_quintile_rate_change_pct_grid_only": grid_only,
        "lowest_quintile_rate_change_pct_with_onsite": with_onsite,
        "voltage_violations": "NOT MODELLED — requires load-flow engine; success criterion indeterminate on this channel",
        "provenance_floor": "assumed",
    }


def eng_exp0008_microgrid(fips, params, rng):
    """EXP-0008: hospital+school microgrid over historical winters. Solar resource
    proxied from observed Open-Meteo precip/snow days (no radiation column) — tagged."""
    clim = _climate(fips)
    clim["year"] = clim["date"].dt.year
    solar_mw = params.get("solar_mw", 1.5)
    storage_mwh = params.get("storage_mwh", 6)
    gen_mw = params.get("backup_generator_mw", 0.5)
    crit_mw = 0.3  # hospital+school critical load, assumed
    served_events, total_events = 0, 0
    for y, grp in clim.groupby("year"):
        winter = grp[grp["date"].dt.month.isin([12, 1, 2])].reset_index(drop=True)
        if len(winter) < 72:
            continue
        start = int(rng.integers(0, len(winter) - 3))
        window = winter.iloc[start:start + 3]
        # daily solar: clear day -> 4.5 kWh/kW winter at this latitude assumed;
        # precip/snow day -> 25% of clear
        clear = (window["precipitation_sum"] < 1.0) & (window["snowfall_sum"] < 1.0)
        daily_kwh = np.where(clear, 1.0, 0.25) * solar_mw * 1000 * 4.5
        need = crit_mw * 1000 * 24 - gen_mw * 1000 * 24
        soc = storage_mwh * 1000
        ok = True
        for d in daily_kwh:
            soc = min(soc + d, storage_mwh * 1000)
            if need > 0:
                soc -= need
                if soc < 0:
                    ok = False
                    break
        served_events += ok
        total_events += 1
    return {
        "winters_served_72_of_72": int(served_events),
        "winters_simulated": int(total_events),
        "share_served": served_events / max(total_events, 1),
        "solar_basis": "derived from observed Open-Meteo precip/snow; clear-day yield assumed",
    }


def eng_exp0009_edge(fips, params, rng):
    """EXP-0009: edge node availability during backhaul outages. Outage process assumed."""
    it_kw = params.get("it_load_kw", 10)
    batt_kwh = params.get("battery_kwh", 40)
    autonomy_h = batt_kwh / it_kw
    years = 3
    covered, total = 0, 0
    for _ in range(years):
        n_out = rng.poisson(6)  # 6 backhaul outages/yr, assumed
        durs = rng.lognormal(mean=np.log(1.5), sigma=1.0, size=n_out)  # hours, assumed
        covered += int((durs <= autonomy_h).sum())
        total += n_out
    return {
        "availability_during_outages_pct": 100 * covered / max(total, 1),
        "battery_autonomy_hours": autonomy_h,
        "outages_simulated": int(total),
    }


def eng_exp0010_hypothetical(fips, params, rng):
    """EXP-0010: conditional statement only — hypothetical chemistry, never promoted."""
    dens = params.get("energy_density_multiplier", 2.0)
    cost_m = params.get("cost_multiplier", 0.5)
    # county-wide microgrid: 5 MWh storage nodes x 6, assumed topology
    storage_mwh = 30
    npc_micro = storage_mwh * 400_000 * cost_m / dens * 1.0  # effective $/kWh 400 assumed base
    feeder_miles = 40  # assumed upgrade path length; power-lines layer lacks feeder voltage classes
    npc_feeder = feeder_miles * 250_000  # $/mile assumed
    return {
        "conditional": True,
        "npc_microgrid_usd": npc_micro,
        "npc_feeder_upgrade_usd": npc_feeder,
        "statement": (f"IF a chemistry with {dens}x density at {cost_m}x cost existed, the modelled "
                      f"microgrid NPC (${npc_micro/1e6:.1f}M) would be "
                      f"{'below' if npc_micro < npc_feeder else 'above'} the feeder upgrade path "
                      f"(${npc_feeder/1e6:.1f}M). Says nothing about whether such a device can be built."),
    }
