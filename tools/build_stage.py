#!/usr/bin/env python3
"""Assemble the OpenUSD stage for one pilot county (fips5 argument) from fetched layers.

Scene format: OpenUSD, one stage per county, one sublayer per data source.
Coordinates: ENU metres. Projection: the county's UTM zone (tools/county_config.py); origin = county
centroid (recorded as customData). Every layer carries provenance metadata.
Also exports a compact JSON scene bundle per layer for the web viewer.
"""
import json, pathlib, datetime, sys
import numpy as np
import geopandas as gpd
from shapely.geometry import mapping
import rasterio
from pxr import Usd, UsdGeom, Gf, Sdf

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from county_config import get
C = get(sys.argv[1] if len(sys.argv) > 1 else None)
FIPS = C.fips
COUNTY = C.slug
REPO = pathlib.Path(__file__).resolve().parent.parent
W = C.world
RAW, LAYERS = W / "layers_raw", W / "layers"
STAGE_TMP = pathlib.Path(f"/tmp/ruralsim_stage/{FIPS}"); STAGE_TMP.mkdir(parents=True, exist_ok=True)
STAGE = STAGE_TMP  # USD atomic-save needs rename; final copy to W/stage at end
VIEWER_DATA = W / "viewer_data"; VIEWER_DATA.mkdir(parents=True, exist_ok=True)

UTM = C.utm
geom_wgs = C.geom
ORIGIN = (geom_wgs.centroid.x, geom_wgs.centroid.y)  # lon, lat

import pyproj
fwd = pyproj.Transformer.from_crs(4326, UTM, always_xy=True)
ox, oy = fwd.transform(*ORIGIN)

def enu(lon, lat):
    x, y = fwd.transform(lon, lat)
    return x - ox, y - oy

def enu_coords(coords):
    xs, ys = fwd.transform(*zip(*coords)) if False else fwd.transform([c[0] for c in coords], [c[1] for c in coords])
    return list(zip(np.asarray(xs) - ox, np.asarray(ys) - oy))

# DEM sampler: overlays are draped onto observed terrain (1:1, no exaggeration)
_DEM = {"src": None, "fallback": None}
def demz(lon, lat, default=None):
    if _DEM["src"] is None:
        _DEM["src"] = rasterio.open(next((LAYERS / "terrain").glob("dem_*_*.tif")))
    src = _DEM["src"]
    if default is None:
        # fallback = elevation at county centroid (was hardcoded 340 m = pilot 1;
        # buried every unplaceable Teton overlay 1.2 km under the terrain)
        if _DEM["fallback"] is None:
            v0 = next(src.sample([ORIGIN]))[0]
            _DEM["fallback"] = float(v0) if np.isfinite(v0) and v0 > 0 else 0.0
        default = _DEM["fallback"]
    try:
        v = next(src.sample([(lon, lat)]))[0]
        nd = src.nodata
        if not np.isfinite(v) or (nd is not None and v == nd) or v <= 0:
            return default
        return float(v)
    except Exception:
        return default

LAYER_META = {}  # layer_id -> meta dict (provenance etc.)

def register(layer_id, source, provenance, license_, vintage, notes=""):
    LAYER_META[layer_id] = {"source": source, "provenance": provenance,
                            "license": license_, "vintage": vintage, "notes": notes}

def write_layer(name, builder):
    path = STAGE / f"{name}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    builder(stage)
    m = LAYER_META.get(name, {})
    stage.SetMetadata("customLayerData", {"ruralsim": {**m, "layer": name}})
    stage.GetRootLayer().Save()
    return path.name

