# RuralSim — ARCHITECTURE.md

Version 0.1 · 2026-11-11 · status: Gate G2 (first pilot county built + validated)

## 1. What this is

A physically grounded 3D world model of rural American counties, built to test
software / hardware / robotics / energy-compute infrastructure *before* real
deployment. Three scope tiers:

- **Tier A — national statistical twin.** 3,144 current counties
  (`geography_vintage == "2024"`), no 3D. Data profiled at Gate G1.
- **Tier B — five pilot 3D county twins**, built smallest-first:
  `31173 Thurston NE → 16081 Teton ID → 54047 McDowell WV → 20019 Chautauqua KS → 01131 Wilcox AL`.
- **Tier C — procedural extension** over Tier A statistics (not started).

## 2. Pipeline (per county)

```
pilots/pilot_county_boundaries.geojson            (canonical county polygon, fips5)
        │
        ▼
tools/fetch_*.py   ── observed public sources ──►  worlds/<fips>_<name>/layers_raw/
  fetch_terrain.py     USGS TNM 3DEP NED 1/3″ DEM      (GeoTIFF / CSV / GeoJSON + _meta.json)
                       └─ throughput probe falls back to PC 3dep-seamless 1″ COG (D-021)
  fetch_osm.py         OpenStreetMap via Overpass      per-layer provenance:
                       └─ curl GET transport (D-022), quadrant bbox splitting on 504s
  fetch_bridges.py     FHWA NBI 2024                   source · license · vintage ·
  fetch_grid.py        EIA-860/861                     observed|derived|calibrated|assumed
  fetch_water.py       EPA SDWIS (Envirofacts)
  fetch_climate.py     Open-Meteo ERA5 1991–2020 (D-010)
  fetch_cropland.py    USDA CropScape CDL (D-011), PC usda-cdl fallback (D-017)
  fetch_arcgis_layers.py  USFS EDW tribal lands, PAD-US 3.0, BTS NTAD rail, USGS NHD
        │  (all fetches are idempotent: skip-existing; payloads staged in /tmp then
        │   copied to /mnt under a settle-and-heal watch against portal-mount drops,
        │   D-019/D-023)
        ▼
tools/build_stage.py ──► worlds/<fips>_<name>/stage/<fips>_<name>.usda
        │                OpenUSD, Y-up, metersPerUnit=1, ENU metres
        │                (UTM zone per county, origin = county centroid)
        │                one sublayer per source; root carries customLayerData
        │                {fips, ENU origin, fidelity tier, layer provenance, guardrails}
        ├──► worlds/<fips>_<name>/viewer_data/*.json  (compact ENU bundles)
        ▼
worlds/<fips>_<name>/viewer/index.html   three.js viewer (vendored, offline):
        layer toggles with per-layer provenance tags, time scrubber (population
        context 2010–2024), decision-support disclaimer, ?capture=1 headless mode
        ▼
tools/validate_county.py ──► validation/<county>_validation.{md,json}
        world-vs-dataset checks; any mismatch >5% is FLAGGED, never hidden
```

One-command rebuild: `python3 tools/build_county.py <fips5>` (fetch → stage → validate).

## 3. Coordinate & geometry contract

- **fips5 is a zero-padded 5-char string everywhere.** Joins on integer FIPS are bugs.
- Stage coordinates: local ENU metres, Y-up, `metersPerUnit = 1`, origin recorded in
  `customLayerData.enu_origin_wgs84` + UTM EPSG code. Terrain is 1:1.
- Viewer adds ×4 vertical exaggeration as a labelled display aid only.
- All overlays are **draped** on the observed DEM (D-016). Nothing floats at a
  convention height; nothing is invented to fill gaps (D-015).
- Terrain mesh nodata (outside the county-buffer clip) is interpolated and tagged
  `derived`; the payload GeoTIFF keeps true nodata.

## 4. Data lineage & fidelity tiers

Every layer carries `{source, license, vintage, provenance, notes}` in
`layer_meta.json` (viewer), `customLayerData` (USD stage), and `_meta.json`
(layers_raw). Provenance vocabulary: `observed | derived | calibrated | assumed | hypothetical`.

