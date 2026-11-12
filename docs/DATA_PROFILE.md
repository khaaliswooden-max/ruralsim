# RuralSim — Data Profile (Gate G1)

Built 2026-11-11 from `ruralsim_handoff_v0.1`. All row counts reproduced against README claims; discrepancies and traps documented below. `fips5` is carried as a zero-padded 5-character string everywhere (verified: zero malformed keys in all six fips-bearing tables).

## 1. Table inventory

| Table | Rows (README claim) | Rows (measured) | Cols | Key | Key unique | Coverage |
|---|---|---|---|---|---|---|
| `county_master` | 3,163 | 3,163 ✓ | 62 | `fips5` | ✓ (3,144 vintage `2024` + 19 `legacy`) | snapshot |
| `county_year` | 47,150 | 47,150 ✓ | 11 | `fips5`+`year` | ✓ | 2010–2024, 15 yrs |
| `county_profile` | 3,148 | 3,148 ✓ | 255 (254 indicators + key) | `fips5` | ✓ | snapshot |
| `county_decade` | 40,159 | 40,159 ✓ | 5 | `fips5`+`year` | ✓ | 1900–2020, 13 censuses |
| `county_election` | 116,878 | 116,878 ✓ | 15 | `fips5`+`year` | ✓ | 1868–2024, 40 elections |
| `facility_hospital` | 5,419 | 5,419 ✓ | 11 | `Facility ID` | ✓ | current snapshot |
| `state_decade_power` | 588 | 588 ✓ | 15 | `state_name`+`year` (see §3.6) | ✓ | 1910–2020 |
| `national_power_summary` | 12 | 12 ✓ | 12 | decade | ✓ | 1910–2020 |
| `codebook` | 375 | 375 ✓ | 6 | `table`+`column` | ✓ | — |

## 2. Independent reproduction of README checks

| Check | README | Measured | Verdict |
|---|---|---|---|
| 2020 population, current counties | 331,449,281 | 331,449,281 (filter `geography_vintage == "2024"`) | ✓ exact |
| CT double-count in `county_decade` 2020 | sums to 335.1M unfiltered | 335,055,225 unfiltered; 17 CT rows (8 legacy + 9 planning regions) | ✓ confirmed, filter resolves |
| Hospital→county match | 97.4% | 97.4% `fips5` non-null (2.6% unmatched) | ✓ |
| Nonmetro/metro counties (RUCC 2023) | 1,958 / 1,186 | spot-consistent with master | ✓ |

## 3. Findings beyond the README

### 3.1 `county_year` — components of change absent in census anchor years
`births`, `deaths`, `natural_change`, `international_migration`, `domestic_migration`, `net_migration`, `pop_change_pct` are null for **exactly** 2010 (3,143 rows) and 2020 (3,144 rows) — the two decennial anchor years, where population is a census count rather than an estimate. All other years are complete. **Handling:** not a defect; treat 2010/2020 as population anchors and derive intercensal components only for estimate years. Two `popest_vintage` values coexist (vintage-2020 series: 31,430 rows; vintage-2024: 15,720 rows) — always filter or group by vintage before differencing.

### 3.2 `county_profile` — cleaner than feared
254 indicators, zero "(D)"-suppressed cells, zero non-numeric junk values, no column over 10% missing. ERS has already suppressed small-cell columns out of the file entirely rather than marking them. **Handling:** absence of an indicator ≠ value of zero; the IPF marginal set must intersect with available columns per county, not assume full coverage.

### 3.3 `county_election` — Alaska and one historical quirk
- Alaska: **zero** county-level rows 1868–2020; the 2024 unofficial compilation adds 40 AK area rows (vs. 36 AK codes in master — includes non-current areas). README gap #4 confirmed and slightly understated for 2024.
- 13 rows with null `fips5` (1868–1916, small vote counts, Algara & Amlani source) — appear to be territory/unorganized returns. Exclude from county joins; retain only for national totals if ever needed.
- Counties per year range 1,723 (1868) → 3,160 (2024): historical county creation is real, not missing data. `in_current_spine` flag (262 False rows) handles the retired-code spine.
- Guardrail note: per `rqli_spec.yaml` hard constraint `political_variables_excluded`, this entire table plus `state_decade_power`, `national_power_summary` and `pres_margin_rd_*` columns are context-only and are fenced off from the objective, optimizer features, and agent targeting.

### 3.4 `state_decade_power` — join key is `state_name`, not `state_abbr`
`state_abbr` is null for 538 of 588 rows (all pre-2000 decades). Key on `state_name`+`year`, which is unique. Minor schema wart; documented, not blocking.

### 3.5 `county_master` — expected nulls only
Only column >10% missing is `pop_1900_census` (counties not yet organized in 1900, e.g. Teton ID — correct behavior). Poverty and median household income carry 90% CI columns (`*_ci90_lo/hi`) — these will be propagated into the simulation as uncertainty per Section 2 of the prompt, not collapsed to points. Boolean trap flags already exist: `is_ct_planning_region`, `is_ak_borough_or_census_area`, `is_va_independent_city` (41 VA independent cities present and flagged).

### 3.6 `facility_hospital` — needs geocoding
Address fields only; no lat/lon. Geocoding is a Tier B task (manifest layer `hospitals`). 2.6% county-name unmatched facilities need a second-pass matcher before pilot validation (hospital count must match `n_hospitals` exactly per manifest validation rule).

## 4. Pilot counties — confirmed and consistent

All five FIPS (20019, 54047, 01131, 31173, 16081) are present in **every** data table including `facility_hospital`, and all five polygons exist in `pilot_county_boundaries.geojson` (EPSG:4326 `Polygon` geometries). Values in `pilot_counties.csv` match `county_master` exactly (population, poverty, income, hospitals, housing units). Build order per prompt, smallest first: **31173 Thurston NE → 16081 Teton ID → 54047 McDowell WV → 20019 Chautauqua KS → 01131 Wilcox AL**.

Cross-archetype spread is wide and useful: poverty 6.6%–36.2%, median HH income $34.4k–$94.9k, population trajectory from 19% of peak (McDowell) to at-peak (Teton), one majority-Native county with tribal-sovereignty constraints (Thurston; `tribal_boundaries` layer mandatory).

## 5. Missing inputs (not in bundle, by design)

Per README "Known gaps" and manifest, the following must be fetched per pilot county and are **not yet present**: terrain, land cover, crops, hydrology, flood zones, buildings, roads, bridges, rail, grid (transmission/generation/territory), broadband, towers, schools, water systems, solar/wind resource, climate, land tenure, tribal boundaries. Until fetched, every dependent world feature is tagged `assumed`.

Two manifest layers require credentials the bundle does not include: **FCC National Broadband Map bulk download** (free account) and **NREL API key** (free). PROMPT.md's compute-budget and API-key fields were left as placeholders.

## 6. Gate G1 recommendation

Data foundation is sound: counts, keys, and external reference totals all reproduce; the known traps (CT vintage, AK elections, VA cities, census-anchor nulls, vintage mixing) are understood and have defined handling. Recommend proceeding to Tier B pilot 1 (Thurston County NE, 31173) with the no-key fetch subset (USGS 3DEP/TNM, NLCD, CropScape, TIGER roads + AIANNH, Overture buildings, NBI, EIA, NCES, EPA ECHO, NOAA, PAD-US), marking FCC-broadband and NREL-resource layers `assumed` until keys arrive.
