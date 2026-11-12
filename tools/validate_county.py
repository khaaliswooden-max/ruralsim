#!/usr/bin/env python3
"""Validation sheet: world (stage/viewer) vs dataset for one pilot county.

Manifest rules: every comparison world-vs-dataset; any mismatch >5% is FLAGGED,
not silently passed. Output: validation/<fips>_<county>_validation.md + .json.
"""
import json, pathlib, sys
import numpy as np
import geopandas as gpd
import pandas as pd
from shapely.geometry import shape, mapping, LineString, MultiLineString

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from county_config import get
C = get(sys.argv[1] if len(sys.argv) > 1 else None)
FIPS = C.fips
W = C.world
RAW, VD = W / "layers_raw", W / "viewer_data"
geom_wgs = C.geom

master = pd.read_csv(REPO / "data" / "county_master.csv", dtype={"fips5": str}, low_memory=False)
m = master[master["fips5"] == FIPS].iloc[0]
cy = pd.read_csv(REPO / "data" / "county_year.csv", dtype={"fips5": str}, low_memory=False)
cy = cy[cy["fips5"] == FIPS]

results = []  # (check, world_value, dataset_value, diff_pct, status, note)
def cmp(name, world, ref, thresh=5.0, note="", exact=False):
    if ref in (None, 0) or (isinstance(ref, float) and not np.isfinite(ref)):
        results.append((name, world, ref, None, "INFO", note or "no dataset reference"))
        return
    diff = abs(world - ref) / abs(ref) * 100
    ok = (world == ref) if exact else diff <= thresh
    results.append((name, world, ref, round(diff, 1), "PASS" if ok else "FLAG", note))

# 1. county polygon area vs land+water area (manifest: within 1%)
g_proj = gpd.GeoSeries([geom_wgs], crs=4326).to_crs(C.utm)
area_sqmi = float(g_proj.area.iloc[0]) / 2.58999e6
ref_area = float(m["land_area_sqmi"]) + float(m["water_area_sqmi"])
cmp("county polygon area (sq mi)", round(area_sqmi, 1), round(ref_area, 1), thresh=1.0,
    note="Census 2023 cartographic polygon vs master land+water area")

# 2. buildings vs housing units (manifest: buildings >= 0.8 * housing_units_2020)
bl = json.loads((VD / "buildings.json").read_text())
hu = float(m["housing_units_2020"])
n_b = len(bl)
status = "PASS" if n_b >= 0.8 * hu else "FLAG"
results.append(("buildings vs housing_units_2020", n_b, int(hu),
                round((n_b - hu) / hu * 100, 1), status,
                f"OSM footprints {n_b} vs {int(hu)} housing units ({n_b/hu*100:.0f}%); "
                "manifest floor is 80% - OSM building completeness in rural counties is partial"))

# 3. hospitals
fac = json.loads((VD / "facilities.json").read_text())
cmp("hospitals placed", len(fac["hospitals"]), int(m["n_hospitals"]), exact=True,
    note="CMS bundle names geocoded via OSM name match, else town centroid (tagged)")

# 4. bridges: stage vs NBI raw extract
nbi = json.loads((RAW / "bridges" / f"nbi_{FIPS}.geojson").read_text())
br = json.loads((VD / "bridges.json").read_text())
cmp("bridges placed", len(br), len(nbi["features"]), exact=True,
    note="FHWA NBI 2024, DMS-parsed coordinates, bounds-checked")
conds = {}
for f in nbi["features"]:
    c = f["properties"].get("bridge_condition") or "?"
    conds[c] = conds.get(c, 0) + 1

# 5. road / rail network length inside county (baseline metrics)
def net_len(path, key_filter=None):
    d = json.loads(pathlib.Path(path).read_text())
    total = 0.0
    gline = []
    for f in d["features"]:
        g = f["geometry"]
        if key_filter and not key_filter(f["properties"]):
            continue
        ls = []
        if g["type"] == "LineString":
            ls = [g["coordinates"]]
        elif g["type"] == "MultiLineString":
            ls = g["coordinates"]
        for part in ls:
            gline.append(LineString(part))
    gs = gpd.GeoSeries(gline, crs=4326)
    gs = gs[gs.intersects(geom_wgs)]
    if len(gs) == 0:
        return 0.0
    clipped = gs.intersection(geom_wgs.buffer(0.001))
    return float(gpd.GeoSeries(clipped, crs=4326).to_crs(C.utm).length.sum()) / 1609.344

road_mi = net_len(RAW / "osm" / "roads.geojson")
rail_mi = net_len(RAW / "rail" / f"rail_ntad_{FIPS}.geojson")
hydro_mi = net_len(RAW / "hydrology" / f"nhd_flowlines_{FIPS}.geojson")
results.append(("road network in county (miles, baseline)", round(road_mi, 1), None, None, "INFO",
                "OSM, clipped to county; no TIGER cross-check yet (Census blocked from build network)"))
results.append(("rail network in county (miles, baseline)", round(rail_mi, 1), None, None, "INFO",
                "BTS NTAD lines intersecting county"))
results.append(("flowline network in county (miles, baseline)", round(hydro_mi, 1), None, None, "INFO",
                "USGS NHD flowlines clipped to county envelope"))

