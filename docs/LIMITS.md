# RuralSim — LIMITS

What this system is, what it is not, and where every shortcut lives.
Read this before trusting any number the world model produces.

## 1. What the world is

A **synthetic, physically grounded test environment** for stress-testing software,
hardware, robotics, and energy-compute infrastructure before real deployment. It is
built from observed public datasets wherever the network allowed, and every value
carries a provenance tag: `observed | derived | calibrated | assumed | hypothetical`.

It is **not** a digital twin of record. It is not updated in real time. It must never
be cited as authoritative about any real place, person, or parcel.

## 2. Hard limits (by design, non-negotiable)

- **No real people.** All persons, households, and agents are synthetic. No
  address-level records are collected, stored, or emitted. The finest resolution is
  the Census tract/block-group aggregate.
- **Election/party variables are read-only governance context.** They never enter the
  RQLI objective, any optimizer, or any agent targeting rule. Enforced in code
  (denylist `political_variables_excluded`, D-007), not by convention.
- **Tribal data sovereignty is a constraint, not a theme.** Tribal lands are marked as
  jurisdiction; no proxy modeling of tribal populations or assets without an explicit
  `assumed` label; tribal data is included only where the holding agency publishes it
  for public use.
- **Robotics-with-humans experiments are simulation-only**, with safety-incident
  logging; nothing here certifies a machine for operation near people.
- **No intervention relocates or removes residents.** Recommendations are decision
  support only: they require community consent, engineering review, and regulatory
  approval before any real-world action.
- **Nothing is invented and presented as real.** Where a source was unreachable, the
  layer is absent (D-013 flood), substituted with a documented stand-in (D-010
  climate, D-011 land cover), or flagged (D-015 water-system locations) — never
  silently fabricated.

## 3. Known data gaps and degradations (as of 2026-11-11)

| Layer | Limitation | Tag |
|---|---|---|
| Flood hazard | **Absent.** FEMA NFHL unreachable from the build network. Flood experiments are blocked, not approximated (D-013) | — |
| Schools | OSM `amenity=school` interim; NCES EDGE blocked; completeness unknown, likely partial in rural counties (D-014) | observed (partial) |
| Transmission | OSM `power=line`; EIA Atlas REST deferred. **Distribution feeders are not public anywhere** — synthesized at experiment time | observed / assumed |
| Water systems | EPA SDWIS has no coordinates; systems whose served town has no OSM place match are **listed but unplaced** (28/37 in 31173, 35/38 in 16081) (D-015) | observed attrs, derived position |
| Terrain | All five pilots refetched at full 1/3 arc-second (~10 m) after the D-024 window-crop repair; the 1″ PC fallback (D-021) remains in code for future builds | observed |
| Land cover | CDL (crop-focused) doubles as land cover; non-ag classes coarse (D-011). CropScape outage forced Planetary Computer CDL ≤2021 for later pilots (D-017) | observed |
| Climate | Open-Meteo ERA5 reanalysis at county centroid, not NOAA station normals (D-010); context layer, not engineering design values | observed (modelled) |
| Building heights | Inferred from footprint class per manifest rule, not measured | derived |
| Roads | OSM; TIGER cross-check deferred (Census www2 blocked) | observed |
| 2024 election context | Provisional vintage; fenced per §2 | observed, read-only |

## 4. Validation limits

- Validation compares **world vs source dataset** (counts, areas, terrain ranges,
  population series). It does not and cannot certify that the source dataset itself is
  correct, current, or complete.
- Validation must cover **spatial coverage**, not only value statistics: a DEM cropped
  at a tile boundary passed elevation min/max checks while missing half the county
  (D-024, caught by render review 2026-11-12). The validator now checks terrain
  coverage of the county polygon (≥99%); the same principle applies to any layer —
  a PASS on statistics alone is not evidence of complete spatial extent.
- OSM completeness varies by region and theme; a PASS against an OSM baseline inherits
  OSM's own gaps. Where a manifest floor exists (buildings ≥80% of housing units) it is
  checked; where none exists, counts are reported INFO with no threshold.
- A mismatch >5% is a FLAG, not a silent fix. Flags ship in the validation sheet with
  the same prominence as passes. Negative results (e.g., zero rail, zero water towers)
  are reported, not suppressed.
- RQLI is reported as a distribution (p10/p50/p90/mean + worst-off decile), never as a
  mean alone. Any run that collapses it to a single number is invalid.

## 5. Compute and reproducibility limits

- The sandbox `/mnt` mount intermittently drops freshly written files (observed
  2026-11-11, D-019). Builds verify expected outputs per step and retry; a green build
  means outputs verified at build time, not a guarantee about later mount state.
- Remote APIs used by the fetchers (TNM, Overpass mirrors, CropScape, Envirofacts,
  Open-Meteo, Planetary Computer, ArcGIS REST) are outside our control. Outages are
  handled by documented fallback, absence, or retry — never by silent substitution.
- One-command rebuild reproduces the *pipeline*; exact bytes can differ when upstream
  data changes between runs. Vintages are recorded per layer in `_meta.json`.

## 6. What would invalidate a result

Each assumption carries an "invalidated by" clause in DECISIONS.md. The big ones:
access to NOAA/NCEI (climate), mrlc.gov NLCD (land cover), FEMA NFHL (flood),
NCES EDGE (schools), a tribal-data-sharing agreement (tribal layers beyond public
agency publications), and paid utility interconnection data (feeders).

## 7. Experiment harness limits (v1, 2026-11-12)

- Only two of ten seed cards have domain engines (EXP-0002 telehealth, EXP-0006 drone
  reachability). The rest are registered `engine_pending`; power-flow, water, robotics
  dynamics and economy engines are not implemented. No card may report a result without
  its engine.
- Connectivity, outage, broadband-cost and energy-cost indicators are `assumed`
  placeholders (FCC BDC and EIA reliability layers are not in the pilot bundle). Any
  result depending on them carries provenance floor `assumed` and cannot be promoted
  without sensitivity analysis (card schema rule).
- Synthetic households sit on OSM building centroids; where OSM buildings are sparse
  (e.g. Wilcox 13% of housing units), the synthetic population covers only mapped
  settlement and under-represents dispersed rural households.
- Road travel times use assumed class speeds and the observed OSM graph; disconnected
  OSM subgraphs make some households honestly unreachable (reported as a share).
- Screening runs (<20 seeds) are never findings; promotion-eligible runs (20 seeds)
  still require full-physics confirmation per the promotion rule, and all v1 engines
  are reduced-order — treat every 20-seed result in the first batch as indicative, not
  as a finding. Large runs are gated at G3 (owner approval, granted 2026-11-12 with
  "no preference" for the Tier A build and the full experiment batch).
- Tier A is statistical only: no geometry, no households, no simulation. County-level
  broadband availability, grid reliability (SAIDI), and water-violation series are not
  in the national bundle; Tier A cannot speak to them.
