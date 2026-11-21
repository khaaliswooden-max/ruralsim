# AI-infrastructure engine — energy-layer inventory of three published counties

Rollout step 2, first task (D-100). Read 2026-11-21 from the public R2 snapshots
listed in `worlds/index.json`; nothing was rebuilt. Counts are inside the county
polygon (`viewer_data/boundaries.json`, ENU) unless marked "bbox", which means the
buffered fetch box the layer was clipped to.

| County | fips5 | RUCC 2023 | Snapshot | Validation |
|---|---|---|---|---|
| Wilcox AL | 01131 | 9 (nonmetro) | 20261118T014023Z-51fd9fb | 8 pass, 1 flag (water systems 5 of 6 placed) |
| Licking OH | 39089 | 1 (metro) | 20261120T183038Z-6f61b6f | 9 pass, 0 flag |
| Pottawattamie IA | 19155 | 2 (metro) | 20261120T061502Z-c905991 | 9 pass, 0 flag |

**Only Wilcox is in the engine's target population** (nonmetro). Licking and
Pottawattamie are both on step 3's back-test candidate list, so they are inventoried
here but must not be used to tune any engine parameter (spec rule `no_tuning_on_backtest_sites`).

## Misses first

1. **No distribution feeders anywhere.** OSM `minor_line`: Wilcox 0 km, Pottawattamie
   37 km (untagged voltage), Licking 138 km — and Licking's is tagged 69 kV, which is
   subtransmission, not a feeder. 1,044 / 1,918 / 2,580 `pole` points (bbox) exist with
   no lines joining them. Feeder topology is not in the published data and will not be.
2. **EIA-860 file has no capacity.** `fetch_grid.py` reads only the `Plant` sheet: location,
   utility, balancing authority, grid voltage, water source. No nameplate MW, technology
   or status (those are in the `3_1_Generator` sheet of the same zip). The docstring says
   "plant+generator tables"; the code reads one.
3. **EIA-861 file has no co-op flag and no rates.** The territory CSV has six columns
   (year, utility number, name, short-form flag, state, county). The docstring and the
   step-2 brief both say co-ops are flagged; they are not. Ownership is in
   `Utility_Data_2024`, rates and customers in `Sales_Ult_Cust_2024`, both in the
   `f8612024.zip` already downloaded.
4. **No retail service-territory polygons.** Each county is served by 4–8 utilities
   (below); nothing says which one serves a given point. HIFLD's territory layer is gone.
5. **No humidity, dew point or wet-bulb** in any climate file. Normals are monthly
   Tmax/Tmin/precip (nClimDiv; Wilcox still on its pilot ERA5 normals); the optional daily
   series has Tmax, Tmin, precip, snowfall, max wind. Evaporative cooling cannot be sized.
6. **No streamflow.** NHD flowlines carry name, ftype, fcode, reachcode, length — no
   discharge. Surface-water availability cannot be estimated from published layers.
7. **SDWIS has no capacity or population served.** Wilcox and Licking publish 13 columns
   (no population, no source type). Pottawattamie publishes 57 columns, but every
   population, source-type, connection and contact column is empty (headers only). No
   contact data is exposed; the empty columns are a schema inconsistency for step 1.
8. **No flood layer** (D-013) and **no broadband layer** (D-002) in any county.
9. **Wilcox is on pilot-era raw layers.** Its 2026-11-18 snapshot republishes OSM from
   Overpass (2026-11-11), climate normals from ERA5 and CDL 2021; Licking and
   Pottawattamie are on Geofabrik OSM, nClimDiv and CDL 2025.

## Grid layers

### EIA-860 plants in county (`layers_raw/grid/eia860_plants_<fips>.csv`, 42 columns, Plant sheet)
| County | Plants | Content |
|---|---|---|
| Wilcox | 2 | Millers Ferry (USACE hydro, 115 kV, Alabama River); International Paper Pine Hill Mill (industrial CHP, Alabama River) |
| Licking | 1 | Denison Solar Array (AEP Onsite Partners, 12.47 kV) |
| Pottawattamie | 2 | Walter Scott Jr Energy Center (MidAmerican, 345/161/69 kV, Missouri River + wells); Walnut Wind Farm |