# 6. terrain: stage/viewer grid vs payload DEM
tm = json.loads((VD / "terrain_meta.json").read_text())
grid = np.fromfile(VD / "terrain_grid.f32", dtype=np.float32)
import rasterio
with rasterio.open(next((W / "layers" / "terrain").glob("dem_*_*.tif"))) as src:
    a = src.read(1)
    # mesh is a ~160 m strided subsample of the DEM; compare at the SAME
    # sampling — raw 20 m extremes legitimately fall between mesh nodes
    # (01131 max 175.0 vs mesh 164.2, 2026-11-12; that is smoothing, not error)
    step = max(1, round(160 / (abs(src.transform.a) * 111320)))
    sub = a[::step, ::step]
    ref_mn, ref_mx = float(np.nanmin(sub)), float(np.nanmax(sub))
    raw_mn, raw_mx = float(np.nanmin(a)), float(np.nanmax(a))
    dem_bounds = src.bounds
cmp("terrain min elevation (m)", round(float(grid.min()), 1), round(ref_mn, 1), thresh=5.0,
    note=f"vs DEM at matched ~160 m sampling (raw 20 m min {raw_mn:.1f}); nodata outside clip polygon filled by interpolation in mesh; payload keeps nodata")
cmp("terrain max elevation (m)", round(float(grid.max()), 1), round(ref_mx, 1), thresh=5.0,
    note=f"vs DEM at matched ~160 m sampling (raw 20 m max {raw_mx:.1f}); extremes smooth under mesh resolution")

# 6b. terrain SPATIAL COVERAGE: elevation min/max cannot catch a spatially
# cropped DEM (the 2026-11-12 window-clipping bug passed both while 01131's
# DEM covered only 59% of the county's latitude span). Require the DEM valid-
# data mask to cover >=99% of the county polygon.
from shapely.geometry import box as _box
from rasterio.features import geometry_mask as _gmask
with rasterio.open(next((W / "layers" / "terrain").glob("dem_*_*.tif"))) as src:
    valid = ~np.isnan(src.read(1))
    tf, shp = src.transform, (src.height, src.width)
cpoly = gpd.read_file(REPO / "pilots" / "pilot_county_boundaries.geojson")
cpoly = cpoly[cpoly["fips5"] == FIPS].geometry.iloc[0]
inside = cpoly.intersection(_box(*dem_bounds))
cov_bbox = inside.area / cpoly.area * 100
# finer: rasterize the county onto the DEM grid and test valid cells
cmask = _gmask([mapping(cpoly)], out_shape=shp, transform=tf, invert=True)
cov_cells = float((valid & cmask).sum() / max(cmask.sum(), 1) * 100)
cov = min(cov_bbox, cov_cells)
cmp("terrain coverage of county polygon (%)", round(cov, 1), 100.0, thresh=1.0,
    note="DEM valid cells over county polygon; a crop at a 1-degree tile edge fails this")

# 7. population series vs county_year
pop = json.loads((VD / "population_series.json").read_text())
mism = []
for p in pop:
    rows = cy[(cy["year"] == p["year"])]
    if len(rows) and int(rows.iloc[0]["population"]) != int(p["population"]):
        mism.append(p["year"])
results.append(("population series 2010-2024 vs county_year", len(pop), len(pop), 0,
                "PASS" if not mism else "FLAG",
                f"mismatch years: {mism}" if mism else "all years match county_year exactly"))

# 8. water systems: SDWIS systems vs placed markers
wsy = pd.read_csv(RAW / "water_systems" / f"sdwis_systems_{FIPS}.csv", dtype=str)
n_sys = len(wsy)
cmp("water systems placed", len(fac["water_systems"]), n_sys, thresh=5.0,
    note="EPA SDWIS has no coordinates; markers placed at served-town centroids - "
         "systems whose town name did not match OSM places are unplaced (see DECISIONS)")

# 9. power: OSM generators vs EIA-860 plants
plants_csv = RAW / "grid" / f"eia860_plants_{FIPS}.csv"
eia = pd.read_csv(plants_csv, dtype=str) if plants_csv.exists() else pd.DataFrame()
pp = json.loads((VD / "power_points.json").read_text())
results.append(("OSM generators vs EIA-860 plants", len(pp["generators"]), len(eia), None, "INFO",
                "OSM counts individual wind turbines; EIA-860 counts plant-level records - "
                "different granularity, not an error; flagged for reader awareness"))

# ---- write report ----
VAL = REPO / "validation"; VAL.mkdir(exist_ok=True)
cname = W.name
lines = [f"# Validation sheet — {cname}", "",
         "World vs dataset, per build manifest. Mismatch >5% => FLAG. ",
         "Negative results are reported with the same prominence as passes.", "",
         "| check | world | dataset | diff % | status | note |",
         "|---|---|---|---|---|---|"]
n_flag = 0
for name, wv, rv, dp, st, note in results:
    if st == "FLAG":
        n_flag += 1
    lines.append(f"| {name} | {wv} | {rv} | {dp if dp is not None else '—'} | **{st}** | {note} |")
lines += ["", f"**Flags: {n_flag}** of {len(results)} checks", "",
          "## Bridge condition mix (NBI 2024)",
          "", json.dumps(conds), "",
          "## Layer provenance summary", ""]
lm = json.loads((VD / "layer_meta.json").read_text())
for k, v in lm.items():
    lines.append(f"- **{k}**: {v.get('source')} — {v.get('provenance')} — {v.get('vintage')}"
                 + (f" — {v.get('notes')}" if v.get('notes') else ""))
(VAL / f"{cname}_validation.md").write_text("\n".join(lines))
(VAL / f"{cname}_validation.json").write_text(json.dumps(
    [{"check": n, "world": w, "dataset": r, "diff_pct": d, "status": s, "note": nt}
     for n, w, r, d, s, nt in results], indent=2))
print("\n".join(lines[:40]))
print("...")
print("written:", VAL / f"{cname}_validation.md")
