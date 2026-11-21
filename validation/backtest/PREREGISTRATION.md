# Back-test pre-registration: AI-infrastructure engine against built rural data centers

Rollout step 3 · version 1.0 · registered 2026-11-21 · decision **D-200**
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

Two exceptions widen the date, each the same for every site:
- **L1 (load):** the information set is every data-center project served by the same utility whose public announcement is dated ≤ E+2, each limited to facts published at its own announcement. The observed load window runs to E+2, so projects announced inside it belong in the run.
- **W1 (water):** for an observation in year Y, the engine may use cumulative publicly announced investment as of Y. It may never use any observed water figure.

Never allowed as input: any quantity in an `observed:` block; any later estimate of the site's MW (for example the 2008 "~30 MW" for The Dalles); EIA, PUD or press figures on the site's actual consumption.

### 4.2 World layers: vintage and masking
Published worlds are current (OSM 2026, EIA-860/861 2024, Overture 2026-10, CDL 2025). They contain the data centers themselves and their interconnections. Each back-test run must therefore:
1. use **EIA-860 and EIA-861 tables of year T0−1** in place of the 2024 tables;
2. **mask the site:** remove buildings inside the site parcel, and remove every OSM `power=substation` within 2 km of the parcel, and every `power=line` or `power=minor_line` ending at one, unless a dated source shows it existed before T0. Transmission lines longer than 10 km that pass within the 2 km buffer without ending there stay. Every masked feature is listed in the run record;
3. use Census/ACS values of the vintage nearest to and not after T0 for the synthetic population;
4. keep terrain, hydrology, climate normals (1991–2020) and land tenure as published. Their post-T0 change is small against the site. The climate normals overlap the outcome years, and this is recorded.

If the engine cannot apply 4.2.1–4.2.3, the affected channel is **NOT SCORED** for that run (§11).

### 4.3 Frozen engine
- One tagged commit of the engine and its parameter files, named in the run record before the first site runs.
- No parameter may be set, fitted or tuned using any back-test site. A change to the engine after the first back-test run voids grading for every channel it touches. A rerun on these sites is then reported but cannot raise a grade.
- 20 seeds per site. The prediction is the **median** across seeds; p10 and p90 are reported. A median pass with the observed value outside p10–p90 is recorded as "pass, interval miss" and does not change the grade.

## 5. Engine outputs required

Proposed to step 2 for its output schema. Field names may be mapped to step 2's names by amendment before the run; the quantities and bars may not change.

| Field | Unit | Used by |
|---|---|---|
| `site_load_avg_mw` | average MW at full announced build of the information set | L1 |
| `new_substation_required` | boolean per seed | G1 |
| `new_transmission_required` (≥ 69 kV) | boolean per seed | G1 |
| `residential_rate_change_pct_y5` | % change in residential price attributable to the site, year E+5 against T0−1 | R1 |
| `site_water_withdrawal_gal_yr` | gallons per year, at the stated investment level | W1 |
| `months_to_energize` | months from T0 | T1 (context) |

Each output carries the `observed | assumed` provenance tags the harness already uses.

## 6. Comparisons and pass bars

Every comparison scores **PASS**, **MISS** or **NOT SCORED**. NOT SCORED applies when the observation or a required input is PENDING at run time. It is never counted as a pass. Where E is uncertain (Jackson: 2018 or 2019), the comparison is computed for each candidate year and **passes only if it passes for all of them**.

### 6.1 L1 · Site load
- **Observed:** `(mean retail MWh of the serving utility over E+1..E+2 − mean over T0−3..T0−1) / 8760`, from EIA-861 Part A. This is the utility's whole load change. Other industrial growth in the window is included and not removed.
- **Bar:** PASS if `0.5 ≤ predicted / observed ≤ 2.0`.
- Scored only where the serving utility is the site's retail seller and is named in `sites.yaml`. Jackson is scored only if the retail seller is shown to be NAEC. TVA's Alabama direct-serve total is dominated by other customers.

### 6.2 G1 · Grid build
- **Observed:** whether a new substation, or a new or rebuilt transmission line of 69 kV or more, was built to serve the site between T0 and E+2. This is two booleans, each from a dated source.
- **Prediction:** each boolean is "yes" when at least 50% of seeds say yes.
- **Bar:** PASS when both booleans match. When only one is documented, that one must match and the other is NOT SCORED.

### 6.3 R1 · Residential rate
- **Rate utility:** the site's serving utility where it has residential retail (NWCPUD, Grant PUD). Otherwise, the distributor whose territory contains the site and which buys from the serving utility, documented before the run (Jackson: NAEC, territory to verify; Mayes: PENDING). If it cannot be documented, R1 is NOT SCORED.
- **Observed:** two estimates of the site-attributable change, in percentage points, between T0−1 and E+5:
  - peer: `100·[(p_u(E+5)/p_u(T0−1) − 1) − (p_peer(E+5)/p_peer(T0−1) − 1)]`, where `p` is bundled residential revenue ÷ sales and the peers are same-state utilities of the same EIA ownership class reporting residential sales in both years (a balanced panel);
  - state: the same with the all-utility state average in place of the peers.
