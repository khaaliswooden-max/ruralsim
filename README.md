# RuralSim

A reproducible rural-county digital twin: five pilot counties as OpenUSD 3D worlds, a national
statistical table for 3,144 counties, and an experiment harness that scores interventions on a
rural quality-of-life index (RQLI), always as a distribution with hard equity constraints.

**Results are screening-grade.** Engines are reduced-order with assumed device parameters; no
experiment result is a finding until confirmed with full-physics models. See `docs/LIMITS.md`.

## Quickstart

```bash
pip install -r requirements.txt

# rebuild a pilot county's 3D stage from the committed raw layers, then validate it
python3 tools/build_stage.py 16081
python3 tools/validate_county.py 16081

# run experiment cards (20 seeds = promotion-eligible; baselines cached to experiments/baseline_cache/)
python3 -m tools.harness.run_experiment EXP-0002 --seeds 20
python3 -m tools.harness.run_experiment --county 01131 --seeds 20

# rebuild the national table
python3 tools/build_national.py

# full rebuild including live data fetches (needs network)
python3 tools/build_county.py 31173

# build any other current U.S. county the same way (boundary cached to counties/<fips>.geojson)
python3 tools/build_county.py 48301      # Loving County, TX

# rebuild the website into public/ (Vercel runs this on every push to main)
python3 tools/build_site.py
```

Pilot FIPS: 31173 Thurston NE · 16081 Teton ID · 54047 McDowell WV · 20019 Chautauqua KS · 01131 Wilcox AL.
Live site: <https://www.ruralsim.io>. The data tables in `data/` and `pilots/` were built by the
scripts in `build_scripts/` (see its README for sources).

The live fetchers depend on public services that are sometimes down or rate-limited
(OpenStreetMap Overpass, Open-Meteo, CropScape). Each fetch is resumable: rerun the same
command and it picks up where it stopped.

## License

Code: [Apache 2.0](LICENSE). Data: see [DATA_LICENSE.md](DATA_LICENSE.md). Map data derived from
OpenStreetMap is © OpenStreetMap contributors under the ODbL; other public data keeps its
publisher's terms; RuralSim's own specs, results and writing are CC BY 4.0.
Reproducibility check (2026-11-12, clean machine): all five stages, all ten cards at 20 seeds, and
the national table reproduced identically to the original build.

---

# Original handoff bundle v0.1

Built 2026-11-10. Everything Kimi K3.1 Pro needs to start building the 3D rural world model, except the items under "You must supply".

> **Build status 2026-11-12** — all five pilot 3D twins built, validated and render-verified
> (`worlds/`, `validation/`); Tier A national statistical twin built (`national/`, 3,163 counties,
> 8/8 checks pass); experiment harness operational (`tools/harness/`, ten seed cards in
> `experiments/ledger/`); `improve-quality-of-life` skill packaged in `skills/`.
> See `docs/ARCHITECTURE.md` §8, `docs/DECISIONS.md` D-001…D-026, `docs/LIMITS.md`.

## Start here

1. Unzip this bundle into the working directory of an agentic Kimi session (Kimi Code or equivalent, with shell and network).
2. Fill the compute budget in `PROMPT.md`, then paste `PROMPT.md` as the first message.
3. Kimi stops at Gate 1 after profiling the data. Review before it proceeds.

## Contents

| Path | What it is | Rows |
|---|---|---|
| `PROMPT.md` | The build prompt, pre-filled with this bundle's paths and pilot counties | |
| `data/county_master.csv` | One row per county: rural codes 1974–2023, Census rural share, typology, area, centroid, population 1900/2000/2010/2020/2024, poverty, income, hospitals, last three presidential margins | 3,163 (3,144 current + 19 retired codes) |
| `data/county_year.csv` | Population and components of change, 2010–2024 | 47,150 |
| `data/county_profile.csv` | 254 demographic, jobs, income and veteran indicators (USDA ERS Atlas) | 3,148 |
| `data/county_decade.csv` | Decennial population 1900–2020 | 40,159 |
| `data/county_election.csv` | Presidential returns by county, 1868–2024 | 116,878 |
| `data/state_decade_power.csv` | State population, House seats, electoral votes, Senate / House / Electoral College weight indices, 1910–2020 | 588 |
| `data/national_power_summary.csv` | Malapportionment indices by decade; nonmetro- vs metro-weighted Senate and Electoral College weight (2020) | 12 |
| `data/facility_hospital.csv` | Every Medicare-registered hospital with address, type and county | 5,419 |
| `data/codebook.csv` | Every column: description, source, vintage, provenance tag | 375 |
| `pilots/pilot_counties.csv` | Five pilot counties with selection rule, profile and bounding box | 5 |
| `pilots/pilot_county_boundaries.geojson` | Real county polygons (Census 2023 cartographic boundaries) | 5 |
| `specs/geodata_manifest.yaml` | Every 3D layer: source, access point, auth, provenance | 22 layers |
| `specs/rqli_spec.yaml` | Quality-of-life index: 9 domains, 21 indicators, 6 hard constraints | |
| `experiments/experiment_card_schema.yaml` | The format every test must follow | |
| `experiments/seed_experiments.yaml` | Ten ready-to-run experiment cards | 10 |
| `build_scripts/` | The scripts that produced `data/` and `pilots/` from raw sources (restored 2026-11-12; see its README) | |

