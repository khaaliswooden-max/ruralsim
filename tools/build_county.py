#!/usr/bin/env python3
"""One-command county rebuild: fetch -> stage -> validate.

    python3 tools/build_county.py [fips5]     # default 31173

Fetch tools are idempotent (skip-existing), so a rebuild only re-fetches what
is missing. Delete a layer's raw file to force re-fetch of that layer.

Every tool takes the fips5 argument; county-specific settings (UTM zone, EPA
region, bbox, boundary, world directory) come from tools/county_config.py. Any
current U.S. county can be built; non-pilot boundaries are cached in counties/.
"""
import pathlib, subprocess, sys

REPO = pathlib.Path(__file__).resolve().parent.parent
FIPS = sys.argv[1] if len(sys.argv) > 1 else "31173"

PIPELINE = [
    # order matters: terrain first (stage draping needs the DEM); arcgis tribal
    # before water (water checks tribal lands to decide on tribal-primacy query)
    "tools/fetch_terrain.py",
    "tools/fetch_osm.py",            # roads/buildings/schools/healthcare/power/places/water/food_shops/bridges
    "tools/fetch_arcgis_layers.py",  # tribal, PAD-US, rail, NHD
    "tools/fetch_bridges.py",
    "tools/fetch_grid.py",
    "tools/fetch_water.py",
    "tools/fetch_climate.py",
    "tools/fetch_cropland.py",
    "tools/build_stage.py",
    "tools/validate_county.py",
]

OSM_THEMES = ["roads", "buildings", "schools", "healthcare", "power",
              "places", "water", "waterways", "food_shops", "bridges"]
WORLD = next((REPO / "worlds").glob(f"{FIPS}_*")) if any((REPO / "worlds").glob(f"{FIPS}_*")) else None

# expected payload globs per script, relative to the world dir. The /mnt mount
# occasionally drops a freshly written file (observed 2026-11-11, four files
# across two runs); after each step we verify outputs and retry the step.
EXPECT = {
    "tools/fetch_terrain.py": ["layers/terrain/dem_*_*.tif"],
    "tools/fetch_osm.py": [f"layers_raw/osm/{t}.geojson" for t in OSM_THEMES],
    "tools/fetch_arcgis_layers.py": ["layers_raw/tribal/tribal_*.geojson",
                                     "layers_raw/land_tenure/land_tenure_*.geojson",
                                     "layers_raw/rail/rail_ntad_*.geojson",
                                     "layers_raw/hydrology/nhd_flowlines_*.geojson",
                                     "layers_raw/hydrology/nhd_waterbodies_*.geojson"],
    "tools/fetch_bridges.py": ["layers_raw/bridges/nbi_*.geojson"],
    # county-file globs are FIPS-specific: eia860_plants_<ST>.csv (state extract)
    # also matches eia860_plants_*.csv and would mask a dropped county file
    "tools/fetch_grid.py": [f"layers_raw/grid/eia860_plants_{FIPS}.csv",
                            f"layers_raw/grid/eia861_territory_{FIPS}.csv"],
    "tools/fetch_water.py": ["layers_raw/water_systems/sdwis_systems_*.csv",
                             "layers_raw/water_systems/sdwis_violations_*.csv"],
    "tools/fetch_climate.py": ["layers_raw/climate/climate_normals_1991_2020_monthly.csv"],
    "tools/fetch_cropland.py": ["layers/land_cover/cdl_*_*.tif"],
    "tools/build_stage.py": ["stage/*.usda", "viewer_data/layer_meta.json", "viewer/index.html"],
    "tools/validate_county.py": [],
}

def outputs_ok(script):
    world = next((REPO / "worlds").glob(f"{FIPS}_*"), None)
    if world is None:
        return False
    missing = [g for g in EXPECT.get(script, []) if not list(world.glob(g))]
    for g in missing:
        print(f"  MISSING after {script}: {g}")
    return not missing

import os
for script in PIPELINE:
    for attempt in range(3):
        print(f"=== {script} {FIPS} (attempt {attempt+1})")
        r = subprocess.run([sys.executable, str(REPO / script), FIPS], cwd=REPO)
        os.sync()
        if r.returncode != 0:
            print(f"FAILED: {script} (exit {r.returncode}) — stop; fix and rerun (fetch is resumable)")
            sys.exit(r.returncode)
        if outputs_ok(script):
            break
        print(f"  outputs incomplete after {script}; retrying step")
    else:
        print(f"FAILED: {script} outputs still incomplete after 3 attempts")
        sys.exit(1)
print("county build complete:", FIPS)