Pilot 1 (31173) fidelity: **T1 geometry** — 10 layers, all observed except building
heights (`derived`, class-inferred), mesh fill cells (`derived`), hospital/water
positions without OSM match (`derived`, town centroid). Feeders, broadband, solar
resource: `assumed` placeholders until keys/feeders exist (D-002, D-014).

## 5. Guardrails (persist across tiers; enforced in code where possible)

- Synthetic people, never real ones; no address-level records.
- Election/party variables are read-only governance context — **denylisted** from the
  RQLI objective, optimizer features, and agent targeting (D-007).
- Tribal jurisdiction explicitly marked (Winnebago + Omaha reservations in 31173);
  tribal layers observed-only; tribal data sovereignty is a constraint.
- Robotics-with-humans experiments are simulation-only with safety-incident logging.
- No intervention relocates or removes residents; recommendations are decision
  support requiring community consent, engineering review, regulatory approval.
- RQLI reported as a distribution (p10/p50/p90/mean + worst-off decile), never mean only.
- Negative results get the same prominence as wins (validation sheet shows FLAGs first-class).

## 6. Known limits (pilot 1)

- Buildings: 1,225 OSM footprints vs 2,283 housing units (54%) — rural/tribal OSM
  completeness gap; FLAGGED in validation, not patched with invented buildings.
- Water systems: 9/37 placed (SDWIS has no coordinates); rest listed but unplaced (D-015).
- No flood layer (FEMA NFHL unreachable, D-013); TIGER road cross-check deferred
  (Census hosts blocked); NCES schools deferred (D-014).
- Climate is centroid reanalysis, not station normals (D-010); land cover is CDL,
  crop-focused (D-011).
- OSM "generators" count individual wind turbines; EIA-860 counts plants — granularity
  difference recorded, not reconciled.
- Headless render verification requires xvfb + swiftshader; viewer `?capture=1`
  flattens WebGL via toDataURL (screenshots don't composite GL surfaces directly).

## 7. Repo layout

```
data/         bundled handoff tables (county_master, county_year, county_profile,
              county_decade, facility_hospital, codebook, fenced election/power)
pilots/       pilot_counties.csv + pilot_county_boundaries.geojson
specs/        geodata_manifest.yaml, rqli_spec.yaml (RQLI domains, hard constraints)
experiments/  card schema, ten seed cards, ledger/ (immutable run records),
              baseline_cache/ (card-independent county baselines)
national/     Tier A statistical twin: tier_a_county_stats.csv (3,163 counties),
              provenance, validation, summary (built by tools/build_national.py)
tools/        fetch_*.py, build_stage.py, validate_county.py, build_county.py,
              build_national.py, harness/ (denylist, households, roads, rqli,
              engines, constraints, run_experiment)
worlds/<fips>_<name>/{layers_raw, layers, stage, viewer_data, viewer, renders}
validation/   per-county validation sheets (md + json)
docs/         PROMPT.md, README.md, DATA_PROFILE.md, DECISIONS.md, ARCHITECTURE.md
```

## 8. Tier A + experiment harness (added 2026-11-12, D-025)

Tier A (national statistical twin, 3,163 rows / 3,144-county target universe, no 3D) is
built by `tools/build_national.py` from the bundled tables only — no fetching. Political
columns are stripped at load; every output column's provenance is in
`national/tier_a_provenance.json`; 8/8 validation checks pass (see
`national/tier_a_validation.json`).

The harness (`tools/harness/`) runs experiment cards: synthetic households (never real
people) on observed building centroids, road-graph travel engine on observed OSM
geometry, RQLI scored per `specs/rqli_spec.yaml` as a distribution only, six hard
constraints checked per run, ledger records immutable under `experiments/ledger/`.
Baselines depend only on (county, seed) and are shared across cards via
`experiments/baseline_cache/`. Engines are reduced-order with every non-observed
parameter tagged; cards without an engine are registered `engine_pending`, never
skipped silently.