## Checks run on the data

| Check | Result | Reference |
|---|---|---|
| 2020 population, current counties | 331,449,281 | Matches the 2020 Census count |
| Nonmetro / metro counties (RUCC 2023) | 1,958 / 1,186 | Matches USDA ERS |
| Nonmetro share of population | 13.8% | Matches USDA ERS |
| Census rural population | 66,300,254 (20.0%) | Matches Census Bureau |
| Key uniqueness, `fips5` | Unique in master | |
| Hospital-to-county match | 97.4% of facilities | 2.6% unmatched on county name |
| Nonmetro presidential margin | D+1.5 in 1992, R+15.0 in 2000, R+32.1 2016, R+32.0 2020, R+35.6 2024 | 2024 is consistent with published ~R+36 |
| Nonmetro share of votes cast | 16.7% (1992) → 14.2% (2024) | Counties classified by their 2023 code in every year |

Computed from the tables, 2020: a nonmetro resident's average Senate weight is 1.67 against 0.89 for a metro resident (1.0 = proportional). For the Electoral College it is 1.13 against 0.98.

## Known gaps: read before trusting any result

1. **No infrastructure condition data yet.** Broadband availability, bridge condition, water violations, schools and grid assets are not in `data/`. They are point or location datasets that Kimi fetches per pilot county from `specs/geodata_manifest.yaml`. County-level national aggregates of these are not built.
2. **No annual economic series.** BLS blocked automated download and the Census and BEA APIs need keys. Income and poverty are 2023 snapshots; jobs indicators come from the ERS Atlas.
3. **2024 election returns are from an unofficial GitHub compilation**, not the MIT Election Lab file, which requires accepting terms in a browser. Replace it with the official file (see below).
4. **Alaska has no county-level election returns** (27–30 areas missing each year); Alaska reports by election district.
5. **Connecticut appears twice** in `county_decade` for 2020 (eight retired counties and nine planning regions), so the 2020 column sums to 335.1M, not 331.4M. Filter on `geography_vintage` in `county_master`.
6. **Historical county boundaries are not harmonized.** Pre-1990 populations are as-reported for the county as it existed then.
7. **No congressional or state-legislative district table.** It needs block-level files and was not built.
8. **Election data stops at 2024.** 2026 midterm county returns were not certified at build time.
9. **Hospital counts are a current snapshot**, not a history; closures are not included.
10. **The quality-of-life weights and thresholds are the designer's starting values**, not validated with residents.
11. **All ten seed experiments use placeholder device parameters** marked `assumed`. Replace with real spec sheets before treating any result as a finding.

## You must supply

| Item | Why | Where |
|---|---|---|
| Compute budget and runtime | Sets fidelity and which engines Kimi can run | Fill in `PROMPT.md` |
| Census API key (free) | Annual ACS detail, including household internet subscription | https://api.census.gov/data/key_signup.html |
| FCC account (free) | Bulk download of location-level broadband availability | https://broadbandmap.fcc.gov/data-download |
| NREL API key (free) | Solar and wind resource data | https://developer.nrel.gov/signup/ |
| MIT Election Lab county file | Official 2000–2024 returns; requires accepting terms | https://doi.org/10.7910/DVN/VOQCHQ |
| Real device spec sheets | For any hardware or robot you actually intend to test | Replace `assumed` parameters in the cards |

## Sources

USDA ERS (Rural-Urban Continuum Codes 1974–2023; County Typology Codes 2025; Atlas of Rural and Small-Town America), U.S. Census Bureau (2024 Gazetteer; 2020 Urban Area county file; Population Estimates Vintage 2020 and 2024; SAIPE 2023; apportionment 1910–2020; 2023 cartographic boundaries), NBER copy of Census historical county counts 1900–1990, CMS Hospital General Information, Algara & Amlani county presidential returns 1868–2020 (doi:10.7910/DVN/DGUMFI, CC0), tonmcg/US_County_Level_Election_Results_08-24 (2024).