# ---------------- terrain ----------------
def build_terrain(stage):
    from rasterio.fill import fillnodata
    with rasterio.open(next((LAYERS / "terrain").glob("dem_*_*.tif"))) as src:
        # ~160 m effective for the stage mesh; payload resolution varies by
        # source (20 m from 1/3 arc-second, 30 m from the 1 arc-second fallback)
        step = max(1, round(160 / (abs(src.transform.a) * 111320)))
        arr = src.read(1)[::step, ::step].astype("float32")
        t = src.transform
    # nodata cells sit outside the county-buffer clip polygon (raster corners).
    # Fill them by edge interpolation so the mesh has no fabricated 0 m pits;
    # county-interior cells remain 100% observed. Payload GeoTIFF keeps nodata.
    valid = np.isfinite(arr)
    arr = fillnodata(arr, mask=valid.astype("uint8"))
    if not np.isfinite(arr).all():
        # fillnodata leaves holes >100 px from valid data (coarser 30 m fallback
        # grids have deeper corners); nearest-fill the remainder - all such cells
        # are outside the county polygon and already tagged derived
        from scipy.ndimage import distance_transform_edt
        ind = distance_transform_edt(~np.isfinite(arr), return_distances=False,
                                     return_indices=True)
        arr = arr[tuple(ind)]
    H, Wd = arr.shape
    pts = []
    for r in range(H):
        lat = t.f + r * step * t.e
        for c in range(Wd):
            lon = t.c + c * step * t.a
            z = arr[r, c]
            x, y = enu(lon, lat)
            pts.append(Gf.Vec3f(float(x), float(z), float(y)))  # Y-up: z=elev
    face_counts, face_idx = [], []
    for r in range(H - 1):
        for c in range(Wd - 1):
            i = r * Wd + c
            face_counts.append(4)
            face_idx += [i, i + 1, i + 1 + Wd, i + Wd]
    mesh = UsdGeom.Mesh.Define(stage, "/Terrain")
    mesh.CreatePointsAttr(pts)
    mesh.CreateFaceVertexCountsAttr(face_counts)
    mesh.CreateFaceVertexIndicesAttr(face_idx)
    mesh.CreateSubdivisionSchemeAttr("none")
    mesh.CreateDisplayColorAttr([(0.45, 0.55, 0.38)])
    # viewer export: float32 grid (nodata-filled) + transform for client-side mesh build
    arr.astype("float32").tofile(VIEWER_DATA / "terrain_grid.f32")
    Hg, Wg = arr.shape
    lons = [t.c + c * t.a * step for c in range(Wg)]
    lats = [t.f + r * t.e * step for r in range(Hg)]
    # reference lon/lat for the 1D axis projections must be THIS county's
    # centroid — hardcoding pilot-1 coords shifted Teton's grid +104 km in y
    xs1 = fwd.transform(lons, [ORIGIN[1]] * Wg)[0]
    ys1 = fwd.transform([ORIGIN[0]] * Hg, lats)[1]
    (VIEWER_DATA / "terrain_meta.json").write_text(json.dumps(
        {"shape": [Hg, Wg], "enu_origin_deg": list(ORIGIN), "utm": UTM,
         "enu_x": [round(float(x - ox), 1) for x in xs1],
         "enu_y": [round(float(y - oy), 1) for y in ys1]}))
_dem_meta = json.loads(((LAYERS / "terrain") / "_meta.json").read_text())
register("terrain", _dem_meta["source"], "observed", "public domain",
         "2012-2024 tile vintages",
         f"Stage/viewer mesh at ~160 m; cells outside county-buffer clip filled by GDAL "
         f"fillnodata interpolation (derived); interior cells observed; "
         f"{_dem_meta['output']['resolution_m']} m GeoTIFF payload retains nodata")

