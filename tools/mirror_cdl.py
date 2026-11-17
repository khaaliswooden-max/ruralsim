#!/usr/bin/env python3
"""Copy USDA NASS's national Cropland Data Layer into R2 as one Cloud-Optimized GeoTIFF (D-043).

    python3 tools/mirror_cdl.py              # 2025, the latest release (published 2026-02-27)
    python3 tools/mirror_cdl.py --year 2024
    python3 tools/mirror_cdl.py --convert-only 2025_30m_cdls.zip   # local test, no upload

CropScape's GetCDLFile service, the per-county source, has answered 404 since 2026-11-11
(it was replaced by CroplandCROS), and Planetary Computer's copy stops at 2021. NASS
still publishes the national 30 m raster as one zip
(nass.usda.gov/.../Release/datasets/<year>_30m_cdls.zip, ~1.9 GB, public domain). This
tool downloads it once, rewrites it as a COG (512 px tiles, DEFLATE, no overviews: county
jobs read full-resolution windows only) and uploads

    cdl/<year>_30m_cdls_cog.tif     the raster, CRS as published (CONUS Albers)
    cdl/<year>_30m_cdls_cog.json    source URL, size, upstream Last-Modified, written UTC

Measured on the 2025 release: 160,171 x 105,432 uint8 cells, 1.89 GB zip -> 1.29 GB COG in
101 s on 2 CPUs; a county window then reads in ~2 s.

County builds (fetch_cropland.py) then read just their window over HTTP range requests.
An existing object is left alone unless --force. Needs R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
R2_SECRET_ACCESS_KEY, R2_BUCKET unless --convert-only. Run by
.github/workflows/mirror-cdl.yml (manual, once per CDL release).
"""
from __future__ import annotations

import argparse, datetime, json, pathlib, sys, time, urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

NASS = "https://www.nass.usda.gov/sites/default/files/Research_and_Science/Cropland/Release/datasets/"
UA = {"User-Agent": "RuralSim/1.0 (+https://www.ruralsim.io; county twin build)"}
PREFIX = "cdl/"


def key(year: int) -> str:
    return f"{PREFIX}{year}_30m_cdls_cog.tif"


def download(url: str, dest: pathlib.Path, tries: int = 5) -> dict:
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r, \
                    open(dest, "wb") as f:
                hdr = {"last_modified": r.headers.get("Last-Modified"),
                       "content_length": int(r.headers.get("Content-Length") or 0)}
                while True:
                    c = r.read(8 << 20)
                    if not c:
                        break
                    f.write(c)
            if hdr["content_length"] and dest.stat().st_size != hdr["content_length"]:
                raise IOError(f"short download {dest.stat().st_size} of {hdr['content_length']}")
            return hdr
        except Exception as e:
            if attempt + 1 == tries:
                raise
            print(f"  download retry ({e})", flush=True)
            time.sleep(30 * (attempt + 1))


def to_cog(zip_path: pathlib.Path, year: int, out: pathlib.Path) -> None:
    import zipfile
    import rasterio
    from rasterio.shutil import copy as rcopy
    with zipfile.ZipFile(zip_path) as z:
        member = max((i for i in z.infolist() if i.filename.lower().endswith(".tif")),
                     key=lambda i: i.file_size).filename
    src = f"/vsizip/{zip_path}/{member}"
    t0 = time.time()
    with rasterio.Env(GDAL_NUM_THREADS="ALL_CPUS", GDAL_CACHEMAX=1024):
        with rasterio.open(src) as s:
            print(f"  {member}: {s.width} x {s.height}, {s.dtypes[0]}, {s.crs}", flush=True)
        rcopy(src, str(out), driver="COG", COMPRESS="DEFLATE", BLOCKSIZE=512,
              OVERVIEWS="NONE", NUM_THREADS="ALL_CPUS", BIGTIFF="IF_SAFER")
    print(f"  COG written: {out.stat().st_size / 1e9:.2f} GB in {time.time() - t0:.0f} s", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--work", default="/tmp/ruralsim_cdl")
    ap.add_argument("--convert-only", metavar="ZIP")
    a = ap.parse_args(argv)
    work = pathlib.Path(a.work); work.mkdir(parents=True, exist_ok=True)
    cog = work / pathlib.Path(key(a.year)).name

    if a.convert_only:
        to_cog(pathlib.Path(a.convert_only), a.year, cog)
        return

    from publish_world import bucket, client
    s3 = client()
    if not a.force:
        try:
            s3.head_object(Bucket=bucket(), Key=key(a.year))
            print(f"{key(a.year)} already in R2; nothing to do (--force to replace)")
            return
        except Exception:
            pass
    url = f"{NASS}{a.year}_30m_cdls.zip"
    zp = work / f"{a.year}_30m_cdls.zip"
    print(f"downloading {url}", flush=True)
    hdr = download(url, zp)
    to_cog(zp, a.year, cog)
    zp.unlink()
    # raster first, metadata last: a reader that finds the json finds a complete raster
    s3.upload_file(str(cog), bucket(), key(a.year),
                   ExtraArgs={"ContentType": "image/tiff", "CacheControl": "public, max-age=86400"})
    meta = {"year": a.year, "source": url, "upstream": hdr,
            "publisher": "USDA NASS Cropland Data Layer", "license": "public domain",
            "format": "COG, DEFLATE, 512 px tiles, no overviews",
            "bytes": cog.stat().st_size,
            "written_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    s3.put_object(Bucket=bucket(), Key=key(a.year).replace(".tif", ".json"),
                  Body=json.dumps(meta, indent=2).encode(), ContentType="application/json")
    cog.unlink()
    print(f"mirrored {key(a.year)} ({meta['bytes'] / 1e9:.2f} GB)")


if __name__ == "__main__":
    main()