State files: AL 104, OH 262, IA 331 plants. Useful fields for the engine: `Grid Voltage (kV)` 1–3,
`Balancing Authority Code` (SOCO, PJM, MISO), `NERC Region`, `Name of Water Source`,
`Transmission or Distribution System Owner`. Plant-to-county match is a substring match on
the county name (`str.contains`), which can over-match (e.g. "Clay" in "Clayton"); worth a
step-1 look.

### EIA-861 utilities serving the county (`eia861_territory_<fips>.csv`)
| County | Utilities |
|---|---|
| Wilcox | Alabama Power; Black Warrior EMC; Pioneer Electric Coop; Clarke-Washington EMC (4) |
| Licking | Duke Energy Ohio; Frontier Power; Guernsey-Muskingum El Coop; Licking Rural Electric; Consolidated Cooperative; Ohio Power (AEP); South Central Power (7) |
| Pottawattamie | Atlantic Municipal; Harrison County RREC; MidAmerican; City of Neola; Nishnabotna Valley REC; Omaha Public Power District; City of Shelby; Waverly Municipal Elec Utility (8) |

Co-op status is readable from the names here, not from a field. Waverly Municipal is an
unexpected entry for Pottawattamie and is unverified.

### OSM power (`layers_raw/osm/power.geojson`; viewer `power_lines.json` carries `kind`, `voltage`)
| | Wilcox | Licking | Pottawattamie |
|---|---|---|---|
| Lines ≥345 kV, km in county | 0 | 247 (765 kV present in bbox) | 147 |
| Lines 100–344 kV, km | 94 (115 kV) | 250 (138 kV) | 50 (161 kV) |
| Lines <100 kV, km | 100 (46 kV) | 32 + 138 minor (69 kV) | 220 (69 kV) |
| Lines, voltage untagged, km | 0 | 10 | 38 |
| Substations in county (of bbox) | 16 (of 30) | 61 (of 96) | 36 (of 82) |
| Substation voltage tagged (bbox) | 30 of 30 | 93 of 96 | 76 of 82 |
| Substation operator tagged (bbox) | 10 of 30 | 46 of 96 | 49 of 82 |
| Generators in county | 3 hydro | 225 solar (panel ways) | 102 wind, 2 coal, 1 solar |

Voltage tagging is good enough to classify every line and substation by voltage class.
Ratings, impedance, conductor and circuit count are absent or sparse; substations have no
transformer capacity. Line endpoints do not reliably coincide with substation polygons, so a
network graph needs endpoint snapping (tolerance to be set in the engine PR). Licking's OSM
names two substation operators that are data-center owners — a back-test signal for step 3,
not an input here.

## Other layers the modules read

| Layer | Wilcox | Licking | Pottawattamie | Gap for the engine |
|---|---|---|---|---|
| Terrain | 3DEP 1/3″ | 3DEP 1/3″ | 3DEP 1/3″ | none for siting; flood needs NFHL or a decision (D-013) |
| NHD flowlines / waterbodies (bbox) | 15,366 / 3,974 (ArcGIS, pilot) | 5,219 / 3,164 (R2 copy) | 7,368 / 1,532 (R2 copy) | no discharge; Wilcox file has 15 attributes, others 6 |
| Named major river | Alabama River | Licking River forks | (Missouri River at Walter Scott, outside NHD top names) | — |
| SDWIS systems: active / CWS | 6 / 10 | 87 / 59 | 32 / 22 | no capacity, no population served |
| EPA service-area polygons | yes | yes | yes | community systems only for most |
| Climate normals | ERA5 (pilot) | nClimDiv | nClimDiv | no humidity |
| Daily series 1991–2020 | present | present | present | no humidity, no radiation |
| Land cover | CDL 2021 | CDL 2025 | CDL 2025 | — |

Source gaps (`layers_raw/_source_gaps.json`): none recorded in any of the three.