# ---------------- boundaries ----------------
def build_boundaries(stage):
    for prim_name, geom, color in [
            ("County", geom_wgs, (0.9, 0.9, 0.9))]:
        coords = list(geom.exterior.coords)
        pts = [Gf.Vec3f(float(x), demz(c[0], c[1]) + 3.0, float(y))
               for c, (x, y) in zip(coords, enu_coords(coords))]
        c = UsdGeom.BasisCurves.Define(stage, f"/Boundaries/{prim_name}")
        c.CreatePointsAttr(pts)
        c.CreateCurveVertexCountsAttr([len(pts)])
        c.CreateTypeAttr("linear")
        c.CreateWidthsAttr([60.0])
        c.CreateDisplayColorAttr([color])
    # tribal reservations
    try:
        tr = gpd.read_file(RAW / "tribal" / f"tribal_{FIPS}.geojson")
        for i, row in tr.iterrows():
            g = row.geometry
            polys = [g] if g.geom_type == "Polygon" else list(g.geoms)
            for j, p in enumerate(polys):
                tcoords = list(p.exterior.coords)
                pts = [Gf.Vec3f(float(x), demz(c[0], c[1]) + 4.0, float(y))
                       for c, (x, y) in zip(tcoords, enu_coords(tcoords))]
                c = UsdGeom.BasisCurves.Define(stage, f"/Boundaries/Tribal/{row['namelsad'].replace(' ','_')}_{j}")
                c.CreatePointsAttr(pts)
                c.CreateCurveVertexCountsAttr([len(pts)])
                c.CreateTypeAttr("linear"); c.CreateWidthsAttr([80.0])
                c.CreateDisplayColorAttr([(0.85, 0.6, 0.2)])
    except Exception as e:
        print("tribal boundaries skipped:", e)
    # viewer
    (VIEWER_DATA / "boundaries.json").write_text(json.dumps({
        "county": [list(p) for p in enu_coords(list(geom_wgs.exterior.coords))],
        "tribal": [{"name": r["namelsad"],
                    "rings": [[list(p) for p in enu_coords(list(poly.exterior.coords))]
                              for poly in ([r.geometry] if r.geometry.geom_type == "Polygon" else list(r.geometry.geoms))]}
                   for _, r in gpd.read_file(RAW / "tribal" / f"tribal_{FIPS}.geojson").iterrows()]}))
register("boundaries",
         ("Census 2023 cartographic county polygon" if C.is_pilot else "Census TIGERweb county polygon (current TIGER/Line)")
         + " + TIGER AIANNH (via USFS EDW)",
         "observed", "public domain", "2023/2024" if C.is_pilot else "current/2024", "tribal jurisdiction marked per guardrails")

# ---------------- generic line/point/polygon loaders ----------------
def lines_from_geojson(path, key_filter=None):
    d = json.loads(pathlib.Path(path).read_text())
    out = []
    for f in d["features"]:
        g = f["geometry"]; p = f["properties"]
        if key_filter and not key_filter(p):
            continue
        if g["type"] == "LineString":
            out.append((p, g["coordinates"]))
        elif g["type"] == "MultiLineString":
            for part in g["coordinates"]:
                out.append((p, part))
    return out

def write_curves(stage, root, lines, color_fn, width=30.0, zoff=2.0, viewer=None):
    """lines: list of (props, coords). viewer: list to append viewer segments.
    Curves are draped on the DEM (zoff metres above sampled ground)."""
    vcount = 0
    for i, (props, coords) in enumerate(lines):
        if len(coords) < 2:
            continue
        pts = [Gf.Vec3f(float(x), demz(c[0], c[1]) + zoff, float(y))
               for c, (x, y) in zip(coords, enu_coords(coords))]
        c = UsdGeom.BasisCurves.Define(stage, f"/{root}/c{i}")
        c.CreatePointsAttr(pts)
        c.CreateCurveVertexCountsAttr([len(pts)])
        c.CreateTypeAttr("linear")
        c.CreateWidthsAttr([width])
        c.CreateDisplayColorAttr([color_fn(props)])
        if viewer is not None:
            viewer.append({"pts": [[round(x, 1), round(y, 1)] for x, y in enu_coords(coords)],
                           "cls": color_fn(props).__class__ and props})
            vcount += 1
    return vcount

ROAD_COLORS = {"motorway": (0.85, 0.3, 0.2), "trunk": (0.85, 0.3, 0.2),
               "primary": (0.9, 0.5, 0.15), "secondary": (0.9, 0.7, 0.2),
               "tertiary": (0.8, 0.8, 0.5)}
def road_color(p):
    return ROAD_COLORS.get(p.get("highway", ""), (0.55, 0.55, 0.55))

def build_roads(stage):
    lines = lines_from_geojson(RAW / "osm" / "roads.geojson")
    segs = []
    write_curves(stage, "Roads", lines, road_color, viewer=segs)
    (VIEWER_DATA / "roads.json").write_text(json.dumps(
        [{"pts": s["pts"], "hwy": s["cls"].get("highway", "road"), "name": s["cls"].get("name")} for s in segs]))
    print("roads:", len(lines))
