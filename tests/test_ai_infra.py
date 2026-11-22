"""Offline tests for the AI-infrastructure engine (tools/engines/ai_infra). No network access:
a toy county with hand-made OSM power features in a local metric frame."""
import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from shapely.geometry import box

# The engine runs in its own environment (tools/engines/ai_infra/requirements.txt, D-103):
# pandapower requires pandas~=2.3, the build pipeline pins pandas 3. In a pipeline-only
# environment this module is skipped with that reason instead of failing at import.
pytest.importorskip("pandapower", reason="AI-infra engine env not installed: "
                    "pip install -r tools/engines/ai_infra/requirements.txt (separate venv, D-103)")

from tools.engines.ai_infra import gate, network, power_flow, rate_impact

HERE = Path(__file__).resolve().parents[1] / "tools" / "engines" / "ai_infra" / "params"
CFG = yaml.safe_load((HERE / "assumed.yaml").read_text())
ACT = json.loads((HERE / "activsg_distributions.json").read_text())
ID = lambda x, y: (x, y)  # features are already in metres  # noqa: E731
COUNTY = box(0, 0, 20000, 20000)


def line(coords, kv, oid):
    return {"type": "Feature", "properties": {"power": "line", "voltage": kv, "osm_id": oid},
            "geometry": {"type": "LineString", "coordinates": coords}}


def sub(x, y, kv, oid, operator=None):
    s = 50
    ring = [[x - s, y - s], [x + s, y - s], [x + s, y + s], [x - s, y + s], [x - s, y - s]]
    return {"type": "Feature", "properties": {"power": "substation", "voltage": kv, "osm_id": oid, "operator": operator},
            "geometry": {"type": "LineString", "coordinates": ring}}


def toy():
    """A 115 kV line from outside the county (x=-5 km) to a 115/46 kV substation at (10, 10) km,
    a 46 kV line on to a 46 kV substation at (15, 10) km, and a 46 kV spur that T-taps it."""
    return [
        sub(10000, 10000, "115000;46000", 1),
        sub(15000, 10000, "46000", 2, operator="Example Cloud LLC"),
        line([[-5000, 10000], [10000, 10000]], "115000", 10),
        line([[10000, 10000], [15000, 10000]], "46000", 11),
        line([[12500, 10000], [12500, 14000]], "46000", 12),   # tees into line 11 mid-way
    ]


def test_parse_kv():
    assert network.parse_kv("345000;138000") == [345.0, 138.0]
    assert network.parse_kv("0") == [] and network.parse_kv(None) == []


def test_network_snaps_taps_and_supplies():
    n = network.build(toy(), ID, COUNTY, CFG["network"])
    s = n.summary
    assert s["substations"] == 2 and s["t_taps"] == 1
    assert {t["kv_hv"] for t in n.trafos} == {115.0}
    assert all(b["supplied"] for b in n.buses)          # fed through the out-of-county end
    assert s["in_county_line_km_by_kv"]["115.0"] == pytest.approx(10.0, rel=0.01)


def test_mask_drops_owner_substation_and_its_lines():
    feats, masked = network.apply_mask(toy(), ID, owner_terms=["example cloud"])
    assert [m["osm_id"] for m in masked] == [2]
    n = network.build(feats, ID, COUNTY, CFG["network"], masked_sub_ids=[2])
    assert 2 not in {s["osm_id"] for s in n.substations}
    assert not any(l["osm_id"] == 11 and n.buses[l["t"]]["x"] > 14000 for l in n.lines)  # segment ending at sub 2


