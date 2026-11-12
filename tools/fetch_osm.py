#!/usr/bin/env python3
"""Fetch OSM layers for a pilot county via Overpass API.

Covers manifest layers: roads (primary), buildings (fallback to MS footprints),
schools, hospitals cross-check, grid cross-check (power=*), places, water towers.
Output: one GeoJSON per theme in layers_raw/osm/, EPSG:4326.
Provenance: observed (OpenStreetMap, ODbL). Retrieval date recorded in sidecar.
"""
import json, sys, time, urllib.request, urllib.parse, datetime, pathlib, subprocess

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from county_config import get
C = get(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].isdigit() else None)
FIPS = C.fips
W, S, E, N = C.bbox   # county bbox
BUF = 0.062           # ~5 km in degrees - uniform, slightly generous
BBOX = f"{S-BUF},{W-BUF},{N+BUF},{E+BUF}"               # overpass order: s,w,n,e

OUT = C.world / "layers_raw" / "osm"
OUT.mkdir(parents=True, exist_ok=True)

THEMES = {
    "roads":      'way["highway"]({b});',
    "buildings":  'way["building"]({b});relation["building"]({b});',
    "schools":    'nwr["amenity"="school"]({b});nwr["amenity"="college"]({b});',
    "healthcare": 'nwr["amenity"~"hospital|clinic|doctors"]({b});nwr["healthcare"]({b});',
    "power":      'nwr["power"]({b});',
    "places":     'node["place"]({b});',
    "water":      'nwr["man_made"="water_tower"]({b});nwr["amenity"="drinking_water"]({b});',
    "waterways":  'way["waterway"]({b});',
    "food_shops": 'nwr["shop"~"supermarket|grocery|convenience|general"]({b});',
    "bridges":    'way["bridge"="yes"]["highway"]({b});',
}
# NOTE: overpass.osm.ch was tested 2026-11-11 and returns empty result sets with a
# corrupt timestamp - an empty answer is worse than a loud failure; do not add it
# back without a currency check. overpass-api.de was unreachable earlier but came
# back 2026-11-12; it 406s POST, so requests go out as GET with ?data=.
ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.private.coffee/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter"]

def run(query, attempts=5):
    for attempt in range(attempts):
        for ep in ENDPOINTS:
            # curl transport first: api.de (or the egress middlebox) resets
            # Python's TLS handshake (SSL EOF) but answers curl fine on the
            # same host and query, 2026-11-12. GET form because api.de 406s POST.
            try:
                p = subprocess.run(
                    ["curl", "-sS", "--max-time", "150", "-G",
                     "-A", "RuralSim-research/0.1 (county twin build)",
                     "--data-urlencode", f"data={query}", ep],
                    capture_output=True, text=True, timeout=170)
                if p.returncode == 0 and p.stdout.strip():
                    return json.loads(p.stdout)
                raise RuntimeError(f"curl rc={p.returncode}: {p.stderr.strip()[:160] or p.stdout[:160]}")
            except Exception as e:
                print(f"  endpoint {ep} (curl) failed: {e}", file=sys.stderr)
            # urllib fallback in case curl is ever missing from the sandbox
            try:
                sep = "&" if "?" in ep else "?"
                req = urllib.request.Request(ep + sep + urllib.parse.urlencode({"data": query}),
                    headers={"User-Agent": "RuralSim-research/0.1 (county twin build)"})
                with urllib.request.urlopen(req, timeout=150) as r:
                    return json.load(r)
            except Exception as e:
                print(f"  endpoint {ep} (urllib) failed: {e}", file=sys.stderr)
        wait = 20 * (attempt + 1)
        print(f"  all endpoints failed (attempt {attempt+1}/{attempts}); backing off {wait}s", file=sys.stderr)
        time.sleep(wait)
    raise RuntimeError("all overpass endpoints failed")

def run_theme(body, bbox_str, depth=0):
    """Run one theme over a bbox; on total failure split the bbox into
    quadrants and retry each (county-scale result sets 504 under egress
    throttling; quadrant responses are ~4x smaller). Elements crossing a
    quadrant edge arrive twice; dedupe by (type, id)."""
    q = f"[out:json][timeout:300];({body.format(b=bbox_str)});out geom qt;"
    try:
        return run(q, attempts=3 if depth == 0 else 2)
    except RuntimeError:
        if depth >= 2:
            raise
        s, w, n, e = (float(v) for v in bbox_str.split(","))
        mlon, mlat = (w + e) / 2, (s + n) / 2
        quads = [(s, w, mlat, mlon), (s, mlon, mlat, e),
                 (mlat, w, n, mlon), (mlat, mlon, n, e)]
        print(f"  splitting bbox into quadrants (depth {depth+1})", file=sys.stderr)
        merged = {}
        for qs, qw, qn, qe in quads:
            sub = run_theme(body, f"{qs},{qw},{qn},{qe}", depth + 1)
            for el in sub.get("elements", []):
                merged[(el["type"], el["id"])] = el
        return {"elements": list(merged.values())}

def to_geojson(elements):
    """Convert overpass JSON (with out geom) to GeoJSON features."""
    feats = []
    for el in elements:
        tags = el.get("tags", {})
        if el["type"] == "node":
            geom = {"type": "Point", "coordinates": [el["lon"], el["lat"]]}
        elif el["type"] == "way" and "geometry" in el:
            coords = [[p["lon"], p["lat"]] for p in el["geometry"]]
            closed = len(coords) > 2 and coords[0] == coords[-1]
            is_area = closed and ("building" in tags or tags.get("area") == "yes")
            geom = {"type": "Polygon" if is_area else "LineString",
                    "coordinates": [coords] if is_area else coords}
        elif el["type"] == "relation" and "members" in el:
            outers = []
            for m in el["members"]:
                if m.get("role") == "outer" and "geometry" in m:
                    outers.append([[p["lon"], p["lat"]] for p in m["geometry"]])
            if not outers:
                continue
            geom = {"type": "MultiPolygon", "coordinates": [[o] for o in outers]}
        else:
            continue
        props = {"osm_type": el["type"], "osm_id": el["id"], **tags}
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": feats}

metaf = OUT / "_meta.json"
meta = json.loads(metaf.read_text()) if metaf.exists() else {
    "retrieved_utc": datetime.datetime.utcnow().isoformat() + "Z",
    "source": "OpenStreetMap via Overpass API", "license": "ODbL 1.0",
    "provenance": "observed", "bbox_buffered": BBOX, "themes": {}}

only = set(a for a in sys.argv[1:] if not a.isdigit())  # theme names; fips is argv[1]
for theme, body in THEMES.items():
    if only and theme not in only:
        continue
    if (OUT / f"{theme}.geojson").exists():
        print(f"  {theme}: already present, skipping")
        continue
    print(f"fetching {theme} ...", flush=True)
    try:
        data = run_theme(body, BBOX)
    except RuntimeError:
        if theme == "waterways":
            # big-river geometry reliably 504s Overpass; NHD is the manifest
            # hydrology source, so an empty OSM waterways layer is acceptable
            print("  waterways: all endpoints failed - writing empty layer (NHD covers hydrology)")
            data = {"elements": []}
        else:
            raise
    gj = to_geojson(data.get("elements", []))
    p = OUT / f"{theme}.geojson"
    p.write_text(json.dumps(gj))
    meta["themes"][theme] = {"features": len(gj["features"]), "file": p.name}
    print(f"  {theme}: {len(gj['features'])} features")
    time.sleep(2)

(OUT / "_meta.json").write_text(json.dumps(meta, indent=2))
print("done.")
