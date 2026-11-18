#!/usr/bin/env python3
"""USGS NHD flowlines and waterbodies from a per-state copy in R2 (D-045).

    python3 tools/nhd_mirror.py --state TN NC        # copy these states into R2 (plan job)
    python3 tools/nhd_mirror.py --test-read 37065     # print feature counts for a county

On 2026-11-18 hydro.nationalmap.gov (the NHD ArcGIS service) answered most county
queries with read timeouts: fetch_arcgis_layers.py took a median 14 min and up to 46 min
per county, against seconds the day before, and 21 Mississippi counties lost their
flowlines entirely the night before. USGS also publishes NHD as one GeoPackage per state
on its public S3 bucket (StagedProducts/Hydrography/NHD/State/GPKG, 0.1–5.6 GB zipped).

The plan job copies each state the batch touches into R2, once:

    nhd/<state>_flowline.parquet     permanent_identifier, gnis_name, ftype, fcode,
    nhd/<state>_waterbody.parquet    reachcode, lengthkm | areasqkm, xmin, ymin, xmax,
                                     ymax, geom (2D lon/lat WKB), sorted by latitude band
    nhd/<state>.json                 source URL, upstream Last-Modified, counts (written last)

and a county job reads only the rows whose bbox meets its envelope, over HTTP range
requests with DuckDB, from every state whose outline meets the envelope (a state's
GeoPackage also holds features of watersheds that cross its border, so rows are
de-duplicated on permanent_identifier). If a state is not mirrored the caller falls back
to the ArcGIS service. Public domain (USGS).
"""
from __future__ import annotations

import argparse, datetime, json, os, pathlib, shutil, sys, tempfile, time, urllib.request, zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

S3 = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/NHD/State/GPKG/"
PREFIX = "nhd/"
UA = {"User-Agent": "RuralSim/1.0 (+https://www.ruralsim.io; county twin build)"}
DATA_BASE = (os.environ.get("RURALSIM_DATA_BASE")
             or "https://pub-b414cd9251804d11871e4bec734e096e.r2.dev").rstrip("/")
LAYERS = {
    "flowline": ("NHDFlowline", "permanent_identifier, gnis_name, ftype, fcode, reachcode, lengthkm"),
    "waterbody": ("NHDWaterbody", "permanent_identifier, gnis_name, ftype, fcode, reachcode, areasqkm"),
}
_SPECIAL = {"district-of-columbia": "District_of_Columbia",
            "us-virgin-islands": "United_States_Virgin_Islands"}


def nhd_name(region_id: str) -> str:
    """Geofabrik region id ('us/north-carolina') -> USGS staged name ('North_Carolina')."""
    slug = region_id.rsplit("/", 1)[-1]
    return _SPECIAL.get(slug) or "_".join(w.capitalize() for w in slug.split("-"))


def key(region_id: str, layer: str) -> str:
    return f"{PREFIX}{region_id.rsplit('/', 1)[-1]}_{layer}.parquet"


