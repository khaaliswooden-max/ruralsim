# RuralSim experiment batch report — ten seed cards, 20 seeds each

Run 2026-11-12, mode promotion-eligible (20 seeds) — BUT promotion additionally requires
full-physics confirmation; all engines here are reduced-order with assumed device
parameters, so every card's provenance floor is `assumed` or `hypothetical` and no result
below is a finding. Negative and null results are reported with the same prominence as wins.
Synthetic households only; no real persons; political variables excluded at load time (D-007).

## EXP-0001 — EMS dispatch re-optimization

County: McDowell County WV (54047) · Fidelity B_pilot_3d · provenance floor **assumed**
Pre-stated criterion: p90 EMS response falls >=15%, 90% interval excludes zero
Effect (90% interval across 20 seeds): **[-24.4, 12.5]** · hard constraints all seeds: **FAIL**
Primary metric (seed means): p90_baseline_min = 51.62, p90_intervention_min = 49.60, change_pct = -3.87, n_calls = 301.95, unreachable_calls_baseline = 3.25, unreachable_calls_intervention = 4.00

RQLI distribution (mean of per-seed statistics):

| | p10 | p50 | p90 | mean | worst-off decile |
|---|---|---|---|---|---|
| baseline | 0.0134 | 0.1102 | 0.8095 | 0.2462 | 0.0087 |
| intervention | 0.0143 | 0.1129 | 0.8112 | 0.2617 | 0.0091 |

Constraints: no_loss_of_essential_service FAIL; protect_lowest_income_quintile PASS; water_within_recharge PASS; no_displacement PASS; worst_off_decile_must_gain FAIL; political_variables_excluded PASS
- calls on disconnected OSM graph islands are excluded from p90, counted here

## EXP-0002 — Telehealth triage routing under real connectivity

County: Wilcox County AL (01131) · Fidelity B_pilot_3d · provenance floor **assumed**
Pre-stated criterion: mean travel minutes fall >=30%; excluded share reported by income quintile
Effect (90% interval across 20 seeds): **[-31.8, -31.1]** · hard constraints all seeds: **PASS**
Primary metric (seed means): baseline_mean = 40.25, intervention_mean = 27.60, change_pct = -31.43, unreachable_share_graph_disconnected = 0.02

RQLI distribution (mean of per-seed statistics):

| | p10 | p50 | p90 | mean | worst-off decile |
|---|---|---|---|---|---|
| baseline | 0.0073 | 0.0714 | 0.7894 | 0.2071 | 0.0051 |
| intervention | 0.0140 | 0.1090 | 0.8042 | 0.2450 | 0.0093 |

Constraints: no_loss_of_essential_service PASS; protect_lowest_income_quintile PASS; water_within_recharge PASS; no_displacement PASS; worst_off_decile_must_gain PASS; political_variables_excluded PASS
- bandwidth-excluded share by income quintile (seed0): {"1": 0.109, "2": 0.124, "3": 0.095, "4": 0.073, "5": 0.117}

## EXP-0003 — Feeder battery storage for outage ride-through

County: Chautauqua County KS (20019) · Fidelity B_pilot_3d · provenance floor **assumed**
Pre-stated criterion: hospital-feeder outage hours fall >=50%
Effect (90% interval across 20 seeds): **[-100.0, -99.8]** · hard constraints all seeds: **PASS**
Primary metric (seed means): outage_hours_per_year_baseline = 9.39, outage_hours_per_year_intervention = 0.03, change_pct = -99.81, longest_outage_hours_baseline = 12.29, battery_autonomy_hours = 40.00, capex_usd_assumed = 3,200,000.00

RQLI distribution (mean of per-seed statistics):

| | p10 | p50 | p90 | mean | worst-off decile |
|---|---|---|---|---|---|
| baseline | 0.0732 | 0.5313 | 0.8244 | 0.4628 | 0.0352 |
| intervention | 0.0732 | 0.5313 | 0.8244 | 0.4628 | 0.0352 |