register("roads", "OpenStreetMap via Overpass", "observed", "ODbL 1.0", "retrieved 2026-11-11",
         "TIGER cross-check deferred (Census www2 blocked from build network)")

def build_rail(stage):
    lines = lines_from_geojson(RAW / "rail" / f"rail_ntad_{FIPS}.geojson")
    segs = []
    write_curves(stage, "Rail", lines, lambda p: (0.3, 0.3, 0.35), width=45.0, viewer=segs)
    (VIEWER_DATA / "rail.json").write_text(json.dumps([{"pts": s["pts"], "owner": s["cls"].get("RROWNER1")} for s in segs]))
    print("rail:", len(lines))
register("rail", "BTS NTAD North American Rail Network", "observed", "public domain", "NTAD current")

def build_hydrology(stage):
    lines = lines_from_geojson(RAW / "hydrology" / f"nhd_flowlines_{FIPS}.geojson")
    segs = []
    write_curves(stage, "Hydrology", lines, lambda p: (0.25, 0.45, 0.8), width=25.0, viewer=segs)
    (VIEWER_DATA / "hydrology.json").write_text(json.dumps(
        [{"pts": s["pts"], "name": s["cls"].get("gnis_name")} for s in segs]))
    print("flowlines:", len(lines))
register("hydrology", "USGS NHD flowlines+waterbodies (ArcGIS REST)", "observed", "public domain",
         "current", "flowlines clipped to county envelope; buffer-zone flowlines partial")

def build_power(stage):
    lines = lines_from_geojson(RAW / "osm" / "power.geojson", lambda p: p.get("power") in ("line", "minor_line"))
    segs = []
    write_curves(stage, "Grid/Lines", lines,
                 lambda p: (0.9, 0.2, 0.7) if p.get("power") == "line" else (0.6, 0.4, 0.7),
                 width=22.0, viewer=segs)
    (VIEWER_DATA / "power_lines.json").write_text(json.dumps(
        [{"pts": s["pts"], "kind": s["cls"].get("power"), "voltage": s["cls"].get("voltage")} for s in segs]))
    # substations + generators as instanced markers
    d = json.loads((RAW / "osm" / "power.geojson").read_text())
    subs, gens = [], []
    def centroid_of(g):
        if g["type"] == "Point":
            return g["coordinates"]
        if g["type"] == "LineString":
            cs = g["coordinates"]
        elif g["type"] == "Polygon":
            cs = g["coordinates"][0]
        elif g["type"] == "MultiPolygon":
            cs = g["coordinates"][0][0]
        else:
            return None
        return [sum(c[0] for c in cs) / len(cs), sum(c[1] for c in cs) / len(cs)]
    for f in d["features"]:
        p = f["properties"]; g = f["geometry"]
        c0 = centroid_of(g)
        if not c0 or p.get("power") not in ("substation", "generator"):
            continue
        x, y = enu(*c0)
        if p.get("power") == "substation":
            subs.append((x, y, c0))
        elif p.get("power") == "generator":
            gens.append((x, y, c0, p.get("generator:source", "unknown")))
    for i, (x, y, ll) in enumerate(subs):
        cube = UsdGeom.Cube.Define(stage, f"/Grid/Substations/s{i}")
        cube.CreateSizeAttr(25.0)
        UsdGeom.XformCommonAPI(cube).SetTranslate((float(x), demz(*ll) + 12.5, float(y)))
        UsdGeom.Mesh(cube.GetPrim()).CreateDisplayColorAttr([(0.9, 0.2, 0.7)])
    for i, (x, y, ll, src) in enumerate(gens):
        cyl = UsdGeom.Cylinder.Define(stage, f"/Grid/Generators/g{i}")
        cyl.CreateRadiusAttr(3.0); cyl.CreateHeightAttr(80.0)
        UsdGeom.XformCommonAPI(cyl).SetTranslate((float(x), demz(*ll) + 40.0, float(y)))
        UsdGeom.Mesh(cyl.GetPrim()).CreateDisplayColorAttr([(0.95, 0.95, 0.95)])
    (VIEWER_DATA / "power_points.json").write_text(json.dumps(
        {"substations": [[round(x, 1), round(y, 1)] for x, y, _ in subs],
         "generators": [[round(x, 1), round(y, 1), s] for x, y, _, s in gens]}))
    print("power lines:", len(lines), "subs:", len(subs), "gens:", len(gens))
