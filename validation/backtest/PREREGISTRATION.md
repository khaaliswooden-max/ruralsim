# Back-test pre-registration: AI-infrastructure engine against built rural data centers

Rollout step 3 · version 1.0 · registered 2026-11-21 · decisions **D-200**, **D-201**
Status: **registered, no runs.** The engine (rollout step 2) does not exist yet.

This document fixes, before any run: which sites, what the engine is allowed to know, which engine outputs are compared with which observed quantities, the pass bar for each comparison, and what passing allows us to say. It must merge before the step-2 engine runs on any site listed here. Once the first back-test run is recorded, nothing in it changes. A later version can only govern new, held-out sites (§8).

## 1. What this can and cannot do

- Every RuralSim result is **SPECULATIVE** by default. A back-test is the only route by which a result can be graded **PLAUSIBLE**, and only through a method published before the run. This is that method.
- Passing grades an engine channel PLAUSIBLE **for the back-test sites, for that channel only**. It does not make public screening runs anything other than SPECULATIVE. It does not make any output a finding, "validated", or "decision-grade". Those words are never used.
- Failing is reported first and as prominently as passing (§10).

## 2. Sites

| ID | County (FIPS) | RUCC 2023 | Operator | Serving utility (EIA id) | T0 | E | World |
|---|---|---|---|---|---|---|---|
| BT-01 | Mayes OK (40097) | 6 | Google | Grand River Dam Authority (7490), state agency | 2007 | 2011 | published |
| BT-02 | Jackson AL (01071) | 6 | Google | TVA (18642); retail seller PENDING | 2015 | 2018 or 2019 | published |
| BT-03 | Wasco OR (41065) | 7 | Google | Northern Wasco County PUD (13788) | 2005 | 2006 | ~2026-11-23 |
| BT-04 | Grant WA (53025) | 5 | Microsoft (+ Yahoo) | PUD No 2 of Grant County (14624) | 2006 | 2007 | ~2026-11-23 |
| BT-C1 | Licking OH (39089) | 1 | New Albany project PENDING | Ohio Power / AEP Ohio (14006) | PENDING | PENDING | published (contrast only) |

T0 is the year of first public announcement and E the first year of operation. Fact sheets and every source: `SITES.md`. Machine-readable inputs and observations: `sites.yaml`. Derived observed values: `observed/observed_values.json`.

## 3. Why these sites

1. **Rural by both vintages.** The four scored sites are nonmetro in RUCC 2023 *and* in the vintage nearest their T0 (Mayes 6/6, Jackson 6/6, Wasco 6/7, Grant 4/5). Six of the eleven candidates are metro under RUCC 2023 (Pottawattamie, Caldwell, Berkeley, Newton, Montgomery, Licking). Crook OR moved from 6 to 3 in 2023 and is held back rather than judged on a boundary.
2. **Public power.** All four are served by a public or small utility: GRDA (state agency), TVA and its co-op distributors, and two people's/public utility districts. No scored site is an investor-owned utility. The brief prefers rural co-ops. Only Jackson involves a co-op, and that is unconfirmed. Newton GA (Walton EMC) is the strongest co-op case but is metro, so it is the first alternate contrast.
3. **A public record on outcomes.** Each scored site has at least two of: an EIA-861 load signal, a documented substation or transmission build, a residential price series, a water-use record obtained through public records.
4. **Contrast.** Licking OH, an IOU under PUCO's 2025 data-center tariff, is run the same way and reported separately. It never counts toward a grade.

Known cost of this choice: three of four sites are 2005–2011 builds of tens of MW. Today's AI campuses are hundreds of MW. A pass here says nothing about the engine at that scale (§9).

## 4. "Before": what the engine may know

### 4.1 Information set
For each site the engine receives only the `before:` block of `sites.yaml`. That block may hold only facts **published on or before T0**, each with a dated source:
- location, county, and the serving utility as named at announcement
- announced investment, acreage, floor area, jobs, and announced MW where any were announced
- the stated water source and cooling plan, where stated