Constraints: no_loss_of_essential_service PASS; protect_lowest_income_quintile PASS; water_within_recharge PASS; no_displacement PASS; worst_off_decile_must_gain PASS; political_variables_excluded PASS
- feeder-level metric; household RQLI outage channel unchanged (battery serves the hospital)

## EXP-0004 — Fixed wireless versus fiber for the last unserved households

County: Thurston County NE (31173) · Fidelity B_pilot_3d · provenance floor **assumed**
Pre-stated criterion: wireless reaches >=95% of unserved at <=50% of fiber capital cost
Effect (90% interval across 20 seeds): **[50.4, 60.1]** · hard constraints all seeds: **PASS**
Primary metric (seed means): share_unserved_covered = 0.55, n_unserved = 185.60, wireless_cost_usd = 831,560.00, fiber_cost_usd = 12,249,600.00, wireless_cost_share_of_fiber = 0.07

RQLI distribution (mean of per-seed statistics):

| | p10 | p50 | p90 | mean | worst-off decile |
|---|---|---|---|---|---|
| baseline | 0.0851 | 0.7667 | 0.8827 | 0.5608 | 0.0582 |
| intervention | 0.0851 | 0.7667 | 0.8827 | 0.5608 | 0.0582 |

Constraints: no_loss_of_essential_service PASS; protect_lowest_income_quintile PASS; water_within_recharge PASS; no_displacement PASS; worst_off_decile_must_gain PASS; political_variables_excluded PASS

## EXP-0005 — Autonomous field robot under connectivity loss

County: Chautauqua County KS (20019) · Fidelity B_pilot_3d · provenance floor **assumed**
Pre-stated criterion: mission completion >=90%
Effect (90% interval across 20 seeds): **[0.0, 0.0]** · hard constraints all seeds: **PASS**
Primary metric (seed means): mission_completion_rate = 0.00, interventions_per_mission = 0.00, mission_path_km = 849.73, drive_hours = 157.36

RQLI distribution (mean of per-seed statistics):

| | p10 | p50 | p90 | mean | worst-off decile |
|---|---|---|---|---|---|
| baseline | 0.0732 | 0.5313 | 0.8244 | 0.4628 | 0.0352 |
| intervention | 0.0732 | 0.5313 | 0.8244 | 0.4628 | 0.0352 |

Constraints: no_loss_of_essential_service PASS; protect_lowest_income_quintile PASS; water_within_recharge PASS; no_displacement PASS; worst_off_decile_must_gain PASS; political_variables_excluded PASS

## EXP-0006 — Drone delivery of medication in mountain terrain

County: McDowell County WV (54047) · Fidelity B_pilot_3d · provenance floor **assumed**
Pre-stated criterion: >=80% of households reachable within 30 min; grounded days reported
Effect (90% interval across 20 seeds): **[41.1, 44.7]** · hard constraints all seeds: **PASS**
Primary metric (seed means): road_baseline = 0.46, drone_intervention = 0.89, share_grounded_today = 0.05

RQLI distribution (mean of per-seed statistics):

| | p10 | p50 | p90 | mean | worst-off decile |
|---|---|---|---|---|---|
| baseline | 0.0134 | 0.1102 | 0.8095 | 0.2462 | 0.0087 |
| intervention | 0.0134 | 0.1102 | 0.8095 | 0.2462 | 0.0087 |

Constraints: no_loss_of_essential_service PASS; protect_lowest_income_quintile PASS; water_within_recharge PASS; no_displacement PASS; worst_off_decile_must_gain PASS; political_variables_excluded PASS

## EXP-0007 — 20 MW data center on a rural cooperative feeder

County: Wilcox County AL (01131) · Fidelity B_pilot_3d · provenance floor **assumed**
Pre-stated criterion: lowest-quintile rate change <=2% and zero voltage violations
Effect (90% interval across 20 seeds): **[16.7, 16.7]** · hard constraints all seeds: **FAIL**
Primary metric (seed means): lowest_quintile_rate_change_pct_grid_only = -23.77, lowest_quintile_rate_change_pct_with_onsite = 16.73

