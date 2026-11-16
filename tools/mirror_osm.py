#!/usr/bin/env python3
"""Copy the Geofabrik state extracts a batch needs into R2, once, serially (D-036).

    python3 tools/mirror_osm.py 48301 06071 ...        # the extracts covering these counties
    python3 tools/mirror_osm.py --state TX

Run by the plan job of .github/workflows/build-counties.yml before the county jobs
start. In the canary run (43794676050) up to ten county jobs downloading from
Geofabrik at the same time were refused for 7 of 57 counties; one polite serial
download per extract, then county jobs reading from R2, removes that load.

Bucket layout: osm/<state>-latest.osm.pbf and osm/<state>-latest.osm.pbf.md5 (the md5
file is Geofabrik's own). An extract younger than --max-age-days in R2 is left as is.
Each extract is deleted locally once uploaded, so the runner's disk never holds more
than one. Needs R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET.
"""
from __future__ import annotations

import argparse, datetime, pathlib, sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import fetch_osm  # noqa: E402
from publish_world import bucket, client  # noqa: E402

PREFIX = fetch_osm.OSM_MIRROR_PREFIX


def mirror(regions: list[dict], max_age_days: float = 7.0) -> list[str]:
    s3 = client()
    now = datetime.datetime.now(datetime.timezone.utc)
    done = []
    for r in regions:
        name = pathlib.Path(r["urls"]["pbf"]).name
        try:
            head = s3.head_object(Bucket=bucket(), Key=PREFIX + name)
            age = (now - head["LastModified"]).total_seconds() / 86400
            if age < max_age_days:
                print(f"  {name}: in R2, {age:.1f} days old; keeping", flush=True)
                done.append(name)
                continue
        except Exception:
            pass  # not mirrored yet
        # Geofabrik directly: never read back from the mirror we are filling
        saved = fetch_osm.OSM_MIRROR, fetch_osm._r2_ready
        fetch_osm.OSM_MIRROR, fetch_osm._r2_ready = "", (lambda: False)
        try:
            prov = fetch_osm.ensure_extract(r, max_age_days=0)
        finally:
            fetch_osm.OSM_MIRROR, fetch_osm._r2_ready = saved
        dest = fetch_osm.CACHE / name
        md5 = dest.with_name(name + ".md5")
        # pbf first, md5 last: a reader that finds the md5 finds a complete pbf
        s3.upload_file(str(dest), bucket(), PREFIX + name,
                       ExtraArgs={"ContentType": "application/octet-stream", "CacheControl": "public, max-age=3600"})
        s3.upload_file(str(md5), bucket(), PREFIX + name + ".md5",
                       ExtraArgs={"ContentType": "text/plain", "CacheControl": "public, max-age=3600"})
        print(f"  {name}: mirrored ({dest.stat().st_size / 1e6:.0f} MB, md5 {prov['md5']})", flush=True)
        dest.unlink()
        md5.unlink()
        done.append(name)
    return done


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("fips", nargs="*")
    ap.add_argument("--state", default="")
    ap.add_argument("--max-age-days", type=float, default=7.0)
    a = ap.parse_args(argv)
    from county_config import get
    from plan_build import current_counties
    fipses = list(a.fips)
    if a.state:
        fipses += [f for f, st in current_counties().items() if st == a.state.upper()]
    if not fipses:
        ap.error("give fips codes or --state")
    regions = fetch_osm.extracts_for([get(f).buf_bbox for f in fipses], fetch_osm.geofabrik_index())
    print(f"mirror: {len(regions)} extract(s): {', '.join(r['id'] for r in regions)}", flush=True)
    mirror(regions, a.max_age_days)


if __name__ == "__main__":
    main()
