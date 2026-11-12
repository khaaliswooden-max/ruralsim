#!/bin/bash
# Refetch terrain for pilot counties whose DEM fails the coverage check
# (D-024), then restage + revalidate. Restart-safe: coverage is checked BEFORE
# anything is deleted, so an already-fixed county is skipped. Sequential —
# one county at a time (D-019). Logs to /tmp/reterrain_all.log.
set -u
cd "$(dirname "$0")/.."
COV_CHECK='
import sys, glob, numpy as np, rasterio
sys.path.insert(0, "tools")
from county_config import get
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds
from shapely.geometry import mapping, box
import geopandas as gpd
C = get(sys.argv[1])
dem = glob.glob(f"worlds/{C.fips}_*/layers/terrain/dem_{C.fips}_*.tif")
if not dem: sys.exit(1)
with rasterio.open(dem[0]) as src:
    valid = ~np.isnan(src.read(1)); tf, shp = src.transform, (src.height, src.width); b = src.bounds
cp = C.geom  # pilot or any county, from county_config
cov_bbox = cp.intersection(box(*b)).area / cp.area * 100
cmask = geometry_mask([mapping(cp)], out_shape=shp, transform=tf, invert=True)
cov = min(cov_bbox, float((valid & cmask).sum() / max(cmask.sum(), 1) * 100))
print(f"  {C.fips} DEM coverage {cov:.1f}%")
sys.exit(0 if cov >= 99.0 else 1)
'
for FIPS in ${@:-31173 16081 54047 20019 01131}; do
  if python3 -c "$COV_CHECK" $FIPS; then
    echo "=== $FIPS terrain OK, skipping refetch $(date +%H:%M:%S)"
  else
    echo "=== terrain refetch $FIPS $(date +%H:%M:%S)"
    rm -f worlds/${FIPS}_*/layers/terrain/dem_${FIPS}_*.tif
    tries=0
    until [ $tries -ge 4 ]; do
      python3 tools/fetch_terrain.py $FIPS && break
      tries=$((tries+1)); echo "  fetch_terrain $FIPS failed (try $tries); retrying in 30s"; sleep 30
    done
    ls worlds/${FIPS}_*/layers/terrain/dem_${FIPS}_*.tif >/dev/null || { echo "  DEM STILL MISSING for $FIPS"; continue; }
  fi
  # restage if the stage predates the DEM (or always after a refetch)
  DEM=$(ls worlds/${FIPS}_*/layers/terrain/dem_${FIPS}_*.tif | head -1)
  STAGE=$(ls worlds/${FIPS}_*/stage/${FIPS}_*.usda | head -1)
  if [ "$DEM" -nt "$STAGE" ]; then
    echo "=== restage $FIPS $(date +%H:%M:%S)"
    python3 tools/build_stage.py $FIPS || { echo "  build_stage FAILED $FIPS"; continue; }
    echo "=== revalidate $FIPS $(date +%H:%M:%S)"
    python3 tools/validate_county.py $FIPS || echo "  validate FAILED $FIPS"
  else
    echo "=== $FIPS stage already current, verifying validation $(date +%H:%M:%S)"
    python3 tools/validate_county.py $FIPS || echo "  validate FAILED $FIPS"
  fi
done
echo "ALL DONE $(date +%H:%M:%S)"
