#!/usr/bin/env python3
"""Building footprints from Overture Maps to fill OpenStreetMap's rural gaps (D-037).

    python3 tools/fetch_buildings_overture.py 20019

OSM building coverage in rural counties is partial: counted inside the county polygon,
the canary run (D-036) found many counties under 80% of their housing units (Chautauqua
KS: 508 footprints for 1,976 housing units). Overture's buildings theme conflates OSM
with Microsoft and Google machine-learned footprints and Esri Community Maps, giving OSM
the highest priority, under ODbL (the same licence RuralSim already carries for OSM).

This step keeps RuralSim's own OSM layer as the primary source and takes from Overture
only the footprints that did NOT come from OSM, whose centre lies in the county polygon
plus ~1 km (not the whole buffered bbox, which can hold a neighbouring city):

    layers_raw/buildings_overture/overture_buildings_<fips>.geojson
        properties: overture_id, source (e.g. "Microsoft ML Buildings"), record_id,
                    height, num_floors, subtype, class
    layers_raw/buildings_overture/_meta.json   release, licence, counts by source

The stage builder drops any Overture footprint whose centre falls inside an OSM building
(an OSM edit newer than the Overture release), so a building is never drawn twice.

Access: the release named by the Overture STAC catalog (stac.overturemaps.org), read as
GeoParquet straight from Overture's public S3 bucket with DuckDB. A file index (one bbox
per Parquet file) is built once per release and cached in $RURALSIM_CACHE, so a county
reads only the one or two files that cover it. If Overture cannot be reached the layer is
written empty with a `ruralsim_gap` record and validation flags it (D-036 pattern).
"""
from __future__ import annotations

import concurrent.futures as cf, datetime, json, os, pathlib, sys, time, urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from county_config import get  # noqa: E402

STAC = "https://stac.overturemaps.org"
UA = {"User-Agent": "RuralSim/1.0 (+https://www.ruralsim.io; county twin build)"}
CACHE = pathlib.Path(os.environ.get("RURALSIM_CACHE", "/tmp/ruralsim_cache")) / "overture"
LICENSE = "ODbL 1.0"
ATTRIBUTION = "© OpenStreetMap contributors, Overture Maps Foundation"


def _json(url: str, tries: int = 4):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.load(r)
        except Exception:
            if attempt + 1 == tries:
                raise
            time.sleep(5 * (attempt + 1))


def latest_release() -> str:
    pinned = os.environ.get("RURALSIM_OVERTURE_RELEASE")  # reproduce an older build
    return pinned or _json(f"{STAC}/catalog.json")["latest"]


def file_index(release: str) -> list[dict]:
    """[{"bbox": [w, s, e, n], "url": "s3://..."}] for every building Parquet file."""
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{release}_buildings_index.json"
    if p.exists():
        return json.loads(p.read_text())
    coll = _json(f"{STAC}/{release}/buildings/building/collection.json")
    items = [l["href"] for l in coll["links"] if l.get("rel") == "item"]

    def one(href):
        it = _json(href)
        aws = it["properties"]["storage:schemes"]["aws"]
        asset = it["assets"].get("aws") or next(iter(it["assets"].values()))
        href_aws = (asset.get("alternate", {}).get("s3", {}).get("href") or asset["href"])
        if href_aws.startswith("https://"):
            key = href_aws.split(".amazonaws.com/", 1)[1]
            href_aws = f"s3://{aws['bucket']}/{key}"
        return {"bbox": it["bbox"], "url": href_aws}

    with cf.ThreadPoolExecutor(16) as ex:
        idx = list(ex.map(one, items))
    p.write_text(json.dumps(idx))
    print(f"  Overture {release}: indexed {len(idx)} building files", flush=True)
    return idx


def files_for(bbox, idx) -> list[str]:
    w, s, e, n = bbox
    return [f["url"] for f in idx
            if f["bbox"][0] < e and f["bbox"][2] > w and f["bbox"][1] < n and f["bbox"][3] > s]


