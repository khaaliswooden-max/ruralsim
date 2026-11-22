#!/usr/bin/env python3
"""Give already-published viewers gzipped data (D-055).

    python3 tools/repack_viewers.py --dry-run              # count what would change
    python3 tools/repack_viewers.py                        # repack every published viewer
    python3 tools/repack_viewers.py --fips 17031 04013     # just these counties

publish_world.py now writes worlds/<dir>/current/viewer_data/<file>.gz beside each data
file and points the viewer at them (build_site.gzip_viewer). The worlds published before
that serve plain JSON: Cook IL's viewer downloads 219 MB. This tool reads each published
viewer's current files from R2 through the S3 API, writes the .gz copies, and then the
patched index.html, last, so a viewer never points at files that are not there yet. The
plain files stay, for browsers without DecompressionStream. A viewer already patched is
skipped, so the run resumes. The archived snapshots/ are not touched.
Needs R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET.
"""
from __future__ import annotations

import argparse, collections, concurrent.futures as cf, json, pathlib, sys, tempfile, time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))


def one(s3, bucket: str, entry: dict, dry: bool) -> tuple[str, str, int, int]:
    from build_site import gzip_viewer
    from publish_world import SHORT
    base = f"worlds/{entry['dir']}/current"
    try:
        html = s3.get_object(Bucket=bucket, Key=f"{base}/viewer/index.html")["Body"].read().decode()
    except Exception as e:
        return entry["fips5"], f"error: read html {str(e)[:100]}", 0, 0
    if "DecompressionStream" in html:
        return entry["fips5"], "current", 0, 0
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=f"{base}/viewer_data/"):
        keys += [o["Key"] for o in page.get("Contents", []) if not o["Key"].endswith(".gz")]
    with tempfile.TemporaryDirectory() as d:
        vd = pathlib.Path(d)
        for k in keys:
            (vd / k.rsplit("/", 1)[1]).write_bytes(s3.get_object(Bucket=bucket, Key=k)["Body"].read())
        before = sum(f.stat().st_size for f in vd.iterdir())
        new_html, gz = gzip_viewer(html, vd)
        if not gz:
            return entry["fips5"], "unrecognised viewer", before, before
        after = before - sum(f.with_suffix("").stat().st_size for f in gz) + sum(f.stat().st_size for f in gz)
        if dry:
            return entry["fips5"], "repacked", before, after
        try:
            for g in gz:
                s3.upload_file(str(g), bucket, f"{base}/viewer_data/{g.name}",
                               ExtraArgs={"ContentType": "application/gzip", "CacheControl": SHORT})
            s3.put_object(Bucket=bucket, Key=f"{base}/viewer/index.html", Body=new_html.encode(),
                          ContentType="text/html; charset=utf-8", CacheControl=SHORT)
        except Exception as e:
            return entry["fips5"], f"error: write {str(e)[:100]}", before, before
    return entry["fips5"], "repacked", before, after


def main(argv=None):
    from publish_world import bucket, client
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fips", nargs="*", default=[])
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args(argv)
    s3, b = client(), bucket()
    idx = json.loads(s3.get_object(Bucket=b, Key="worlds/index.json")["Body"].read())
    entries = [c for c in idx["counties"] if not a.fips or c["fips5"] in set(a.fips)]
    print(f"{len(entries)} published viewers{' (dry run)' if a.dry_run else ''}", flush=True)
    n, mb0, mb1, t0 = collections.Counter(), 0, 0, time.time()
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for i, (f, status, x0, x1) in enumerate(ex.map(lambda e: one(s3, b, e, a.dry_run), entries), 1):
            key = "error" if status.startswith("error") else status
            n[key] += 1
            if key == "repacked":
                mb0, mb1 = mb0 + x0, mb1 + x1
            if key not in ("repacked", "current"):
                print(f"  {f}: {status}", flush=True)
            if i % 200 == 0:
                print(f"  {i}/{len(entries)} in {time.time() - t0:.0f} s", flush=True)
    print(f"{'would repack' if a.dry_run else 'repacked'} {n['repacked']}, already current {n['current']}, "
          f"unrecognised {n['unrecognised viewer']}, errors {n['error']}; viewer download "
          f"{mb0 / 1e9:.1f} GB -> {mb1 / 1e9:.1f} GB across them")
    if n["error"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