def test_power_flow_seeds_differ_and_big_load_breaks_weak_grid():
    n = network.build(toy(), ID, COUNTY, CFG["network"])
    small, big = [], []
    for seed in range(5):
        small.append(power_flow.run(n, (11000, 11000), 5.0, 0.98, 2.0, 0.95, CFG, ACT, "AL",
                                    np.random.default_rng(seed)))
        big.append(power_flow.run(n, (16000, 10000), 45.0, 0.98, 2.0, 0.95, CFG, ACT, "AL",
                                  np.random.default_rng(seed)))
    assert all(r["status"] == "computed" for r in small + big)
    loads = [r["max_loading_pct"] for r in big if isinstance(r["max_loading_pct"], float)]
    assert len(set(round(x, 6) for x in loads)) > 1        # assumed inputs are sampled per seed
    assert max(loads) > 100                                # 45 MW on a 46 kV spur overloads
    assert all(any(u["type"] == "substation" for u in r["required_upgrades"]) for r in big)


def test_interconnection_class_thresholds():
    rng = np.random.default_rng(0)
    assert power_flow.interconnection_class(2, CFG, rng) == "distribution"
    assert power_flow.interconnection_class(1000, CFG, rng) == "ehv"


def _cand(transmission_owner):
    return [{"utility_number": 1, "utility_name": "Example EMC", "ownership": "Cooperative", "rate_basis": "residential",
             "transmission_owner": transmission_owner, "residential_revenue_usd": 30e6, "residential_mwh": 2e5,
             "residential_customers": 15000, "total_mwh": 3e5, "residential_avg_rate_usd_per_kwh": 0.15,
             "residential_kwh_per_customer": 13300, "industrial_avg_rate_usd_per_kwh": 0.08},
            {"utility_number": 2, "utility_name": "Tiny Coop", "ownership": "Cooperative", "short_form": True,
             "transmission_owner": False, "data": "missing: short form"},
            {"utility_number": 3, "utility_name": "Short Form EMC", "ownership": "Cooperative", "short_form": True,
             "transmission_owner": False, "rate_basis": "all_sectors_stand_in", "all_sector_revenue_usd": 20e6,
             "all_sector_mwh": 1e5, "all_sector_customers": 8000, "avg_rate_all_sectors_usd_per_kwh": 0.2,
             "kwh_per_customer_all_sectors": 12500}]


def test_rate_allocations_ordered_with_common_draws_and_missing_is_indeterminate():
    row = {"mean_q1": 8000.0, "mean_q1_moe": 1500.0}
    ups = [{"type": "substation", "subtype": "new customer substation", "kv": 115, "mva": 30},
           {"type": "line_new", "kv": 115, "km": 10}]
    site = {"peak_mw_net": 25, "grid_mwh": 150000}
    r = {a: rate_impact.run(_cand(True), ups, site, {}, a, row, CFG, np.random.default_rng(7))
         for a in rate_impact.ALLOCATIONS}
    d = {a: r[a]["per_utility"][0]["lowest_quintile_rate_change_pct"] for a in r}
    assert d["direct_assignment"] <= d["large_load_tariff"] <= d["socialized"]
    assert r["socialized"]["per_utility"][1]["status"] == "indeterminate"
    sf = r["socialized"]["per_utility"][2]
    assert sf["status"] == "computed" and sf["rate_basis"] == "all_sectors_stand_in"
    x = r["socialized"]["per_utility"][0]
    inc = r["socialized"]["q1_mean_income_usd"]
    assert 2000 <= inc <= 14000                                  # ACS mean +/- a few sd, floored
    assert x["lowest_quintile_energy_cost_share_change_pp"] == pytest.approx(
        100 * x["lowest_quintile_bill_change_usd_per_yr"] / inc)
    assert r["socialized"]["local_tax_effect"] == "not_modelled"


def test_income_missing_is_indeterminate():
    assert rate_impact.q1_income(None, np.random.default_rng(0)) is None
    assert rate_impact.q1_income({"mean_q1": float("nan"), "mean_q1_moe": 1.0}, np.random.default_rng(0)) is None


def test_ownership_from_name():
    assert rate_impact._ownership_from_name("Black Warrior Elec Member Corp") == "Cooperative"
    assert rate_impact._ownership_from_name("City of Pender - (NE)") == "Municipal"
    assert rate_impact._ownership_from_name("Burt County Public Power Dist") == "Political Subdivision"


