# Validation sheet — 54047_mcdowell_wv

World vs dataset, per build manifest. Mismatch >5% => FLAG. 
Negative results are reported with the same prominence as passes.

| check | world | dataset | diff % | status | note |
|---|---|---|---|---|---|
| county polygon area (sq mi) | 534.7 | 534.9 | 0.0 | **PASS** | Census 2023 cartographic polygon vs master land+water area |
| buildings vs housing_units_2020 | 8938 | 9344 | -4.3 | **PASS** | OSM footprints 8938 vs 9344 housing units (96%); manifest floor is 80% - OSM building completeness in rural counties is partial |
| hospitals placed | 1 | 1 | 0.0 | **PASS** | CMS bundle names geocoded via OSM name match, else town centroid (tagged) |
| bridges placed | 225 | 225 | 0.0 | **PASS** | FHWA NBI 2024, DMS-parsed coordinates, bounds-checked |
| road network in county (miles, baseline) | 1694.4 | None | — | **INFO** | OSM, clipped to county; no TIGER cross-check yet (Census blocked from build network) |
| rail network in county (miles, baseline) | 129.3 | None | — | **INFO** | BTS NTAD lines intersecting county |
| flowline network in county (miles, baseline) | 1344.9 | None | — | **INFO** | USGS NHD flowlines clipped to county envelope |
| terrain min elevation (m) | 233.2 | 233.2 | 0.0 | **PASS** | vs DEM at matched ~160 m sampling (raw 20 m min 233.1); nodata outside clip polygon filled by interpolation in mesh; payload keeps nodata |
| terrain max elevation (m) | 1074.5 | 1074.5 | 0.0 | **PASS** | vs DEM at matched ~160 m sampling (raw 20 m max 1083.7); extremes smooth under mesh resolution |
| terrain coverage of county polygon (%) | 100.0 | 100.0 | 0.0 | **PASS** | DEM valid cells over county polygon; a crop at a 1-degree tile edge fails this |
| population series 2010-2024 vs county_year | 15 | 15 | 0 | **PASS** | all years match county_year exactly |
| water systems placed | 21 | 183 | 88.5 | **FLAG** | EPA SDWIS has no coordinates; markers placed at served-town centroids - systems whose town name did not match OSM places are unplaced (see DECISIONS) |
| OSM generators vs EIA-860 plants | 2 | 0 | — | **INFO** | OSM counts individual wind turbines; EIA-860 counts plant-level records - different granularity, not an error; flagged for reader awareness |

**Flags: 1** of 13 checks

## Bridge condition mix (NBI 2024)

{"F": 145, "P": 71, "G": 9}

## Layer provenance summary

- **terrain**: USGS 3DEP National Elevation Dataset 1/3 arc-second (~10 m) — observed — 2012-2024 tile vintages — Stage/viewer mesh at ~160 m; cells outside county-buffer clip filled by GDAL fillnodata interpolation (derived); interior cells observed; 20 m GeoTIFF payload retains nodata
- **boundaries**: Census 2023 cartographic county polygon + TIGER AIANNH (via USFS EDW) — observed — 2023/2024 — tribal jurisdiction marked per guardrails
- **roads**: OpenStreetMap via Overpass — observed — retrieved 2026-11-11 — TIGER cross-check deferred (Census www2 blocked from build network)
- **rail**: BTS NTAD North American Rail Network — observed — NTAD current
- **hydrology**: USGS NHD flowlines+waterbodies (ArcGIS REST) — observed — current — flowlines clipped to county envelope; buffer-zone flowlines partial
- **grid**: OSM power=* (cross-check per manifest); EIA-860/861 tabular in layers_raw/grid — observed — 2024-2026 — EIA Atlas transmission REST deferred; feeders NOT public - to be synthesized as 'assumed'
- **buildings**: OpenStreetMap building footprints — observed (footprint), derived (height) — retrieved 2026-11-11 — heights inferred from footprint class per manifest rule; MS footprints fallback not needed
- **facilities**: CMS Hospital General Information (bundle) + OSM schools + EPA SDWIS — observed (facility attrs); derived (some positions) — 2024-2026 — NCES EDGE school layer deferred (nces.ed.gov blocked); OSM schools interim
- **bridges**: FHWA National Bridge Inventory 2024 — observed — 2024 — condition codes G/F/P from NBI BRIDGE_CONDITION
- **land_tenure**: USGS PAD-US 3.0 Fee Manager — observed — 3.0 — tribal fee parcels overlap tribal_boundaries; jurisdiction marker authoritative there