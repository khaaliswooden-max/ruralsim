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
    return [{"utility_number": 1, "utility_name": "Example EMC", "ownership": "Cooperative",
             "transmission_owner": transmission_owner, "residential_revenue_usd": 30e6, "residential_mwh": 2e5,
             "residential_customers": 15000, "total_mwh": 3e5, "residential_avg_rate_usd_per_kwh": 0.15,
             "residential_kwh_per_customer": 13300, "industrial_avg_rate_usd_per_kwh": 0.08},
            {"utility_number": 2, "utility_name": "Tiny Coop", "ownership": "Cooperative", "short_form": True,
             "transmission_owner": False, "data": "missing: short form"}]


def test_rate_allocations_ordered_with_common_draws_and_missing_is_indeterminate():
    row = {"median_hh_income_2023_ci90_lo": 40000, "median_hh_income_2023_ci90_hi": 42000,
           "poverty_rate_2023_ci90_lo": 15, "poverty_rate_2023_ci90_hi": 17}
    ups = [{"type": "substation", "subtype": "new customer substation", "kv": 115, "mva": 30},
           {"type": "line_new", "kv": 115, "km": 10}]
    site = {"peak_mw_net": 25, "grid_mwh": 150000}
    r = {a: rate_impact.run(_cand(True), ups, site, {}, a, row, CFG, np.random.default_rng(7))
         for a in rate_impact.ALLOCATIONS}
    d = {a: r[a]["per_utility"][0]["lowest_quintile_rate_change_pct"] for a in r}
    assert d["direct_assignment"] <= d["large_load_tariff"] <= d["socialized"]
    assert r["socialized"]["per_utility"][1]["status"] == "indeterminate"
    assert r["socialized"]["local_tax_effect"] == "not_modelled"


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
