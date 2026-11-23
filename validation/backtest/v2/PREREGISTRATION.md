# Back-test v2 pre-registration: AI-infrastructure engine against three more built rural data centers

Rollout step 3 · version 2.0 · registered 2026-11-22 · decision **D-207**
Status: **registered, no runs.** It must merge before the engine runs on any v2 site. Once the first v2 run is recorded, nothing here changes (§8).

v1 (`../PREREGISTRATION.md`, D-200–D-206) stays frozen and its results stand: no misses, two passes, ten of twelve comparisons not scored, every channel SPECULATIVE. v2 is a new test on held-out sites. It fixes the three rules that left v1's comparisons unscored, plus two errors v1 did not catch. Nothing in v2 changes a v1 grade.

## 1. What this can and cannot do

Same as v1 §1:
- Every result is SPECULATIVE unless it passes this method.
- A pass grades one channel PLAUSIBLE for these three sites only.
- Public screening runs stay SPECULATIVE.
- No output is a finding, "validated" or "decision-grade".
- Misses are reported first.

## 2. Sites

| ID | County (FIPS) | RUCC at T0 / 2023 | Operator | Serving utility (EIA id) | T0 | E | Load source |
|---|---|---|---|---|---|---|---|
| V2-01 | Crook OR (41013) | 6 / 3 | Meta | PacifiCorp (14354) | 2010 | 2011 | Meta per-site disclosure |
| V2-02 | Rutherford NC (37161) | 4 / 4 | Meta | Duke Energy Carolinas (5416) | 2010 | 2011 or 2012 | Meta per-site disclosure |
| V2-03 | Morrow OR (41049) | 6 / 8 | AWS | Umatilla Electric Coop (19325) | 2008 | 2011 or 2013 | UEC EIA-861 increment |

Fact sheets and sources are in `SITES.md`. Inputs and observations are in `sites.yaml`. The observed values derived from them are in `observed/observed_values.json`.

## 3. Site rules

1. **Rural when the decision was made.** A site qualifies if its county is nonmetro in the RUCC vintage in force at T0 (2003 codes for these T0s). v1 required nonmetro in every vintage. That would drop Crook, which turned metro in 2023 after Prineville and Bend grew, partly because of these data centers. What a back-test tests is the conditions before the build. This is a rule change, and it is disclosed.
2. **Held out.** No county used in v1.
3. **Not tribal land (D-420).** All three counties have none at the site or in the county.
4. **A world is published**, and every input the run needs exists (§5.3, §11).

## 4. What the engine may know

Same as v1 §4.1 and D-201: a conditional back-test. These come from the record:
- the load that actually arrived (§5.3);
- the cooling design (§5.4);
- the site location (`site_point`).

Nothing about grid builds, rates or water volumes is an input.

