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


# Fallback source when download.geofabrik.de is unreachable (D-046). On 2026-11-19 it reset
# every connection for hours; runs #27 and #28 failed in this step after ~8 min of retries
# because West Virginia and Ohio had never been mirrored. openstreetmap.fr publishes the
# same OpenStreetMap data (ODbL) as four U.S. Census-region extracts, refreshed daily; a
# state is cut from its region with osmium-tool along the Geofabrik outline we already
# carry (data/geofabrik_us_index.json), so county jobs see the same file name as before.
OSMFR = "https://download.openstreetmap.fr/extracts/north-america/"
CENSUS_REGION = {
    "us-south": "alabama arkansas delaware district-of-columbia florida georgia kentucky louisiana "
                "maryland mississippi north-carolina oklahoma south-carolina tennessee texas "
                "virginia west-virginia",
    "us-midwest": "illinois indiana iowa kansas michigan minnesota missouri nebraska north-dakota "
                  "ohio south-dakota wisconsin",
    "us-northeast": "connecticut maine massachusetts new-hampshire new-jersey new-york "
                    "pennsylvania rhode-island vermont",
    "us-west": "arizona california colorado idaho montana nevada new-mexico oregon utah "
               "washington wyoming",
}
STATE_REGION = {st: reg for reg, sts in CENSUS_REGION.items() for st in sts.split()}


def geofabrik_up(timeout: int = 30) -> bool:
    """One quick probe, so a down Geofabrik costs seconds per batch, not 8 min per state."""
    import urllib.request
    url = "https://download.geofabrik.de/north-america/us/delaware-latest.osm.pbf.md5"
    for _ in range(2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=fetch_osm.UA),
                                        timeout=timeout) as r:
                if r.status == 200 and r.read(64):
                    return True
        except Exception as e:
            print(f"  Geofabrik probe failed: {e}", flush=True)
    return False


def _from_osmfr(r: dict, dest: pathlib.Path, regional: dict) -> str:
    """Cut one state from its openstreetmap.fr Census-region extract; return the source URL."""
    import json, shutil, subprocess
    slug = r["id"].rsplit("/", 1)[-1]
    reg = STATE_REGION.get(slug)
    if reg is None:
        raise RuntimeError(f"no openstreetmap.fr region extract covers {slug}")
    if shutil.which("osmium") is None:
        raise RuntimeError("osmium-tool is not installed (apt-get install osmium-tool)")
    url = f"{OSMFR}{reg}-latest.osm.pbf"
    src = regional.get(reg)
    if src is None or not src.exists():
        src = fetch_osm.CACHE / f"{reg}-latest.osm.pbf"
        print(f"  downloading {url} ...", flush=True)
        if not fetch_osm._fetch_with_retry(url, src, 3, 30):
            raise RuntimeError(f"could not download {url}")
        regional[reg] = src
    feat = next(f for f in json.loads(fetch_osm.US_INDEX.read_text())["features"]
                if f["properties"]["id"] == r["id"])
    poly = dest.with_name(slug + ".geojson")
    poly.write_text(json.dumps({"type": "FeatureCollection", "features": [feat]}))
    subprocess.run(["osmium", "extract", "-p", str(poly), "-s", "smart", "--overwrite",
                    "-o", str(dest), str(src)], check=True)
    poly.unlink()
    if dest.stat().st_size < 1_000_000:
        raise RuntimeError(f"{dest.name} cut from {reg} is only {dest.stat().st_size} bytes")
    return url


def mirror(regions: list[dict], max_age_days: float = 7.0) -> list[str]:
    import json
    s3 = client()
    now = datetime.datetime.now(datetime.timezone.utc)
    done, regional, up = [], {}, None
    fetch_osm.CACHE.mkdir(parents=True, exist_ok=True)
    try:
        for r in regions:
            name = pathlib.Path(r["urls"]["pbf"]).name
            have = False
            try:
                head = s3.head_object(Bucket=bucket(), Key=PREFIX + name)
                have = True
                age = (now - head["LastModified"]).total_seconds() / 86400
                if age < max_age_days:
                    print(f"  {name}: in R2, {age:.1f} days old; keeping", flush=True)
                    done.append(name)
                    continue
            except Exception:
                pass  # not mirrored yet
            dest = fetch_osm.CACHE / name
            md5 = dest.with_name(name + ".md5")
            source = r["urls"]["pbf"]
            try:
                if up is None:
                    up = geofabrik_up()
                    if not up:
                        print("  Geofabrik unreachable; using openstreetmap.fr region extracts", flush=True)
                if up:
                    # Geofabrik directly: never read back from the mirror we are filling
                    saved = fetch_osm.OSM_MIRROR, fetch_osm._r2_ready
                    fetch_osm.OSM_MIRROR, fetch_osm._r2_ready = "", (lambda: False)
                    try:
                        fetch_osm.ensure_extract(r, max_age_days=0)
                    finally:
                        fetch_osm.OSM_MIRROR, fetch_osm._r2_ready = saved
                else:
                    source = _from_osmfr(r, dest, regional)
                    md5.write_text(f"{fetch_osm._md5(dest)}  {name}\n")
            except Exception as e:
                # one state must not stop the batch; a stale copy beats none
                print(f"  {name}: could not refresh ({str(e)[:200]})"
                      + ("; keeping the older copy in R2" if have else
                         "; counties needing it will try Geofabrik themselves"), flush=True)
                if have:
                    done.append(name)
                continue
            # pbf first, md5 last: a reader that finds the md5 finds a complete pbf
            s3.upload_file(str(dest), bucket(), PREFIX + name,
                           ExtraArgs={"ContentType": "application/octet-stream", "CacheControl": "public, max-age=3600"})
            s3.put_object(Bucket=bucket(), Key=PREFIX + name + ".source.json", ContentType="application/json",
                          Body=json.dumps({"source": source, "geofabrik_equivalent": r["urls"]["pbf"],
                                           "written_utc": now.isoformat()}).encode())
            s3.upload_file(str(md5), bucket(), PREFIX + name + ".md5",
                           ExtraArgs={"ContentType": "text/plain", "CacheControl": "public, max-age=3600"})
            print(f"  {name}: mirrored from {source} ({dest.stat().st_size / 1e6:.0f} MB)", flush=True)
            dest.unlink()
            md5.unlink()
            done.append(name)
    finally:
        for f in regional.values():
            f.unlink(missing_ok=True)
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
