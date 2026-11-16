#!/usr/bin/env python3
"""Plan a county build batch and pre-download shared inputs once (D-031).

    python3 tools/plan_build.py --counties 48301,01131      # prints the JSON list of fips
    python3 tools/plan_build.py --state NE --prefetch       # also fills $RURALSIM_CACHE

Used by .github/workflows/build-counties.yml: the plan job runs it with --prefetch so the
NOAA climate files and Census Gazetteer files are downloaded once per batch and handed to
every county job through the Actions cache. With R2 credentials in the environment the
state OpenStreetMap extracts are copied to R2 once (tools/mirror_osm.py, D-036) and county
jobs read them from there; without, up to four extracts go through the Actions cache.
"""
from __future__ import annotations

import argparse, csv, json, pathlib, sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
MATRIX_MAX = 256  # GitHub Actions limit on jobs in one matrix
OSM_PREFETCH_MAX = 4  # state extracts shared through the Actions cache (10 GB per repo)


def current_counties() -> dict[str, str]:
    with open(REPO / "data" / "county_master.csv", newline="") as fh:
        return {r["fips5"]: r["state_abbr"] for r in csv.DictReader(fh) if r.get("geography_vintage") == "2024"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--counties", default="", help="comma-separated fips5 codes")
    ap.add_argument("--state", default="", help="two-letter state: every current county in it")
    ap.add_argument("--prefetch", action="store_true", help="download shared inputs into $RURALSIM_CACHE")
    a = ap.parse_args(argv)

    universe = current_counties()
    fipses = [f.strip().zfill(5) for f in a.counties.split(",") if f.strip()]
    if a.state:
        fipses += [f for f, st in universe.items() if st == a.state.strip().upper()]
    fipses = sorted(set(fipses))
    bad = [f for f in fipses if f not in universe]
    if bad:
        raise SystemExit(f"not current (2024-vintage) counties: {bad}")
    if not fipses:
        raise SystemExit("no counties selected: give --counties and/or --state")
    if len(fipses) > MATRIX_MAX:
        raise SystemExit(f"{len(fipses)} counties exceeds the {MATRIX_MAX}-job matrix limit; split the batch")

    if a.prefetch:
        from county_config import get
        import fetch_osm, fetch_climate, place_water_systems
        cfgs = [get(f) for f in fipses]  # also caches each boundary from TIGERweb
        index = fetch_osm.geofabrik_index()
        regions = fetch_osm.extracts_for([c.buf_bbox for c in cfgs], index)
        if fetch_osm._r2_ready():
            # D-036: copy each extract to R2 once, serially; county jobs read it from there
            import mirror_osm
            print(f"prefetch: mirroring {len(regions)} OSM extract(s) to R2: "
                  f"{', '.join(r['id'] for r in regions)}", file=sys.stderr)
            mirror_osm.mirror(regions)
        elif len(regions) <= OSM_PREFETCH_MAX:
            print(f"prefetch: {len(regions)} OSM extract(s): {', '.join(r['id'] for r in regions)}", file=sys.stderr)
            for r in regions:
                fetch_osm.ensure_extract(r, max_age_days=7)
        else:
            # The Actions cache holds 10 GB per repository; a many-state batch would overflow it.
            # Each county job downloads its own state extract instead (D-035).
            print(f"prefetch: {len(regions)} OSM extracts needed; over {OSM_PREFETCH_MAX}, "
                  "so each county job downloads its own", file=sys.stderr)
        fetch_climate.climdiv_files()
        place_water_systems.gazetteer()
        place_water_systems.zctas()

    print(json.dumps(fipses))


if __name__ == "__main__":
    main()
