#!/usr/bin/env python3
"""Fetch polygon/line layers via ArcGIS REST with bbox envelope, geojson output.

- tribal_boundaries: USFS EDW republication of Census TIGER AIANNH (TIGER direct
  is blocked from this network; fields identical: geoid, namelsad, lsad).
  Manifest layer: tribal_boundaries. Provenance: observed.
- land_tenure: PAD-US 3.0 Fee Manager (official USGS AGOL). Manifest: land_tenure.
  Provenance: observed.
- rail: BTS NTAD North American Rail Network Lines. Manifest: rail. Observed.
- hydrology: USGS NHD flowlines (layer 6) + waterbodies (layer 12). Manifest:
  hydrology. Observed. (OSM waterway fetch abandoned for pilot 1: Overpass
  timeouts on big-river geometry; NHD is the manifest source anyway.)

Skip-existing per output file; delete a file to re-fetch that layer.
"""
import json, pathlib, urllib.request, urllib.parse, datetime, sys, time, shutil

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from county_config import get
C = get(sys.argv[1] if len(sys.argv) > 1 else None)
FIPS = C.fips
W, S, E, N = C.buf_bbox
ENV = f"{W},{S},{E},{N}"
REPO = pathlib.Path(__file__).resolve().parent.parent
ROOT = C.world / "layers_raw"
UA = {"User-Agent": "RuralSim-research/0.1"}
# /tmp staging: writes land on reliable local disk first, then copy to /mnt.
# The portal mount's async sync has repeatedly deleted freshly written files
# ~8 s AFTER a verified write, and a rewrite races the queued delete (D-019
# refined; 20019 tribal/land_tenure/waterbodies vanished on 3 consecutive
# verified rewrites 2026-11-12). Healing recopies from staging instead of
# refetching over the network.
STAGE = pathlib.Path("/tmp/ruralsim_staging") / FIPS
STAGE.mkdir(parents=True, exist_ok=True)

def arcgis_query(url, extra=None, paginate=False):
    """Envelope-intersect query, geojson out. paginate=True walks resultOffset."""
    base = {"geometry": ENV, "geometryType": "esriGeometryEnvelope", "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
            "returnGeometry": "true", "outSR": "4326", "f": "geojson",
            **(extra or {})}
    feats, offset = [], 0
    while True:
        params = {**base, "resultRecordCount": 2000}
        if paginate:
            params["resultOffset"] = offset
        full = url + "?" + urllib.parse.urlencode(params)
        for attempt in range(4):
            try:
                req = urllib.request.Request(full, headers=UA)
                with urllib.request.urlopen(req, timeout=300) as r:
                    gj = json.load(r)
                break
            except Exception as e:
                print(f"  retry {attempt+1}: {e}", file=sys.stderr); time.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(f"query failed after retries: {url}")
        if "features" not in gj:
            raise RuntimeError(f"ArcGIS error: {str(gj)[:300]}")
        feats.extend(gj["features"])
        if not paginate or len(gj["features"]) < 2000:
            break
        offset += 2000
    return {"type": "FeatureCollection", "features": feats}

JOBS = [
    # (dir, file, url, extra, paginate, source, license)
    ("tribal", f"tribal_{FIPS}.geojson",
     "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_TribalIndianLands_01/MapServer/0/query",
     {"where": "1=1"}, False,
     "USFS EDW_EDW_TribalIndianLands_01 (Census TIGER/Line AIANNH 2024 republication)",
     "USDA public domain / Census public domain"),
    ("land_tenure", f"land_tenure_{FIPS}.geojson",
     "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Fee_Manager/FeatureServer/0/query",
     {"where": "1=1"}, False,
     "USGS PAD-US 3.0 Fee Manager (AGOL, owner sboyer@usgs.gov_USGS)",
     "public domain (USGS), see DOI 10.5066/P9Q9LQ4B"),
    ("rail", f"rail_ntad_{FIPS}.geojson",
     "https://services.arcgis.com/xOi1kZaI0eWDREZv/ArcGIS/rest/services/NTAD_North_American_Rail_Network_Lines/FeatureServer/0/query",
     {"where": "1=1"}, False,
     "BTS NTAD North American Rail Network Lines (ArcGIS Open Data)",
     "public domain (USDOT BTS)"),
    ("hydrology", f"nhd_flowlines_{FIPS}.geojson",
     "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/6/query",
     {"where": "1=1"}, True,
     "USGS National Hydrography Dataset flowlines via hydro.nationalmap.gov ArcGIS REST",
     "public domain"),
    ("hydrology", f"nhd_waterbodies_{FIPS}.geojson",
     "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/12/query",
     {"where": "1=1"}, True,
     "USGS National Hydrography Dataset waterbodies via hydro.nationalmap.gov ArcGIS REST",
     "public domain"),
]