### 4.1 Vintage
EIA-860/861 tables are of year T0−1: 2009 for V2-01 and V2-02, 2007 for V2-03. County population is the estimate for July of T0−1 as published then, with Census 2000 household size (D-112's LR-12 rule). Until each exists in R2, the channel it feeds is NOT SCORED.

### 4.2 Fix 2 · The site mask is a bound, not a guess
In v1, keep lists were empty because no source dated a nearby substation before T0. So the 2 km mask removed infrastructure that probably predated each site, which pushed G1 toward "build needed" (v1 results §5).

v2 first tried OSM history as the dating source. The ohsome API shows **no `power=substation` mapped in any of the three counties before 2016**. Lines were mapped, substations were not. So OSM cannot say what stood at T0 for any site built before about 2016.

v2 therefore runs each site **twice** and treats the two networks as bounds:
- **Lower-bound network:** v1's mask. Remove substations within 2 km of the site point, or tagged with an owner term, and the lines ending at them. This network has less than existed at T0.
- **Upper-bound network:** owner-tagged substations removed only (radius 0). This network has more than existed at T0: it keeps non-owner substations built later.

A G1 call is scored only when it is the same on both networks (§6.2). Where the bounds disagree, the pre-T0 grid decides the answer and it cannot be observed, so the comparison is NOT SCORED. This mirrors D-113's rule for an unknown ownership field. Keep lists stay in `sites.yaml`, and a dated record can still add to them before the first run.

## 5. Inputs and engine outputs

### 5.1 Frozen engine
As v1 §4.3:
- One engine commit, named in the record before the first v2 run.
- No parameter fitted on any v2 or v1 site.
- 20 seeds.
- Scoring uses p50. The p10–p90 band is reported. A pass with the observed value outside the band is recorded as "pass, interval miss".

### 5.2 Outputs compared
Mapped as v1 §5 (D-201). G1 uses `power_flow.required_upgrades` (substation, new or expanded) and `new_line_km` at ≥ 69 kV. R1 uses `rate_impact.lowest_quintile_rate_change_pct` for the rate utility. W1 uses `cooling_water.annual_withdrawal_m3`. A module reporting `indeterminate` or `blocked` makes its comparison NOT SCORED.

### 5.3 Fix 3 · Where the load comes from
In v1 the only load rule was the serving utility's Part A (bundled) sales increment over E+1..E+2. It failed in two ways. Under retail choice (Licking OH), bundled sales collapse. At large utilities the site disappears into year-to-year noise: Dominion, Duke and PacifiCorp sell tens of TWh. v2 uses, in order:

1. **The operator's own per-site electricity disclosure for the year the comparison needs.** Meta published per-site use for 2011–2020 (CR-4, CR-5). This is observed load, the same status as v1's `L_obs`.
2. **Otherwise, the serving utility's EIA-861 delivered energy, Parts A + B** (bundled plus delivery-only, never energy-only Part C, which would double count). For year Y the load is mean(Y−1, Y) minus the mean over T0−3..T0−1, in average MW. It is used only if **detectable**: the increment must be at least 3× the standard deviation of the utility's year-on-year changes over T0−7..T0−1. A load that fails the test is not used.
3. Otherwise no load, and the site cannot run that comparison.

Each comparison takes the load **of its own year**: G1 at E+2 (the end of the build window), R1 at E+5 (the rate year), W1 at the water year. v1 used E+1..E+2 for every channel, so its R1 compared an E+5 price with an E+2 load.

| Site | G1 load (E+2) | R1 load (E+5) | Source |
|---|---|---|---|
| V2-01 | 25.6 aMW (2013) | 37.3 aMW (2016) | Meta |
| V2-02 | 25.7 (2013) / 36.8 (2014) aMW | 38.7 (2016) / 49.4 (2017) aMW | Meta |
| V2-03 | 21.7 (2013) / 71.3 (2015) aMW | 96.7 (2016) / 170.4 (2018) aMW | UEC; detect ratios 5.6–44.2 |

V2-03's UEC load includes every AWS campus UEC serves, in Morrow and Umatilla counties, and the run places all of it at one point. That is listed in §10.

### 5.4 Cooling
Both Meta sites cool by pushing outside air through an evaporative "mister" wall, with no cooling towers or chillers reported (CR-6, RU-2). The engine's three designs are `dry`, `adiabatic_hybrid` (evaporation above a setpoint) and `evaporative` (cooling towers). v2 maps the Meta design to `adiabatic_hybrid`, by the design description. One design is run, not three. §12 records that the observed water figures were visible when this mapping was made.

### 5.5 Fix 1 · R1 where the site is a large share of its utility
In v1, Wasco's site was 1.22× its utility's sales. The engine's rate model treats a site as one customer among many and declares itself invalid above 25% of sales (D-102), so Wasco R1 was not scored. v2 fixes this in two ways.

**(a) A floor for attribution.** R1 compares an observed residential price change with a counterfactual. Below a few percent of the utility's sales, the site's possible effect is smaller than the utility's ordinary rate movements. The observed difference then measures the utility's own rate cases, not the site. v2 scores R1 only where the site's energy at E+5 is **at least 5% of the rate utility's T0−1 delivered sales**. Shares, from observed load: V2-01 0.024, V2-02 0.006–0.008, V2-03 0.97–1.71. So **V2-01 and V2-02 R1 are NOT SCORED** by this floor. §12 records that this floor was set after the observed R1 values were computed.

**(b) A large-load rate output.** For a site above the engine's 25% validity limit, R1 is scored only against an engine output built for that case: `rate_impact.large_load.lowest_quintile_rate_change_pct` per utility and allocation. In it the site is a separate rate class paying its own incremental supply, transmission and distribution costs under each allocation, and the residential effect is the net change in the cost left to other customers. It must carry `valid_for_site_share: true` for the run's share. The output does not exist yet (§11). If it is missing at run time, R1 there is NOT SCORED.

The R1 bar itself is v1's, unchanged (§6.3).

### 5.6 Two errors v1 did not catch, fixed here
- **Single-state utilities only.** v1's `derive_observed.py` filtered rows by utility and not by state. That was correct for every v1 site, whose utilities sell in one state. It would be wrong for PacifiCorp (six states). v2's tool filters every quantity to the site's state. v1 values are unaffected; this was checked for NWCPUD, Grant PUD, NAEC and GRDA.
- **Load year.** See §5.3.

## 6. Comparisons and pass bars

PASS, MISS or NOT SCORED. NOT SCORED is never a pass. Every candidate E must pass.

### 6.1 G1 · Grid build
- **Observed:** whether a new or expanded substation, and whether a new line at ≥ 69 kV, was built to serve the site between T0 and E+2. Only the documented boolean is compared. All three sites document a substation; none documents a line (`sites.yaml`).
- **Prediction:** "yes" when at least 50% of seeds include it, on each mask bound (§4.2).
- **Bar:** PASS if both bounds give the observed answer. MISS if both give the other answer. NOT SCORED if the bounds disagree.

### 6.2 R1 · Residential rate (as v1 §6.3)
Peer- and state-differenced price change, T0−1 to E+5, for the rate utility. PASS if the p50 lies in `[min(peer, state) − 5, max(peer, state) + 5]` pp, with the sign rule. No cost allocation is fixed by a record dated before E, so a pass needs all three allocations. Where ownership is blank in EIA-861, D-113 applies: both cases must pass, and a straddle is NOT SCORED. Scored only under §5.5.

Observed R1, for the record:

| Site | Peer (pp) | State (pp) | Status |
|---|---|---|---|
| V2-01 | +17.62 | +8.97 | peer n = 2 IOUs; NOT SCORED by the §5.5(a) floor |
| V2-02 | +20.46 (E=2011) / +20.35 (E=2012) | +13.63 / +11.66 | NOT SCORED by the floor |
| V2-03 | +1.98 (E=2011) / −3.86 (E=2013) | −0.01 / −7.83 | needs §5.5(b) |

### 6.3 W1 · Water (as v1 §6.4)
Annual withdrawal p50 within 0.5–2.0× the observed figure for each year. A site passes if at least 70% of its years pass. Load per year from Meta (§5.3), cooling `adiabatic_hybrid` (§5.4).

| Site | Years |
|---|---|
| V2-01 | 2014–2020, 7 years |
| V2-02 | 2014–2020, 7 years |
| V2-03 | no site-scope record; not scored |

## 7. Grading

As v1 §7, per channel. PLAUSIBLE for these sites requires at least 3 of 3 sites scored, at least 3 passes and at most 1 miss. **With three sites, that means all three scored and all three passing.**

## 8. Amendments and freeze

As v1 §8.
- **Before the first v2 run**, amendments may only:
  - fill PENDING fields from dated primary sources;
  - add keep-list ids with a dated source;
  - correct facts;
  - map engine field names.
- No bar, formula, site or grading rule may change.
- **After the first run**, v2 is frozen. A further change needs v3 on new held-out sites.

## 9. What can reach PLAUSIBLE as registered

| Channel | Can be scored at | Can reach PLAUSIBLE? | What it needs first |
|---|---|---|---|
| G1 | V2-01, V2-02, V2-03 | **Yes** (all three must pass) | EIA 2007 and 2009 tables in R2; LR-12 for vintages 2007 and 2009 and Census 2000; the engine running both mask bounds (§11) |
| R1 | V2-03 only | **No** | §5.5(b) output; even then one site |
| W1 | V2-01, V2-02 | **No** (two sites) | — |

**v2 can promote at most one channel, G1, and only if all three sites pass on both mask bounds.** A third water site, or a second and third large-share rate site, would need v3.

## 10. Known weaknesses

1. **Era and scale.** All three sites were built 2008–2013 at tens of MW. None is a 100+ MW AI campus. Modern sites have no E+5 inside EIA-861's last year (2024).
2. **Mask bounds can disagree at every site.** OSM mapped no substations before 2016 in these counties, so G1 may end up NOT SCORED everywhere. That is the honest result if it happens.
3. **V2-03's load is UEC-wide.** It covers AWS campuses in two counties, placed at one point. This biases G1 toward predicting builds.
4. **V2-02's substation has no build date.** It counts because its operator is the site's owner.
5. **Peer counterfactuals for IOUs are thin** (n = 2). This matters only for the record, since those R1s are below the floor.
6. **The cooling mapping is a judgment** (§5.4, §12).

## 11. Requests

**To step 1 (build pipeline, through Khaalis):**
- EIA-860/861 history for **2007 and 2009** in R2 (`eia/2007/`, `eia/2009/`, D-062's layout).
- **LR-12** (D-112) for popest vintages **2007 and 2009**, and decennial **2000** households.

**To step 2 (engine):**
- **Urgent:** extend `gate.py` to read `validation/backtest/v2/sites.yaml` now. Otherwise the no-tuning rule does not protect Morrow and Rutherford: Crook is already a brief candidate, and Morrow and Rutherford are not.
- Honour `mask_radius_m` per run, so a back-test can run at radius 0 and at 2000 m (§4.2). Record which bound each run used.
- The §5.5(b) large-load rate output, its method and its validity field.
- The cooling design per site from `sites.yaml` (`cooling`).

## 12. What the author knew when writing this

Recorded so the reader can judge:
- **All of v1:** its results, including how the engine behaved there. Its rate result tracks the assumed margin share. Its evaporative water intensity is about 1.7 L/IT-kWh. On the 2 km-masked network it calls for a substation at both sites.
- **The observed values for v2's sites before setting v2's rules:** loads, water, and the R1 values in §6.2.

Two rules were set after seeing observed values:
- **§5.5(a), the 5% attribution floor.** It removes V2-01 and V2-02 R1, where observed peer-differenced changes are +17.6 and +20.4 pp. An engine reading of a ~1% site would almost certainly be near zero, so these would very likely have been misses. The floor exists because those observed changes reflect PacifiCorp's and Duke's system-wide rate paths, not the sites. But it was adopted knowing it removes two likely misses. **Both comparisons will still be computed and published in the results, labelled "below the attribution floor, not scored", so anyone can see them.**
- **§5.4, the cooling mapping.** The design description was read first. But the Meta sites' observed water intensity (0.1–0.7 L/kWh) was visible from the disclosures, and it is far below v1's evaporative intensity.

No engine output exists for any v2 site. Neither rule changes a bar.

## 13. Amendment and status log

(empty)

---

*RuralSim is a free, open-source project by Aldrich K. Wooden, Sr., founder of Get Rural America Done.*
*Simulated, screening-grade results with assumed parameters. Decision support, not a finding.*