register("grid", "OSM power=* (cross-check per manifest); EIA-860/861 tabular in layers_raw/grid",
         "observed", "ODbL 1.0 / public domain", "2024-2026",
         "EIA Atlas transmission REST deferred; feeders NOT public - to be synthesized as 'assumed'")

# ---------------- buildings ----------------
def infer_height(props):
    b = (props.get("building") or "").lower()
    if b in ("farm_auxiliary", "barn", "silo"): return 6.0
    if b in ("commercial", "retail", "supermarket"): return 6.5
    if b in ("industrial", "warehouse"): return 8.0
    if b in ("church", "school", "hospital", "public"): return 9.0
    if b in ("house", "residential", "detached", "yes", ""): return 4.5
    return 5.0

def build_buildings(stage):
    d = json.loads((RAW / "osm" / "buildings.geojson").read_text())
    n = 0; viewer = []
    for f in d["features"]:
        g = f["geometry"]
        if g["type"] == "Polygon":
            rings = [g["coordinates"][0]]
        elif g["type"] == "MultiPolygon":
            rings = [g["coordinates"][0][0]]
        else:
            continue
        h = infer_height(f["properties"])
        xs, ys = zip(*enu_coords(rings[0]))
        cx, cy = float(np.mean(xs)), float(np.mean(ys))
        w = float(max(xs) - min(xs)); dep = float(max(ys) - min(ys))
        if w < 2 or dep < 2:
            continue
        base = demz(float(np.mean([c[0] for c in rings[0]])),
                    float(np.mean([c[1] for c in rings[0]])))
        cube = UsdGeom.Cube.Define(stage, f"/Buildings/b{n}")
        cube.CreateSizeAttr(1.0)
        xf = UsdGeom.XformCommonAPI(cube)
        xf.SetScale((max(w, 3), h, max(dep, 3)))
        xf.SetTranslate((cx, base + h / 2, cy))
        UsdGeom.Mesh(cube.GetPrim()).CreateDisplayColorAttr([(0.75, 0.72, 0.68)])
        n += 1
        viewer.append({"c": [round(cx, 1), round(cy, 1)], "w": round(w, 1), "d": round(dep, 1),
                       "h": h, "kind": f["properties"].get("building", "yes")})
    (VIEWER_DATA / "buildings.json").write_text(json.dumps(viewer))
    print("buildings extruded:", n)
register("buildings", "OpenStreetMap building footprints", "observed (footprint), derived (height)",
         "ODbL 1.0", "retrieved 2026-11-11",
         "heights inferred from footprint class per manifest rule; MS footprints fallback not needed")

# ---------------- facilities: hospitals, schools, water systems ----------------
def _geom_ll(f):
    """Representative lon/lat for any OSM geometry (overpass `out geom` turns
    ways into LineStrings and relations into Polygons). Centroid of vertices;
    Point is exact. Skipping non-Point features dropped 33 of 60 McDowell
    schools and forced Wilcox's hospital onto a town-centroid fallback even
    though its way was mapped (2026-11-12)."""
    g = f["geometry"]; t = g["type"]; c = g["coordinates"]
    if t == "Point":
        return c[0], c[1]
    if t == "LineString":
        pts = c
    elif t == "Polygon":
        pts = c[0]
    elif t == "MultiPolygon":
        pts = [p for poly in c for p in poly[0]]
    else:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

import re as _re
def _norm_name(s):
    return _re.sub(r"[^A-Z0-9 ]", "", str(s).upper())

_NAME_STOP = {"HOSPITAL", "MEDICAL", "CENTER", "CENTRE", "THE", "OF", "AND", "AT", "CITY", "COMMUNITY", "COUNTY", "MEMORIAL", "REGIONAL", "HEALTH", "CARE"}