def write_via_stage(out, payload):
    """Write payload to /tmp staging, copy to the /mnt target, verify size."""
    staged = STAGE / out.name
    staged.write_text(payload)
    shutil.copy2(staged, out)
    ok = out.exists() and out.stat().st_size == len(payload.encode())
    print(f"  wrote {out.name}: {len(payload)} bytes, persisted={ok}", flush=True)
    if not ok:
        raise RuntimeError(f"write did not persist: {out}")

for dirname, fname, url, extra, paginate, source, lic in JOBS:
    d = ROOT / dirname; d.mkdir(parents=True, exist_ok=True)
    out = d / fname
    if out.exists():
        print(f"{dirname}/{fname}: present, skipping")
        continue
    print(f"{dirname}/{fname}: querying ...", flush=True)
    try:
        gj = arcgis_query(url, extra, paginate)
    except RuntimeError as e:
        print(f"  FAILED: {e}"); continue
    payload = json.dumps(gj)
    write_via_stage(out, payload)
    meta = {"retrieved_utc": datetime.datetime.now(datetime.UTC).isoformat(),
            "source": source, "license": lic, "provenance": "observed",
            "endpoint": url, "features": len(gj["features"])}
    # layer-level meta merges when two files share a dir (hydrology)
    mp = d / "_meta.json"
    if mp.exists() and dirname == "hydrology":
        prev = json.loads(mp.read_text())
        prev["features_total"] = prev.get("features_total", prev.pop("features", 0)) + len(gj["features"])
        meta = {**prev, **meta, "features_total": prev["features_total"]}
    (d / "_meta.json").write_text(json.dumps(meta, indent=2))
    names = [f["properties"].get("namelsad") or f["properties"].get("Mang_Name")
             or f["properties"].get("Unit_Nm") or f["properties"].get("gnis_name")
             for f in gj["features"][:12]]
    print(f"  {len(gj['features'])} features -> {[n for n in names if n][:8]}")

# settle-and-heal: the portal mount's async delete can land ~8 s after a
# verified write and clobber a rewrite, repeatedly for the same path (20019
# nhd_waterbodies dropped on 4 consecutive recopies 2026-11-12). Wait out the
# queue and recopy casualties from staging; copies are shielded so a mid-copy
# portal ENOENT just defers to the next round. If one path keeps dropping it
# is treated as cursed: heal once under an alternate glob-compatible name
# (only for layers whose downstream reference is a glob, ALT_OK), which has
# escaped the stuck delete queue in practice.
ALT_OK = ("nhd_waterbodies",)   # build_county EXPECT globs it; nothing reads the exact name
print("settle-and-heal: watching for portal-mount drops ...", flush=True)
targets = [(ROOT / dn / fn, STAGE / fn) for dn, fn, *_ in JOBS]
drops = {out.name: 0 for out, _ in targets}
renamed = {}
for rnd in range(1, 25):
    time.sleep(12)
    healed = []
    for out, staged in targets:
        cur = ROOT / out.parent.name / renamed.get(out.name, out.name)
        # a healed alternate name counts as present for this target
        if cur.exists() or out.exists():
            continue
        if not staged.exists():
            continue
        drops[out.name] += 1
        dest = out
        if drops[out.name] >= 5 and out.name.startswith(ALT_OK):
            dest = out.with_name(out.stem + "_r" + out.suffix)
            renamed[out.name] = dest.name
            print(f"  {out.name}: dropped {drops[out.name]}x; escaping to {dest.name}", flush=True)
        try:
            shutil.copy2(staged, dest)
            healed.append(dest.name)
        except OSError as e:
            print(f"  round {rnd}: copy of {dest.name} deferred ({e})", flush=True)
    if not healed:
        print(f"  round {rnd}: all files stable")
        break
    print(f"  round {rnd}: healed dropped files: {healed}", flush=True)
missing = []
for out, staged in targets:
    cur = ROOT / out.parent.name / renamed.get(out.name, out.name)
    if not out.exists() and not cur.exists():
        missing.append(out.name)
if missing:
    raise RuntimeError(f"files missing after heal phase: {missing}")
if renamed:
    (ROOT / "_healed_renames.json").write_text(json.dumps(
        {"note": "portal mount kept dropping the canonical path; healed under "
                 "a glob-compatible alternate name (D-019 refined)",
         "renames": renamed, "utc": datetime.datetime.now(datetime.UTC).isoformat()}, indent=2))
print("done")