def _duck():
    import duckdb
    con = duckdb.connect()
    con.sql("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
    return con


def _download(url: str, dest: pathlib.Path, tries: int = 5) -> dict:
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r, \
                    open(dest, "wb") as f:
                hdr = {"last_modified": r.headers.get("Last-Modified"),
                       "content_length": int(r.headers.get("Content-Length") or 0)}
                shutil.copyfileobj(r, f, 8 << 20)
            if hdr["content_length"] and dest.stat().st_size != hdr["content_length"]:
                raise IOError(f"short download {dest.stat().st_size} of {hdr['content_length']}")
            return hdr
        except Exception as e:
            if attempt + 1 == tries:
                raise
            print(f"  download retry ({e})", flush=True)
            time.sleep(30 * (attempt + 1))


def convert(gpkg: pathlib.Path, out_dir: pathlib.Path) -> dict:
    """Write <layer>.parquet for each layer; return feature counts."""
    con = _duck()
    counts = {}
    for name, (layer, cols) in LAYERS.items():
        out = out_dir / f"{name}.parquet"
        con.sql(f"""COPY (
            WITH s AS (SELECT {cols}, ST_Force2D(SHAPE) AS g
                       FROM st_read('{gpkg}', layer='{layer}') WHERE SHAPE IS NOT NULL)
            SELECT {cols}, ST_XMin(g) AS xmin, ST_YMin(g) AS ymin, ST_XMax(g) AS xmax,
                   ST_YMax(g) AS ymax, ST_AsWKB(g) AS geom
            FROM s ORDER BY floor(ST_YMin(g) * 10), ST_XMin(g)
        ) TO '{out}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 20000)""")
        counts[name] = con.sql(f"SELECT count(*) FROM '{out}'").fetchone()[0]
    return counts


def mirror(regions: list[dict], work: str | None = None, force: bool = False) -> list[str]:
    """Copy each region's NHD into R2 unless already there. Serial, one state on disk at a time."""
    from publish_world import bucket, client
    s3 = client()
    done = []
    for r in regions:
        rid = r["id"]
        meta_key = f"{PREFIX}{rid.rsplit('/', 1)[-1]}.json"
        if not force:
            try:
                s3.head_object(Bucket=bucket(), Key=meta_key)
                print(f"  NHD {rid}: in R2", flush=True)
                done.append(rid)
                continue
            except Exception:
                pass
        t0 = time.time()
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="nhd_", dir=work))
        try:
            url = f"{S3}NHD_H_{nhd_name(rid)}_State_GPKG.zip"
            zp = tmp / "nhd.zip"
            hdr = _download(url, zp)
            with zipfile.ZipFile(zp) as z:
                member = next(i.filename for i in z.infolist() if i.filename.endswith(".gpkg"))
                z.extract(member, tmp)
            zp.unlink()
            counts = convert(tmp / member, tmp)
            for name in LAYERS:
                s3.upload_file(str(tmp / f"{name}.parquet"), bucket(), key(rid, name),
                               ExtraArgs={"ContentType": "application/octet-stream",
                                          "CacheControl": "public, max-age=86400"})
            s3.put_object(Bucket=bucket(), Key=meta_key, ContentType="application/json",
                          Body=json.dumps({"region": rid, "source": url, "upstream": hdr,
                                           "counts": counts, "license": "public domain (USGS)",
                                           "written_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()},
                                          indent=2).encode())
            print(f"  NHD {rid}: mirrored {counts} in {time.time() - t0:.0f} s", flush=True)
            done.append(rid)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return done


class NotMirrored(RuntimeError):
    pass


def read(layer: str, bbox, region_ids: list[str]) -> dict:
    """GeoJSON FeatureCollection of NHD `layer` features meeting bbox (w, s, e, n)."""
    w, s, e, n = bbox
    urls = [f"{DATA_BASE}/{key(rid, layer)}" for rid in region_ids]
    for u in urls:  # a missing state means fall back, not an empty layer
        try:
            urllib.request.urlopen(urllib.request.Request(u, method="HEAD", headers=UA), timeout=30)
        except Exception as ex:
            raise NotMirrored(f"{u}: {ex}")
    cols = LAYERS[layer][1]
    files = ", ".join(f"'{u}'" for u in urls)
    con = _duck()
    rows = con.sql(f"""
        SELECT {cols}, ST_AsGeoJSON(ST_GeomFromWKB(geom)) AS g
        FROM (SELECT *, row_number() OVER (PARTITION BY permanent_identifier) AS k
              FROM read_parquet([{files}])
              WHERE xmin <= {e} AND xmax >= {w} AND ymin <= {n} AND ymax >= {s})
        WHERE k = 1 AND ST_Intersects(ST_GeomFromWKB(geom), ST_MakeEnvelope({w}, {s}, {e}, {n}))
    """).fetchall()
    names = [c.strip() for c in cols.split(",")]
    feats = [{"type": "Feature", "properties": dict(zip(names, r[:-1])), "geometry": json.loads(r[-1])}
             for r in rows]
    return {"type": "FeatureCollection", "features": feats}


def regions_for(bbox) -> list[str]:
    import fetch_osm
    return [r["id"] for r in fetch_osm.extracts_for([bbox], fetch_osm.geofabrik_index())]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", nargs="*", default=[], help="state names or Geofabrik slugs, e.g. Tennessee north-carolina")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--test-read", metavar="FIPS")
    a = ap.parse_args(argv)
    if a.test_read:
        from county_config import get
        C = get(a.test_read)
        rids = regions_for(C.buf_bbox)
        for layer in LAYERS:
            t0 = time.time()
            fc = read(layer, C.buf_bbox, rids)
            print(f"{C.fips} {layer}: {len(fc['features'])} features from {rids} in {time.time() - t0:.1f} s")
        return
    import fetch_osm
    idx = {f["properties"]["id"]: f["properties"] for f in json.loads(fetch_osm.US_INDEX.read_text())["features"]}
    want = []
    for s in a.state:
        rid = s if s.startswith("us/") else next((k for k in idx if nhd_name(k).lower() == s.lower()
                                                   or k.endswith("/" + s.lower())), None)
        if rid is None:
            raise SystemExit(f"unknown state {s}")
        want.append(idx[rid])
    mirror(want, force=a.force)


if __name__ == "__main__":
    main()