def build_facilities(stage):
    hosp = pd_read(REPO / "data" / "facility_hospital.csv")
    hc = hosp[hosp["fips5"] == FIPS]
    osm_hc = json.loads((RAW / "osm" / "healthcare.geojson").read_text())["features"]
    viewer = {"hospitals": [], "schools": [], "water_systems": []}
    i = 0
    for _, r in hc.iterrows():
        # match to OSM by significant name tokens (punctuation-insensitive),
        # any geometry type via centroid; else place at town centroid
        name = str(r["Facility Name"])
        toks = [t for t in _norm_name(name).split() if t not in _NAME_STOP and len(t) > 1]
        frag = name.split()[0].upper()
        xy = ll = None
        for f in osm_hc:
            nm = _norm_name(f["properties"].get("name") or "")
            hit = (len(toks) >= 2 and all(t in nm for t in toks[:2])) or (toks and toks[0] in nm) or (frag in nm)
            if hit:
                ll = _geom_ll(f)
                if ll: xy = enu(*ll); break
        tag = "observed (OSM geocoded)" if xy else "derived (town-centroid fallback)"
        if not xy:
            town = str(r["City/Town"]).upper()
            pl = json.loads((RAW / "osm" / "places.geojson").read_text())["features"]
            for f in pl:
                if (f["properties"].get("name") or "").upper() == town:
                    ll = f["geometry"]["coordinates"]; xy = enu(*ll); break
        if not xy:
            continue
        cyl = UsdGeom.Cylinder.Define(stage, f"/Facilities/Hospitals/h{i}")
        cyl.CreateRadiusAttr(30.0); cyl.CreateHeightAttr(40.0)
        UsdGeom.XformCommonAPI(cyl).SetTranslate((float(xy[0]), demz(*ll) + 20.0, float(xy[1])))
        UsdGeom.Mesh(cyl.GetPrim()).CreateDisplayColorAttr([(0.9, 0.1, 0.15)])
        cyl.GetPrim().SetCustomData({"name": name, "type": r["Hospital Type"],
                                     "emergency": r["Emergency Services"], "provenance": tag})
        viewer["hospitals"].append({"name": name, "type": r["Hospital Type"], "pos": [round(xy[0],1), round(xy[1],1)], "provenance": tag})
        i += 1
    sc = json.loads((RAW / "osm" / "schools.geojson").read_text())["features"]
    j = 0
    for f in sc:
        ll = _geom_ll(f)   # ways/relations included via centroid, not dropped
        if not ll:
            continue
        x, y = enu(*ll)
        cone = UsdGeom.Cone.Define(stage, f"/Facilities/Schools/s{j}")
        cone.CreateRadiusAttr(25.0); cone.CreateHeightAttr(25.0)
        UsdGeom.XformCommonAPI(cone).SetTranslate((float(x), demz(*ll) + 12.5, float(y)))
        UsdGeom.Mesh(cone.GetPrim()).CreateDisplayColorAttr([(0.2, 0.5, 0.9)])
        viewer["schools"].append({"name": f["properties"].get("name"), "pos": [round(x,1), round(y,1)]})
        j += 1
    wsy = pd_read(RAW / "water_systems" / f"sdwis_systems_{FIPS}.csv")
    wsy = wsy[wsy.get("pws_activity_code", "A") == "A"] if "pws_activity_code" in wsy.columns else wsy
    town_xy, town_ll = {}, {}
    for f in json.loads((RAW / "osm" / "places.geojson").read_text())["features"]:
        nm = (f["properties"].get("name") or "").upper()
        town_xy[nm] = enu(*f["geometry"]["coordinates"])
        town_ll[nm] = f["geometry"]["coordinates"]
    k = 0
    def _s(v):
        # pandas NaN is truthy - "nan" must not win the or-chain (0/11 Chautauqua
        # systems placed 2026-11-12 because city_name was all-NaN and str(nan)
        # short-circuited the populated city_served)
        s = "" if v is None else str(v)
        return "" if s.lower() == "nan" else s
    for _, r in wsy.iterrows():
        city = (_s(r.get("city_name")) or _s(r.get("city_served"))).upper()
        xy = town_xy.get(city)
        if not xy:
            continue
        sp = UsdGeom.Sphere.Define(stage, f"/Facilities/WaterSystems/w{k}")
        sp.CreateRadiusAttr(18.0)
        UsdGeom.XformCommonAPI(sp).SetTranslate((float(xy[0]) + 40.0 * (k % 3), demz(*town_ll[city]) + 18.0, float(xy[1])))
        UsdGeom.Mesh(sp.GetPrim()).CreateDisplayColorAttr([(0.2, 0.75, 0.75)])
        viewer["water_systems"].append({"name": _s(r.get("pws_name")) or _s(r.get("pwsid")) or "PWS",
                                        "pop": _s(r.get("population_served_count")), "pos": [round(xy[0],1), round(xy[1],1)]})
        k += 1
    (VIEWER_DATA / "facilities.json").write_text(json.dumps(viewer))
    print("hospitals:", i, "schools:", j, "water systems:", k)