**This is a conditional back-test (D-201).** The step-2 engine takes the site's load as an input (`it_load_mw`). It does not predict load. So the back-test does not ask whether the engine can size a data center from a press release. It asks: given the load that actually arrived, did the engine get the grid build, the rate effect and the water right? Two design attributes of the built plant are therefore inputs, taken from the record whatever their date:
- **Load.** The facility average load is set to the observed load increment `L_obs` (§6.1). Per seed, `it_load_mw = L_obs / (pue × load_factor)`, with `pue` and `load_factor` drawn from the engine's own assumed ranges. So the facility average equals `L_obs` in every seed. For a W1 observation in year Y, `L_obs` is the same increment computed with Y in place of E+1..E+2 (§6.4).
- **Cooling type.** Taken from the record if stated (any date). Otherwise every engine value (`dry`, `adiabatic_hybrid`, `evaporative`) is run, and W1 passes only if it passes for all of them. Water use is the measured outcome; cooling type is a design fact.

Never allowed as input: any grid-build, rate, tariff or water-volume quantity in an `observed:` block; any cost-allocation or tariff fact dated after T0 (§6.3 says how cost allocation is set).

### 4.2 World layers: vintage and masking
Published worlds are current (OSM 2026, EIA-860/861 2024, Overture 2026-10, CDL 2025). They contain the data centers themselves and their interconnections. Each back-test run must therefore:
1. use **EIA-860 and EIA-861 tables of year T0−1** in place of the 2024 tables;
2. **mask the site:** remove buildings inside the site parcel. Remove every OSM `power=substation` within 2 km of the parcel, and every one anywhere in the county whose `operator` or `name` tag names the data-center owner or its holding company (e.g. Design LLC). Remove every `power=line` or `power=minor_line` ending at a removed substation. A feature stays if a dated source shows it existed before T0. Transmission lines longer than 10 km that pass within the 2 km buffer without ending there also stay. Every masked feature is listed in the run record;
3. use Census/ACS values of the vintage nearest to and not after T0 for the synthetic population;
4. keep terrain, hydrology, climate normals (1991–2020) and land tenure as published. Their post-T0 change is small against the site. The climate normals overlap the outcome years, and this is recorded.

If the engine cannot apply 4.2.1–4.2.3, the affected channel is **NOT SCORED** for that run (§11).

### 4.3 Frozen engine
- One tagged commit of the engine and its parameter files, named in the run record before the first site runs.
- No parameter may be set, fitted or tuned using any back-test site. A change to the engine after the first back-test run voids grading for every channel it touches. A rerun on these sites is then reported but cannot raise a grade.
- 20 seeds per site. **Scoring uses the p50 (median) across seeds**, not the band: the observed value need not fall inside p10–p90. The band is reported. A p50 pass with the observed value outside p10–p90 is recorded as "pass, interval miss" and does not change the grade.

## 5. Engine outputs compared

Mapped to step 2's `output_schema` in `specs/ai_infra_engine.yaml` (PR #50, D-100). **Only the outputs in this table are compared with the record.** Everything else the engine emits is recorded in the results file and not scored, including `interconnection_voltage_class_kv`, `nearest_substation_of_class`, fiber, flood and the hard constraints. Step 2 does not model the construction timeline, so T1 is never scored against this engine (§6.5).

| Engine output (step 2 name) | Derived quantity | Used by |
|---|---|---|
| `power_flow.required_upgrades` (type, kV, km or MVA) | per seed: `new_substation` = any upgrade of type substation (new or expansion) | G1 |
| `power_flow.new_line_km` with `required_upgrades` kV | per seed: `new_line` = new_line_km > 0 at ≥ 69 kV | G1 |
| `rate_impact.lowest_quintile_rate_change_pct`, for the rate utility named in `sites.yaml` | p50, in % | R1 |
| `cooling_water.annual_withdrawal_m3` | p50 × 264.172 = gallons per year | W1 |

A module that returns `indeterminate` or `blocked` makes its comparison **NOT SCORED** for that site. Each record must carry `backtest: {site_id, preregistration_commit}` and the engine commit.

## 6. Comparisons and pass bars

Every comparison scores **PASS**, **MISS** or **NOT SCORED**. NOT SCORED applies when the observation or a required input is PENDING at run time. It is never counted as a pass. Where E is uncertain (Jackson: 2018 or 2019), the comparison is computed for each candidate year and **passes only if it passes for all of them**.