- **Bar:** PASS if the prediction lies in `[min(peer, state) − 5, max(peer, state) + 5]` pp. In addition, where both estimates have the same sign and both have magnitude ≥ 5 pp, the prediction must have that sign. The two counterfactuals disagree, sometimes in sign. The bar takes their spread as the observation's uncertainty instead of choosing one.

### 6.4 W1 · Water
- **Observed:** each annual water-use figure in `sites.yaml` (Mayes FY2025; The Dalles 2012–2021).
- **Bar:** PASS for a year if `0.5 ≤ predicted / observed ≤ 2.0`. A site passes W1 if at least 70% of its scored years pass.
- Grant's "~10% of city water" figure covers every data center in a later year, so it is context only. Jackson has no record.

### 6.5 T1 · Timeline (context only)
Months from T0 to first operation are reported against the record. T1 is not graded. Mayes's 2008–2010 pause was a corporate capacity decision, not a grid constraint, and the engine has no construction model. It may become graded only by an amendment merged before the first run, with a bar of ±12 months.

## 7. Grading

Grades are per channel (L1, G1, R1, W1), never pooled across channels.

A channel is graded **PLAUSIBLE for the back-test sites** only if all of these hold:
- at least **3 of the 4** scored sites are scored on it (not NOT SCORED);
- it has **at most one MISS**;
- it has **at least three PASSes**.

Otherwise it stays **SPECULATIVE**. The contrast site is reported in its own table and is never counted.

As registered today, with PENDING items unfilled, the counts are:

| Channel | Scorable sites now | Can reach PLAUSIBLE as registered? |
|---|---|---|
| L1 load | Mayes, Wasco, Grant | Yes. Needs 3 of 3 to pass, plus the `projects_in_info_set` inputs for Mayes and Grant. |
| G1 grid | Wasco, Grant | No, unless Mayes or Jackson gets a documented substation or line record |
| R1 rate | Wasco, Grant, Jackson (if NAEC territory verified) | Yes. Needs 3 of 3 to pass. |
| W1 water | Wasco, Mayes (once cumulative investment is filled) | **No.** Only 2 sites have records. |

## 8. Amendments and freeze

- **Before the first run**, amendments may only: fill PENDING fields with dated primary sources; correct a factual error, with the source; map engine field names (§5); add T1 grading (§6.5). Each is a PR with a D-2xx entry. None may change a bar, a formula, a site list or the grading rule.
- An amendment may not use knowledge of engine output. The first run happens only after its amendments merge.
- **After the first run:** frozen. Problems found in the method are recorded as deviations in the results file, and they can only lower a grade. A corrected method is a new pre-registration (v2) on new, held-out sites.

## 9. Known weaknesses

1. **Scale and era.** Three sites are 2006–2011 builds of tens of MW. Passing does not cover 100+ MW AI campuses.
2. **L1 is a utility-level proxy.** It includes other industrial growth: the whole park for GRDA, several data centers for Grant.
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
- the §5 output fields, or a mapping;
- an `as_of_year` input that loads EIA-860/861 of year T0−1 (§4.2.1). EIA-861 2001–2024 is already parsed here: `tools/eia861_series.py`;
- a site mask input, with masked features written to the run record (§4.2.2);
- a Census/ACS vintage switch for the synthetic population (§4.2.3);
- seeds, median and p10/p90 per output; the engine commit hash in every ledger record.

To step 1 (build pipeline), through Khaalis: none required. Grant (53025) and Wasco (41065) must be published before they can run.

## 12. What the author knew when writing this

Recorded so the reader can judge. Before fixing the bars, the author had:
- read the public record in `SITES.md`, including water and load figures;
- computed the observed L1 and R1 values in `observed/observed_values.json` (Mayes L1 47.1 aMW; Wasco 33.8 aMW; Grant 82.5 aMW; Wasco R1 −12.0 pp peer / −33.0 pp state; Grant +2.9 / −15.0; Jackson +2.1 / −7.8 for E=2018 and +2.0 / −9.6 for E=2019).

The bars are ratios and intervals around observed values, set without any prediction to aim at. No engine output existed. The R1 interval rule (§6.3) was adopted after seeing that the two counterfactuals disagree, in place of choosing one, so that the author's choice of counterfactual cannot decide a pass. For reference only, not as a run: EXP-0007's existing accounting model (Wilcox AL, 20 MW, all inputs assumed) gives −23.8% lowest-quintile rate change grid-only and +16.7% with on-site generation. Compared naively with the R1 intervals, the grid-only value falls inside Wasco's interval and outside Grant's and Jackson's. The on-site value falls outside all three. That model is not the step-2 engine and is not a back-test result.