register("facilities", "CMS Hospital General Information (bundle) + OSM schools + EPA SDWIS",
         "observed (facility attrs); derived (some positions)", "public domain / ODbL", "2024-2026",
         "NCES EDGE school layer deferred (nces.ed.gov blocked); OSM schools interim")

def pd_read(p):
    import pandas as pd
    return pd.read_csv(p, dtype=str, low_memory=False)

# ---------------- bridges ----------------
def build_bridges(stage):
    d = json.loads((RAW / "bridges" / f"nbi_{FIPS}.geojson").read_text())
    cond_color = {"G": (0.2, 0.7, 0.2), "F": (0.85, 0.7, 0.1), "P": (0.9, 0.15, 0.1)}
    viewer = []
    i = 0
    import math
    for f in d["features"]:
        ll = f["geometry"]["coordinates"]
        x, y = enu(*ll)
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        cond = f["properties"].get("bridge_condition") or "?"
        cube = UsdGeom.Cube.Define(stage, f"/Bridges/b{i}")
        cube.CreateSizeAttr(15.0)
        UsdGeom.XformCommonAPI(cube).SetTranslate((float(x), demz(*ll) + 7.5, float(y)))
        UsdGeom.Mesh(cube.GetPrim()).CreateDisplayColorAttr([cond_color.get(cond, (0.5, 0.5, 0.5))])
        cube.GetPrim().SetCustomData({k: v for k, v in f["properties"].items() if v})
        viewer.append({"pos": [round(x,1), round(y,1)], "cond": cond,
                       "carries": f["properties"].get("carries"), "crosses": f["properties"].get("crosses"),
                       "year_built": f["properties"].get("year_built")})
        i += 1
    (VIEWER_DATA / "bridges.json").write_text(json.dumps(viewer))
    print("bridges:", i)
register("bridges", "FHWA National Bridge Inventory 2024", "observed", "public domain", "2024",
         "condition codes G/F/P from NBI BRIDGE_CONDITION")

# ---------------- land tenure ----------------
def build_land_tenure(stage):
    try:
        lt = gpd.read_file(RAW / "land_tenure" / f"land_tenure_{FIPS}.geojson")
    except Exception as e:
        print("land tenure skipped:", e); return
    viewer = []
    own_color = {"TRIB": (0.85, 0.6, 0.2), "USACE": (0.3, 0.4, 0.7), "SDNR": (0.3, 0.65, 0.3),
                 "CNTY": (0.6, 0.6, 0.4)}
    for i, row in lt.iterrows():
        g = row.geometry
        polys = [g] if g.geom_type == "Polygon" else (list(g.geoms) if g.geom_type == "MultiPolygon" else [])
        for j, p in enumerate(polys[:3]):
            lcoords = list(p.exterior.coords)
            pts = [Gf.Vec3f(float(x), demz(c[0], c[1]) + 2.5, float(y))
                   for c, (x, y) in zip(lcoords, enu_coords(lcoords))]
            c = UsdGeom.BasisCurves.Define(stage, f"/LandTenure/p{i}_{j}")
            c.CreatePointsAttr(pts); c.CreateCurveVertexCountsAttr([len(pts)])
            c.CreateTypeAttr("linear"); c.CreateWidthsAttr([40.0])
            c.CreateDisplayColorAttr([own_color.get(row.get("Mang_Type"), (0.5, 0.5, 0.5))])
        viewer.append({"type": row.get("Mang_Type"), "name": row.get("Unit_Nm")})
    (VIEWER_DATA / "land_tenure.json").write_text(json.dumps(viewer))
    print("land tenure parcels:", len(lt))
