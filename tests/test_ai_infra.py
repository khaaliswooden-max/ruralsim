"""Offline tests for the AI-infrastructure engine (tools/engines/ai_infra). No network access:
a toy county with hand-made OSM power features in a local metric frame."""
import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from shapely.geometry import box

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