def test_gate_refuses_backtest_sites_and_candidates():
    with pytest.raises(gate.Refused):
        gate.check("40097", None, lambda y: True)          # Mayes OK, scored site
    with pytest.raises(gate.Refused):
        gate.check("19155", None, lambda y: True)          # Pottawattamie, brief candidate
    with pytest.raises(gate.Refused, match="T0-1"):
        gate.check("40097", "BT-01", lambda y: False)       # registered, but no 2006 EIA tables
    assert gate.check("01131", None, lambda y: True) is None


def test_judge_bar_is_inclusive_at_exactly_ten_percent():
    from tools.engines.ai_infra import run
    pf = {"status_counts": {"computed": 20}, "share_seeds_any_voltage_violation": 0.0,
          "share_seeds_voltage_indeterminate": 0.0, "share_seeds_any_thermal_overload": 2 / 20}
    rec = {"county": {"fips5": "00000"}, "site": {"note": "x"},
           "scenarios": {"s": {"summary": {"power_flow": pf, "rate_impact": {}}}}}
    card = {"criterion": {"grid_clean_seed_share": 0.9, "rate_change_pct_max": 2.0}}
    misses, passes = run.judge(card, rec)
    assert not misses and len(passes) == 2


def test_site_larger_than_utility_is_outside_validity():
    row = {"mean_q1": 8000.0, "mean_q1_moe": 1500.0}
    site = {"peak_mw_net": 25, "grid_mwh": 150000}          # 1.5x the stand-in utility's 1e5 MWh
    r = rate_impact.run(_cand(False), [], site, {}, "socialized", row, CFG, np.random.default_rng(1))
    sf = r["per_utility"][2]
    assert sf["site_share_of_utility_sales"] == pytest.approx(1.5) and sf["outside_validity"]
    big = r["per_utility"][0]                               # 1.5e5 / 3e5 = 0.5 > 0.25
    assert big["site_share_of_utility_sales"] == pytest.approx(0.5) and big["outside_validity"]


# --- cooling_water (D-106) -------------------------------------------------------------
import pandas as pd  # noqa: E402

from tools.engines.ai_infra import cooling_water  # noqa: E402


def _weather(tw, tdb, days=3653):
    return pd.DataFrame({"t2mwet_c": np.full(days, tw), "t2m_c": np.full(days, tdb)})


def test_wue_by_design_and_ordering():
    w = _weather(20.0, 27.0)
    res = {}
    for ct in cooling_water.COOLING_TYPES:
        res[ct] = cooling_water.run(w, 20.0, 1.3, ct, None, (None, None), {}, CFG, np.random.default_rng(3))
    assert 1.2 < res["evaporative"]["wue_l_per_it_kwh"] < 3.0       # US data-center average is ~1.8 L/kWh
    assert 0 < res["adiabatic_hybrid"]["wue_l_per_it_kwh"] < res["evaporative"]["wue_l_per_it_kwh"]
    assert res["dry"]["annual_withdrawal_m3"] == 0 and res["dry"]["pue_effective_annual"] > 1.3
    assert res["evaporative"]["annual_consumption_m3"] < res["evaporative"]["annual_withdrawal_m3"]


def test_gauge_pick_and_zero_low_flow():
    g = pd.DataFrame({"site_no": ["a", "b", "c"], "station_nm": ["creek", "river", "far"],
                      "dec_lat_va": [32.0, 32.3, 34.0], "dec_long_va": [-87.0, -87.0, -87.0],
                      "drain_area_sqmi": [50.0, 20000.0, 90000.0], "mean_flow_cfs": [40.0, 30000.0, 1e5],
                      "p10_min_cfs": [0.0, 4000.0, 9e4], "fips5": ["x", "y", "z"]})
    src, near = cooling_water.pick_gauges(g, 32.0, -87.0, 50)
    assert src["station_nm"] == "river" and near["station_nm"] == "creek"   # 'far' is outside the radius
    out = cooling_water.run(_weather(20.0, 27.0), 20.0, 1.3, "evaporative", None, (near, near), {}, CFG,
                            np.random.default_rng(0))
    assert out["share_of_source_low_flow_peak_day"] == float("inf")         # dry creek: any withdrawal fails