register("land_tenure", "USGS PAD-US 3.0 Fee Manager", "observed", "public domain", "3.0",
         "tribal fee parcels overlap tribal_boundaries; jurisdiction marker authoritative there")

# ---------------- root stage ----------------
def build_root(layer_files):
    path = STAGE / f"{FIPS}_{COUNTY}.usda"
    stage = Usd.Stage.CreateNew(str(path))
    root = stage.GetRootLayer()
    root.subLayerPaths = [f"./{f}" for f in layer_files]
    stage.SetMetadata("metersPerUnit", 1.0)
    stage.SetMetadata("upAxis", "Y")
    stage.SetMetadata("customLayerData", {"ruralsim": {
        "county_fips": FIPS, "county": f"{C.county_name}, {C.st}",
        "coordinate_system": "local ENU metres; origin at county centroid",
        "enu_origin_wgs84": list(ORIGIN), "projection": UTM,
        "built_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "fidelity_tier": "T1 geometry (observed layers) / feeders-broadband-solar assumed",
        "layers": LAYER_META,
        "guardrails": ["no real-person data", "election tables excluded from objective",
                       "tribal data sovereignty: jurisdiction marked, tribal layers observed-only"],
    }})
    root.Save()
    print("root stage:", path)

order = ["terrain", "land_tenure", "boundaries", "roads", "rail", "hydrology",
         "grid", "buildings", "bridges", "facilities"]
builders = {"terrain": build_terrain, "boundaries": build_boundaries, "roads": build_roads,
            "rail": build_rail, "hydrology": build_hydrology, "grid": build_power,
            "buildings": build_buildings, "facilities": build_facilities,
            "bridges": build_bridges, "land_tenure": build_land_tenure}
files = []
for name in order:
    print(f"--- {name}")
    files.append(write_layer(name, builders[name]))
build_root(files)

# population scrubber series (context only; observed Census estimates)
import pandas as pd
cy = pd.read_csv(REPO / "data" / "county_year.csv", dtype={"fips5": str}, low_memory=False)
cy = cy[cy["fips5"] == FIPS].sort_values("year")
pop = [{"year": int(r["year"]), "population": int(r["population"]),
        "vintage": int(r["popest_vintage"])}
       for _, r in cy.iterrows()
       if np.isfinite(r["population"]) and 2010 <= int(r["year"]) <= 2024]
(VIEWER_DATA / "population_series.json").write_text(json.dumps(pop))
print("population series:", len(pop), "years")

# materialize viewer from template (keeps all county viewers on one code path)
import shutil
tpl = (REPO / "tools" / "viewer_template.html").read_text()
vdir = W / "viewer"; vdir.mkdir(parents=True, exist_ok=True)
html = (tpl.replace("{{COUNTY_NAME}}", C.county_name).replace("{{ST}}", C.st)
           .replace("{{FIPS}}", FIPS).replace("{{KIND}}", "pilot" if C.is_pilot else "county").replace("{{UTM}}", UTM.replace("EPSG:", "EPSG:")))
(vdir / "index.html").write_text(html)
vendor_src = REPO / "worlds" / "31173_thurston_ne" / "viewer" / "vendor"
vendor_dst = vdir / "vendor"
if vendor_src.exists() and not vendor_dst.exists():
    shutil.copytree(vendor_src, vendor_dst)
print("viewer materialized at", vdir)
# copy stage to repo (/mnt does not support USD's atomic rename writes)
import shutil
final_dir = W / "stage"; final_dir.mkdir(parents=True, exist_ok=True)
for f in STAGE_TMP.glob("*.usda"):
    shutil.copyfile(f, final_dir / f.name)
print("stage copied to", final_dir)
(VIEWER_DATA / "layer_meta.json").write_text(json.dumps(LAYER_META, indent=2))
print("stage assembly complete")
