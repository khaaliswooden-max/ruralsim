# Data build scripts

These two scripts produced everything in `data/` and `pilots/`. They were written on
2026-11-10, before the 3D build, and were left out of the exported repo by mistake; they are
restored here unchanged from the original handoff bundle (`ruralsim_handoff_v0.1`).

| Script | Produces | Run |
|---|---|---|
| `build.py` | `data/county_master.csv`, `county_year.csv`, `county_profile.csv`, `county_decade.csv`, `county_election.csv`, `state_decade_power.csv`, `national_power_summary.csv`, `facility_hospital.csv`, `codebook.csv` | `python3 build_scripts/build.py RAW/ OUT/` |
| `pilots.py` | `pilots/pilot_counties.csv`, `pilots/pilot_county_boundaries.geojson` | `python3 build_scripts/pilots.py RAW/ OUT/` (needs `OUT/data/` from `build.py`) |

Extra Python packages beyond `requirements.txt`: `xlrd` and `openpyxl` (Excel inputs),
`pyreadr` (the 1868–2020 election file is an `.Rdata`), `pyshp` (county shapefile).

## The raw folder

Both scripts read source files from a raw folder laid out as below. The raw files are not
committed: they are large and each publisher distributes its own copy. Download them into
this layout, then run the scripts.

| Path under `RAW/` | Source (as recorded in `data/codebook.csv`) |
|---|---|
| `gaz/2024_Gaz_counties_national.txt` | Census Gazetteer 2024, counties (unzipped from `2024_Gaz_counties_national.zip`) |
| `ers_rucc/rucc2023.csv`, `rucc2013.xls`, `rucc2003.xls`, `rucc1983_1993.xls`, `rucc1974.xls` | USDA ERS Rural-Urban Continuum Codes, all vintages |
| `census_ua/2020_UA_COUNTY.xlsx` | Census 2020 Urban Area county file (sheets `2020_UA_COUNTY`, `CT_2022`) |
| `ers_typ/typology2025.csv` | USDA ERS County Typology Codes, 2025 edition |
| `cms/hospitals.csv` | CMS Hospital General Information (Provider Data dataset `xubh-q36u`) |
| `saipe/est23all.xls` | Census SAIPE 2023 state and county estimates |
| `popest/co-est2020-alldata.csv`, `popest/co-est2024-alldata.csv` | Census Population Estimates, Vintage 2020 (2010–19) and Vintage 2024 (2020–24) |
| `ers_atlas/People.csv`, `Jobs.csv`, `Income.csv`, `Veterans.csv`, `CountyClassifications.csv`, `VariableNameLookup.csv` | USDA ERS Atlas of Rural and Small-Town America |
| `nber/cencounts.csv` | Decennial census county counts 1900–2020 (NBER compilation) |
| `algara/pres_county.Rdata` | Algara & Amlani county presidential returns 1868–2020 (Harvard Dataverse) |
| `tonmcg/2024.csv` | County presidential results 2024 (tonmcg GitHub compilation) |
| `apport/apportionment.csv` | Census apportionment tables 1910–2020 |
| `tiger/cb_2023_us_county_500k.*` | Census 2023 cartographic boundary file, counties, 1:500k (`pilots.py` only) |

Every output column, with its source and vintage, is documented in `data/codebook.csv`.

## Reproducibility status

The scripts are restored byte-for-byte from the original bundle. They have not been re-run
against fresh downloads since; publishers revise these files (CMS weekly, ERS and Census on
release schedules), so a re-run today will differ from the committed `data/` where sources
have been updated. The committed tables are the reference for every result in this repo.

Election and apportionment tables are governance context only. They are stripped at load
time by the experiment harness (`tools/harness/denylist.py`, decision D-007) and never reach
a model or the public website.
