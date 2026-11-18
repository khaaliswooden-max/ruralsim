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

def arcgis_query(url, extra=None, paginate=False, page=2000):
    """Envelope-intersect query, geojson out. paginate=True walks resultOffset.

    A server that answers HTTP 500 for a large page (NHD waterbodies over Cameron
    Parish's coastal marsh, canary run 43794676050) is retried with smaller pages."""
    deadline = time.time() + LAYER_BUDGET_S
    while True:
        try:
            return _arcgis_query(url, extra, paginate, page, deadline)
        except RuntimeError:
            if not paginate or page <= 250 or time.time() > deadline:
                raise
            page //= 4
            print(f"  retrying {url.rsplit('/', 3)[-3]} with {page}-feature pages", file=sys.stderr)


# One layer may spend at most this long across all retries and page sizes. NHD answered
# HTTP 504 for hours over Yukon-Koyukuk AK in the rerun (43845007357), and the retry
# ladder kept the county job running toward GitHub's 5-hour limit. Past the budget the
# layer becomes a recorded source gap (D-036) and the build continues (D-038).
LAYER_BUDGET_S = 20 * 60


def _arcgis_query(url, extra, paginate, page, deadline):
    base = {"geometry": ENV, "geometryType": "esriGeometryEnvelope", "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
            "returnGeometry": "true", "outSR": "4326", "f": "geojson",
            **(extra or {})}
    feats, offset = [], 0
    while True:
        params = {**base, "resultRecordCount": page}
        if paginate:
            params["resultOffset"] = offset
        full = url + "?" + urllib.parse.urlencode(params)
        if time.time() > deadline:
            raise RuntimeError(f"gave up after {LAYER_BUDGET_S // 60} min: {url}")
        for attempt in range(4):
            try:
                req = urllib.request.Request(full, headers=UA)
                with urllib.request.urlopen(req, timeout=120) as r:
                    gj = json.load(r)
                break
            except Exception as e:
                print(f"  retry {attempt+1}: {e}", file=sys.stderr); time.sleep(15 * (attempt + 1))
        else:
            raise RuntimeError(f"query failed after retries: {url}")
        if "features" not in gj:
            raise RuntimeError(f"ArcGIS error: {str(gj)[:300]}")
        feats.extend(gj["features"])
        if not paginate or len(gj["features"]) < page:
            break
        offset += page
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

def _gap_of(path):
    """The recorded gap if this file is a placeholder for a failed fetch, else None."""
    if path.stat().st_size > 4096:
        return None
    try:
        return json.loads(path.read_text()).get("ruralsim_gap")
    except ValueError:
        return None


gaps = []
for dirname, fname, url, extra, paginate, source, lic in JOBS:
    d = ROOT / dirname; d.mkdir(parents=True, exist_ok=True)
    out = d / fname
    if out.exists() and not _gap_of(out):
        print(f"{dirname}/{fname}: present, skipping")
        continue
    print(f"{dirname}/{fname}: querying ...", flush=True)
    if dirname == "hydrology":
        # D-045: read the per-state NHD copy in R2 first; the ArcGIS service is the fallback
        layer = "flowline" if "flowlines" in fname else "waterbody"
        try:
            import nhd_mirror
            rids = nhd_mirror.regions_for(C.buf_bbox)
            t0 = time.time()
            gj = nhd_mirror.read(layer, C.buf_bbox, rids)
            src_note = (f"USGS NHD state GeoPackages ({', '.join(nhd_mirror.nhd_name(r) for r in rids)}), "
                        "RuralSim's R2 copy (tools/nhd_mirror.py, D-045)")
            print(f"  NHD {layer} from the R2 copy: {len(gj['features'])} features in {time.time() - t0:.0f} s",
                  flush=True)
            write_via_stage(out, json.dumps(gj))
            meta = {"retrieved_utc": datetime.datetime.now(datetime.UTC).isoformat(),
                    "source": src_note, "license": lic, "provenance": "observed",
                    "endpoint": nhd_mirror.DATA_BASE + "/" + nhd_mirror.PREFIX, "features": len(gj["features"])}
            mp = d / "_meta.json"
            if mp.exists():
                prev = json.loads(mp.read_text())
                prev["features_total"] = prev.get("features_total", prev.pop("features", 0)) + len(gj["features"])
                meta = {**prev, **meta, "features_total": prev["features_total"]}
            mp.write_text(json.dumps(meta, indent=2))
            continue
        except Exception as e:
            print(f"  NHD R2 copy not usable ({str(e)[:160]}); querying the ArcGIS service", flush=True)
    try:
        gj = arcgis_query(url, extra, paginate)
    except RuntimeError as e:
        # One federal server being down should not cost the whole county (D-036): write
        # an empty layer, record the gap, and let validation flag it on the public page.
        print(f"  FAILED: {e}; recording a source gap and continuing", flush=True)
        gaps.append({"layer": dirname, "file": fname, "endpoint": url, "error": str(e)[:300],
                     "utc": datetime.datetime.now(datetime.UTC).isoformat()})
        write_via_stage(out, json.dumps({"type": "FeatureCollection", "features": [],
                                         "ruralsim_gap": gaps[-1]}))
        continue
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

# The settle-and-heal loop (D-019/D-023) that lived here guarded against the old build
# sandbox's portal mount deleting fresh files. Builds now run on local disk (GitHub
# runners), and the loop turned an upstream outage into a false "files missing" failure
# (Cameron LA, canary run 43794676050), so it is gone (D-036). build_county.py still
# verifies every expected output after each step.
gp = ROOT / "_source_gaps.json"
current = [g for dn, fn, *_ in JOBS if (ROOT / dn / fn).exists() and (g := _gap_of(ROOT / dn / fn))]
mine = {fn for _, fn, *_ in JOBS}
current += [g for g in (json.loads(gp.read_text()) if gp.exists() else [])
            if g.get("file") not in mine]  # other steps' gaps (e.g. Overture buildings) stay
if current:
    gp.write_text(json.dumps(current, indent=2))
    print(f"source gaps recorded: {[g['file'] for g in current]}")
elif gp.exists():
    gp.unlink()
print("done")