# --- flood (D-107) -----------------------------------------------------------------------
from shapely import wkb as _wkb  # noqa: E402
from shapely.geometry import Polygon as _Poly  # noqa: E402

from tools.engines.ai_infra import flood  # noqa: E402


def _zones():
    sq = lambda x0, y0, s: _Poly([(x0, y0), (x0 + s, y0), (x0 + s, y0 + s), (x0, y0 + s)])  # noqa: E731
    return pd.DataFrame({"fld_zone": ["AE", "X"], "zone_subty": [None, "0.2 PCT ANNUAL CHANCE FLOOD HAZARD"],
                         "sfha_tf": ["T", "F"], "static_bfe": [-9999.0, -9999.0], "depth": [None, None],
                         "dfirm_id": ["T1", "T1"], "area_m2": [1e6, 1e6],
                         "geometry": [_wkb.dumps(sq(0, 0, 1000)), _wkb.dumps(sq(1000, 0, 1000))]})


def test_flood_point_in_zone_share_and_status_rules():
    st = {"status": "effective", "prelim_coverage": 0.5, "prelim_issue_date_max": "2026-01-01", "pending_coverage": 0.0}
    near = flood.prepare(_zones(), ID, (1000, 500), 3000)
    o = flood.run(st, near, (1000.0, 500.0), CFG, np.random.default_rng(0))   # site on the AE / X boundary
    assert 0.3 < o["footprint_share_sfha"] < 0.7 and o["footprint_share_sfha"] + o["footprint_share_x_shaded"] > 0.95
    assert any("about to change" in f for f in o["flags"])
    far = flood.run(st, flood.prepare(_zones(), ID, (2500, 2500), 3000), (2500.0, 2500.0), CFG, np.random.default_rng(0))
    assert far["site_point_zone"].startswith("X unshaded") and far["footprint_share_sfha"] == 0
    none = flood.run({"status": "none"}, [], (0, 0), CFG, np.random.default_rng(0))
    assert none["status"] == "indeterminate" and "not 'no flood risk'" in none["reason"]
    part = flood.run({"status": "partial"}, near, (2500.0, 2500.0), CFG, np.random.default_rng(0))
    assert part["status"] == "indeterminate"                      # outside drawn zones in a partly mapped county


# --- fiber (D-108) -----------------------------------------------------------------------
import h3 as _h3  # noqa: E402

from tools.engines.ai_infra import fiber  # noqa: E402


def test_fiber_site_hex_nearest_and_county():
    site = _h3.latlng_to_cell(32.0, -87.3, 8)
    ring2 = sorted(_h3.grid_ring(site, 3))[0]                       # ~2.5-3 km away
    rows = pd.DataFrame({"h3_res8_id": [ring2, ring2], "fips5": ["01131", "01099"], "state": ["AL", "AL"],
                         "fiber_locations": [5, 7], "residential": [5, 7], "business": [1, 1], "providers": [1, 2],
                         "max_down_mbps": [1000.0, 2000.0], "max_up_mbps": [1000.0, 2000.0], "locations_ge_1000_mbps": [5, 7]})
    hx = fiber.hex_table(rows)
    assert int(hx.loc[ring2].fiber_locations) == 12 and int(hx.loc[ring2].providers) == 2   # county parts summed
    o = fiber.run(32.0, -87.3, hx, {"fiber_providers": 2, "brand_names": "A; B", "fiber_locations": 12,
                                    "hexes_with_fiber": 1}, 30)
    assert not o["fiber_in_site_hex"] and 2.0 < o["nearest_fiber_hex_km"] < 4.0
    assert o["middle_mile"].startswith("not observed")
    lat, lon = _h3.cell_to_latlng(ring2)
    assert fiber.run(lat, lon, hx, None, 30)["nearest_fiber_hex_km"] == 0.0
    assert fiber.run(40.0, -100.0, hx, None, 30)["nearest_fiber_hex_km"] is None   # nothing within radius
