#!/usr/bin/env python3
"""Replace the founder disclosure line in county viewers already published to R2 (D-048).

    python3 tools/rebrand_viewers.py --dry-run          # report what would change, write nothing
    python3 tools/rebrand_viewers.py                    # rewrite every published viewer
    python3 tools/rebrand_viewers.py --fips 01001 48029 # just these counties

PR #41 changed the disclosure line in `build_site.brand_viewer_html()`, so worlds published
from then on carry the new wording. The ~1,650 worlds published before it serve
`worlds/<dir>/current/viewer/index.html` with the old line. This tool reads each of those
files, swaps the old sentence for the new one, and writes it back with the same content
type and cache header the publisher uses. Nothing else in the file changes.

Only `current/` is touched. The copy under `snapshots/<snapshot>/viewer/` is the archived
build record, listed with its sha256 in the snapshot manifest, and stays as it was.

Safe to run more than once: a viewer that already has the new line is skipped. Run it after
any build batch that started before PR #41 has finished, or that batch's late publishes will
put the old line back. Needs R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET.
Run by .github/workflows/rebrand-viewers.yml (manual).
"""
from __future__ import annotations

import argparse, collections, concurrent.futures as cf, json, pathlib, sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

NEW = "RuralSim is a free, open-source project by Aldrich K. Wooden, Sr., founder of Get Rural America Done."
# the old sentence as published: HTML-escaped ampersand, and the raw form in case any viewer has it
OLD = ("RuralSim is a free, open-source project by Grid &amp; Grain's founder.",
       "RuralSim is a free, open-source project by Grid & Grain's founder.",
       "RuralSim is a free, open-source project by Grid &amp; Grain’s founder.",
       "RuralSim is a free, open-source project by Grid & Grain’s founder.")


def rebrand(html: str) -> tuple[str, str]:
    """(new html, status): status is 'updated', 'current' (already new) or 'missing'."""
    if NEW in html:
        return html, "current"
    for old in OLD:
        if old in html:
            return html.replace(old, NEW), "updated"
    return html, "missing"


def viewer_key(entry: dict) -> str:
    return entry.get("viewer") or f"worlds/{entry['dir']}/current/viewer/index.html"


def one(s3, bucket: str, entry: dict, dry: bool) -> tuple[str, str]:
    from publish_world import SHORT
    key = viewer_key(entry)
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        html = obj["Body"].read().decode("utf-8")
    except Exception as e:
        return entry["fips5"], f"error: read {str(e)[:120]}"
    out, status = rebrand(html)
    if status != "updated" or dry:
        return entry["fips5"], status
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=out.encode("utf-8"),
                      ContentType="text/html; charset=utf-8", CacheControl=SHORT)
    except Exception as e:
        return entry["fips5"], f"error: write {str(e)[:120]}"
    return entry["fips5"], status


def main(argv=None):
    from publish_world import bucket, client
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fips", nargs="*", default=[])
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args(argv)
    s3, b = client(), bucket()
    idx = json.loads(s3.get_object(Bucket=b, Key="worlds/index.json")["Body"].read())
    entries = [c for c in idx["counties"] if not a.fips or c["fips5"] in set(a.fips)]
    print(f"{len(entries)} published viewers{' (dry run)' if a.dry_run else ''}", flush=True)
    res = {}
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for i, (fips, status) in enumerate(ex.map(lambda e: one(s3, b, e, a.dry_run), entries), 1):
            res[fips] = status
            if status not in ("updated", "current"):
                print(f"  {fips}: {status}", flush=True)
            if i % 200 == 0:
                print(f"  {i}/{len(entries)}", flush=True)
    n = collections.Counter(s if not s.startswith("error") else "error" for s in res.values())
    verb = "would update" if a.dry_run else "updated"
    print(f"{verb} {n['updated']}, already current {n['current']}, "
          f"no disclosure line {n['missing']}, errors {n['error']}")
    if n["error"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