def query(urls: list[str], bbox) -> list[dict]:
    import duckdb
    w, s, e, n = bbox
    con = duckdb.connect()
    con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2';")
    files = ", ".join(f"'{u}'" for u in urls)
    rows = con.sql(f"""
        SELECT id, sources[1].dataset AS source, sources[1].record_id AS record_id,
               height, num_floors, subtype, class, ST_AsGeoJSON(geometry) AS g
        FROM read_parquet([{files}])
        WHERE bbox.xmin < {e} AND bbox.xmax > {w} AND bbox.ymin < {n} AND bbox.ymax > {s}
          AND sources[1].dataset <> 'OpenStreetMap'
    """).fetchall()
    feats = []
    for oid, src, rid, h, nf, sub, cls, g in rows:
        feats.append({"type": "Feature", "geometry": json.loads(g),
                      "properties": {"overture_id": oid, "source": src, "record_id": rid,
                                     "height": h, "num_floors": nf, "subtype": sub, "class": cls}})
    return feats


CLIP_BUFFER_DEG = 0.01  # ~1 km around the county polygon


def clip_to_county(feats: list[dict], county_geom) -> list[dict]:
    """Keep footprints whose centre is in the county (plus ~1 km). The bbox around a small
    county can hold a whole neighbouring city: Salem NJ's held 215,000 Overture footprints
    from the Wilmington and Philadelphia suburbs. OSM keeps the full bbox for context."""
    from shapely.geometry import shape
    from shapely.prepared import prep
    area = prep(county_geom.buffer(CLIP_BUFFER_DEG))
    return [f for f in feats if area.contains(shape(f["geometry"]).representative_point())]


def main(fips=None):
    C = get(fips)
    out_dir = C.world / "layers_raw" / "buildings_overture"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"overture_buildings_{C.fips}.geojson"
    if out.exists() and out.stat().st_size > 4096:
        print(f"overture buildings: {out.name} present, skipping (delete to re-fetch)")
        return
    t0 = time.time()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        release = latest_release()
        urls = files_for(C.buf_bbox, file_index(release))
        if not urls:
            raise RuntimeError(f"no Overture {release} building file covers {C.buf_bbox}")
        feats = clip_to_county(query(urls, C.buf_bbox), C.geom)
    except Exception as e:
        gap = {"layer": "buildings_overture", "file": out.name, "endpoint": STAC,
               "error": str(e)[:300], "utc": now}
        out.write_text(json.dumps({"type": "FeatureCollection", "features": [], "ruralsim_gap": gap}))
        print(f"overture buildings FAILED: {e}; recorded a source gap and continuing", flush=True)
        _record_gap(C, gap)
        return
    out.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    by_src = {}
    for f in feats:
        by_src[f["properties"]["source"]] = by_src.get(f["properties"]["source"], 0) + 1
    meta = {"retrieved_utc": now, "release": release,
            "source": f"Overture Maps Foundation buildings theme, release {release} "
                      "(non-OSM footprints only; OSM comes from RuralSim's own extract)",
            "license": LICENSE, "attribution": ATTRIBUTION, "provenance": "observed (footprint)",
            "files": urls, "features": len(feats), "by_source": by_src}
    (out_dir / "_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"overture buildings ({C.fips}): {len(feats)} non-OSM footprints {by_src} "
          f"from {len(urls)} file(s) in {time.time() - t0:.0f} s", flush=True)
    _record_gap(C, None)


def _record_gap(C, gap):
    """Keep layers_raw/_source_gaps.json (D-036) in step with this layer."""
    gp = C.world / "layers_raw" / "_source_gaps.json"
    gaps = [g for g in (json.loads(gp.read_text()) if gp.exists() else [])
            if g.get("layer") != "buildings_overture"]
    if gap:
        gaps.append(gap)
    if gaps:
        gp.write_text(json.dumps(gaps, indent=2))
    elif gp.exists():
        gp.unlink()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