RQLI distribution (mean of per-seed statistics):

| | p10 | p50 | p90 | mean | worst-off decile |
|---|---|---|---|---|---|
| baseline | 0.0073 | 0.0714 | 0.7894 | 0.2071 | 0.0051 |
| intervention | 0.0073 | 0.0714 | 0.7894 | 0.2071 | 0.0051 |

Constraints: no_loss_of_essential_service PASS; protect_lowest_income_quintile FAIL; water_within_recharge PASS; no_displacement PASS; worst_off_decile_must_gain PASS; political_variables_excluded PASS

## EXP-0008 — Hospital and school microgrid

County: Teton County ID (16081) · Fidelity B_pilot_3d · provenance floor **assumed**
Pre-stated criterion: 72/72 h served in >=95% of simulated winters
Effect (90% interval across 20 seeds): **[100.0, 100.0]** · hard constraints all seeds: **PASS**
Primary metric (seed means): winters_served_72_of_72 = 30.00, winters_simulated = 30.00, share_served = 1.00

RQLI distribution (mean of per-seed statistics):

| | p10 | p50 | p90 | mean | worst-off decile |
|---|---|---|---|---|---|
| baseline | 0.2313 | 0.8558 | 0.9179 | 0.7408 | 0.1441 |
| intervention | 0.2313 | 0.8558 | 0.9179 | 0.7408 | 0.1441 |

Constraints: no_loss_of_essential_service PASS; protect_lowest_income_quintile PASS; water_within_recharge PASS; no_displacement PASS; worst_off_decile_must_gain PASS; political_variables_excluded PASS
- derived from observed Open-Meteo precip/snow; clear-day yield assumed

## EXP-0009 — Edge compute at the clinic for offline AI triage

County: Thurston County NE (31173) · Fidelity B_pilot_3d · provenance floor **assumed**
Pre-stated criterion: availability >=99% during backhaul outages
Effect (90% interval across 20 seeds): **[74.8, 94.7]** · hard constraints all seeds: **PASS**
Primary metric (seed means): availability_during_outages_pct = 84.82, battery_autonomy_hours = 4.00, outages_simulated = 17.50

RQLI distribution (mean of per-seed statistics):

| | p10 | p50 | p90 | mean | worst-off decile |
|---|---|---|---|---|---|
| baseline | 0.0851 | 0.7667 | 0.8827 | 0.5608 | 0.0582 |
| intervention | 0.0851 | 0.7667 | 0.8827 | 0.5608 | 0.0582 |

Constraints: no_loss_of_essential_service PASS; protect_lowest_income_quintile PASS; water_within_recharge PASS; no_displacement PASS; worst_off_decile_must_gain PASS; political_variables_excluded PASS

## EXP-0010 — Hypothetical storage chemistry

County: Chautauqua County KS (20019) · Fidelity B_pilot_3d · provenance floor **hypothetical**
Pre-stated criterion: conditional statement only; no pass/fail
Effect (90% interval across 20 seeds): **n/a (conditional card)** · hard constraints all seeds: **PASS**
Primary metric (seed means): conditional = 1.00, npc_microgrid_usd = 3,000,000.00, npc_feeder_upgrade_usd = 10,000,000.00

RQLI distribution (mean of per-seed statistics):

| | p10 | p50 | p90 | mean | worst-off decile |
|---|---|---|---|---|---|
| baseline | 0.0732 | 0.5313 | 0.8244 | 0.4628 | 0.0352 |
| intervention | 0.0732 | 0.5313 | 0.8244 | 0.4628 | 0.0352 |

Constraints: no_loss_of_essential_service PASS; protect_lowest_income_quintile PASS; water_within_recharge PASS; no_displacement PASS; worst_off_decile_must_gain PASS; political_variables_excluded PASS
- IF a chemistry with 2.0x density at 0.5x cost existed, the modelled microgrid NPC ($3.0M) would be below the feeder upgrade path ($10.0M). Says nothing about whether such a device can be built.