### 6.1 L_obs · Site load (input, not graded)
- **Value:** `L_obs = (mean retail MWh of the serving utility over E+1..E+2 − mean over T0−3..T0−1) / 8760`, in average MW, from EIA-861 Part A. This is the utility's whole load change. Other industrial growth in the window is included and not removed.
- It is the load **input** for the conditional run (§4.1). It is not compared with anything, because the engine does not predict load.
- It is available only where the serving utility is the site's retail seller. Jackson has it only if the retail seller is shown to be NAEC; TVA's Alabama direct-serve total is dominated by other customers. A site without `L_obs` cannot run, and every channel is NOT SCORED there.

### 6.2 G1 · Grid build
- **Observed:** whether a new substation, or a new or rebuilt transmission line of 69 kV or more, was built to serve the site between T0 and E+2. This is two booleans, each from a dated source.
- **Prediction:** each boolean is "yes" when at least 50% of seeds say yes.
- **Bar:** PASS when both booleans match. When only one is documented, that one must match and the other is NOT SCORED.

### 6.3 R1 · Residential rate
- **Rate utility:** the site's serving utility where it has residential retail (NWCPUD, Grant PUD). Otherwise, the distributor whose territory contains the site and which buys from the serving utility, documented before the run (Jackson: NAEC, territory to verify; Mayes: PENDING). If it cannot be documented, R1 is NOT SCORED.
- **Observed:** two estimates of the site-attributable change, in percentage points, between T0−1 and E+5:
  - peer: `100·[(p_u(E+5)/p_u(T0−1) − 1) − (p_peer(E+5)/p_peer(T0−1) − 1)]`, where `p` is bundled residential revenue ÷ sales and the peers are same-state utilities of the same EIA ownership class reporting residential sales in both years (a balanced panel);
  - state: the same with the all-utility state average in place of the peers.
- **Prediction:** the p50 of `lowest_quintile_rate_change_pct` for the rate utility. The engine reports a rate change, and the observed value is an average residential price change. Under a single residential tariff the two coincide. Where they differ, the comparison is still made and the difference is listed in §9.
- **Cost allocation:** step 2 runs `direct_assignment`, `large_load_tariff` and `socialized` unless one is fixed. One is fixed only if a tariff, contract or board record **dated on or before E** shows how the site's grid costs were allocated. Otherwise R1 passes only if it passes under all three.
- **Bar:** PASS if the prediction lies in `[min(peer, state) − 5, max(peer, state) + 5]` pp. In addition, where both estimates have the same sign and both have magnitude ≥ 5 pp, the prediction must have that sign. The two counterfactuals disagree, sometimes in sign. The bar takes their spread as the observation's uncertainty instead of choosing one.

### 6.4 W1 · Water
- **Observed:** each annual water-use figure in `sites.yaml` (Mayes FY2025; The Dalles 2012–2021).
- **Load for year Y:** `(retail MWh of the serving utility in Y − mean over T0−3..T0−1) / 8760`. For Mayes FY2025 the calendar years 2024 and 2025 are averaged; if 2025 EIA-861 is not published at run time, 2024 alone is used. This is utility-wide (all of MidAmerica Industrial Park for GRDA), so it overstates the site's load. The bias is listed in §9.
- **Bar:** PASS for a year if `0.5 ≤ predicted / observed ≤ 2.0`. A site passes W1 if at least 70% of its scored years pass.
- Grant's "~10% of city water" figure covers every data center in a later year, so it is context only. Jackson has no record.

### 6.5 T1 · Timeline (record only)
Months from T0 to first operation are recorded in `SITES.md` for context. Step 2 does not model construction, so T1 is never scored against this engine. Mayes's 2008–2010 pause was a corporate capacity decision, not a grid constraint.

## 7. Grading

Grades are per channel (G1, R1, W1), never pooled across channels.

A channel is graded **PLAUSIBLE for the back-test sites** only if all of these hold:
- at least **3 of the 4** scored sites are scored on it (not NOT SCORED);
- it has **at most one MISS**;
- it has **at least three PASSes**.

Otherwise it stays **SPECULATIVE**. The contrast site is reported in its own table and is never counted.

As registered today, with PENDING items unfilled, the counts are:

| Channel | Scorable sites now | Can reach PLAUSIBLE as registered? |
|---|---|---|
| G1 grid | Wasco, Grant | No, unless Mayes or Jackson gets a documented substation or line record |
| R1 rate | Wasco, Grant, Jackson (only if Jackson's retail seller is NAEC, which also gives Jackson its `L_obs`) | Yes. Needs 3 of 3 to pass. |
| W1 water | Wasco, Mayes | **No.** Only 2 sites have records. |

Only sites with `L_obs` can run at all: today Mayes, Wasco and Grant.

## 8. Amendments and freeze

- **Before the first run**, amendments may only: fill PENDING fields with dated primary sources; correct a factual error, with the source; map engine field names (§5) where step 2 renames an output. Each is a PR with a D-2xx entry. None may change a bar, a formula, a site list or the grading rule.
- An amendment may not use knowledge of engine output. The first run happens only after its amendments merge.
- **After the first run:** frozen. Problems found in the method are recorded as deviations in the results file, and they can only lower a grade. A corrected method is a new pre-registration (v2) on new, held-out sites.

## 9. Known weaknesses

1. **Scale and era.** Three sites are 2006–2011 builds of tens of MW. Passing does not cover 100+ MW AI campuses.
2. **The load input is a utility-level proxy, and it comes from the record.** `L_obs` includes other industrial growth: the whole park for GRDA, several data centers for Grant. Because the run is conditional on it, a pass shows the modules work *given the true load*. It says nothing about predicting load from an announcement.
7. **Rate change vs price change.** The engine reports a lowest-quintile rate change; the record gives an average residential price. They coincide only under one residential tariff.
3. **The R1 counterfactual is weak.** Peer and state differencing disagree by 15–20 pp at Wasco and Grant. The bar is wide because the observation is uncertain, not because the engine is trusted.
4. **Public power only.** IOU rate design (rate cases, riders) is exercised only by the contrast site.
5. **Secondary sources.** Several facts (water at Mayes and The Dalles, Grant's load figures) come from journalists reporting public records, not the records themselves. Pulling the underlying records would strengthen them.
6. **Small n.** Four sites cannot show calibration. At most they can show the engine is not wrong by more than a factor of two, or in sign.

## 10. Reporting

The results file is `validation/backtest/RESULTS_<date>.md` plus a JSON record. In this order:
1. Every **MISS**, each with its bar, the predicted value with p10–p90, and the observed value.
2. Every **NOT SCORED**, and why.
3. PASSes.
4. The per-channel grade from §7, with the counts.
5. The contrast site, separately.
6. Deviations from this document, if any.

The two public disclosure lines go on any public page that shows these results.

## 11. Requests to other rollout chats

To step 2 (engine), for its spec:
- the §5 mapping is done against PR #50; a renamed output needs a mapping amendment;
- an `as_of_year` input that loads EIA-860/861 of year T0−1 (§4.2.1). EIA-861 2001–2024 is already parsed here: `tools/eia861_series.py`;
- a site mask input, with masked features written to the run record (§4.2.2);
- a Census/ACS vintage switch for the synthetic population (§4.2.3);
- seeds, median and p10/p90 per output; the engine commit hash in every ledger record.

To step 1 (build pipeline), through Khaalis: none required. Grant (53025) and Wasco (41065) must be published before they can run.

## 12. What the author knew when writing this

Recorded so the reader can judge. Before fixing the bars, the author had:
- read the public record in `SITES.md`, including water and load figures;
- computed `L_obs` and the observed R1 values in `observed/observed_values.json` (`L_obs` Mayes 47.1 aMW; Wasco 33.8 aMW; Grant 82.5 aMW; Wasco R1 −12.0 pp peer / −33.0 pp state; Grant +2.9 / −15.0; Jackson +2.1 / −7.8 for E=2018 and +2.0 / −9.6 for E=2019). Load for the water years, from the same file: Mayes FY2025 417 aMW (all of GRDA's park load); The Dalles 33–98 aMW over 2012–2021.

The bars are ratios and intervals around observed values, set without any prediction to aim at. No engine output existed. The R1 interval rule (§6.3) was adopted after seeing that the two counterfactuals disagree, in place of choosing one, so that the author's choice of counterfactual cannot decide a pass. For reference only, not as a run: EXP-0007's existing accounting model (Wilcox AL, 20 MW, all inputs assumed) gives −23.8% lowest-quintile rate change grid-only and +16.7% with on-site generation. Compared naively with the R1 intervals, the grid-only value falls inside Wasco's interval and outside Grant's and Jackson's. The on-site value falls outside all three. That model is not the step-2 engine and is not a back-test result.
