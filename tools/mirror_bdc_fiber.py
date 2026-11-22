#!/usr/bin/env python3
"""FCC Broadband Data Collection: fiber availability per H3 hexagon and fiber providers per county, in R2 (D-058; LR-7).

    python3 tools/mirror_bdc_fiber.py --list                  # show the as-of dates and fiber files the API offers
    python3 tools/mirror_bdc_fiber.py                         # latest as-of date, every state -> R2
    python3 tools/mirror_bdc_fiber.py --as-of 2025-06-30 --state AL KS
    python3 tools/mirror_bdc_fiber.py --from-dir zips/ --as-of 2025-06-30   # state files downloaded by hand
    python3 tools/mirror_bdc_fiber.py --local out/ --state RI               # no upload (testing)

The step-2 fiber module needs to know where fiber is offered, by whom. The FCC's
National Broadband Map publishes fixed availability by provider, technology and location,
as one file per state and technology. This reads the fiber files (technology code 50)
through the BDC public data API (broadbandmap.fcc.gov/api/public, which needs a free FCC
account: FCC_USERNAME is the account's email and FCC_TOKEN its API token, both GitHub
secrets) and aggregates them. The website itself refuses GitHub runners (403); the API
answers them. --from-dir reads the same zips if they were downloaded by hand.

The location Fabric is excluded: no location identifier, address or coordinate is written.
Locations are only counted, inside H3 resolution-8 hexagons (about 0.7 km2) and counties:

    broadband/bdc/<as_of>/fiber_h3.parquet      h3_res8_id, fips5 (a hexagon crossing a county
                                                line has one row per county), state,
                                                fiber_locations, residential, business,
                                                providers, max_down_mbps, max_up_mbps,
                                                locations_ge_1000_mbps
    broadband/bdc/<as_of>/fiber_county.parquet  fips5, state, fiber_providers, provider_ids,
                                                brand_names, fiber_locations, hexes_with_fiber
    broadband/bdc/<as_of>/fiber_providers.parquet  provider_id, frn, brand_name, states, locations
    broadband/bdc/<as_of>/_meta.json            source, files read, counts (written last)

Availability is what providers report they can serve within 10 business days, not
subscriptions or take rates, and the FCC challenge process is still revising it. Counts are
of locations where fiber is offered, not a share of all locations: the denominator would
need the Fabric. County comes from the census block (block_geoid), so it is exact. The
FCC's data are public; cite "FCC National Broadband Map, BDC, as of <date>".
"""
from __future__ import annotations

import argparse, datetime, io, json, os, pathlib, sys, tempfile, time, urllib.error, urllib.parse, urllib.request, zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

API = "https://broadbandmap.fcc.gov/api/public/map"
FIBER = "50"
UA = "RuralSim/1.0 (+https://www.ruralsim.io; county twin build)"
PREFIX = "broadband/bdc/"
STATES = ("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH "
          "NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY").split()


def headers() -> dict:
    # strip: a secret pasted with a trailing newline or space is the commonest cause of a 401
    u, t = (os.environ.get("FCC_USERNAME") or "").strip(), (os.environ.get("FCC_TOKEN") or "").strip()
    if not u or not t:
        raise SystemExit("FCC_USERNAME and FCC_TOKEN must be set (GitHub secrets); the BDC API answers 401 without them")
    return {"username": u, "hash_value": t, "User-Agent": UA}


def credential_shape() -> str:
    """What is wrong with the secrets, without printing them."""
    raw_u, raw_t = os.environ.get("FCC_USERNAME") or "", os.environ.get("FCC_TOKEN") or ""
    u, t = raw_u.strip(), raw_t.strip()
    return (f"username looks like an email: {'@' in u and '.' in u.split('@')[-1]}, "
            f"username had surrounding whitespace: {raw_u != u}; token length {len(t)} (FCC tokens are 44), "
            f"token had surrounding whitespace: {raw_t != t}, token has inner spaces: {' ' in t}")


def get(path: str, params: dict | None = None, tries: int = 6) -> bytes:
    url = f"{API}/{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers()), timeout=600) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                body = e.read()[:200].decode(errors="replace")
                raise SystemExit(f"FCC API refused {path} with HTTP {e.code}: {body}. [{credential_shape()}] "
                                 "401: check the FCC_USERNAME / FCC_TOKEN secrets; 403: the runner is blocked "
                                 "(download the state fiber files by hand and use --from-dir)")
            if e.code < 500 and e.code != 429 or attempt + 1 == tries:
                raise
        except Exception:
            if attempt + 1 == tries:
                raise
        time.sleep(min(15 * 2 ** attempt, 300))


def as_of_dates() -> list[str]:
    d = json.loads(get("listAsOfDates"))["data"]
    return sorted({x["as_of_date"][:10] for x in d if x.get("data_type") == "availability"})


def listing(as_of: str) -> list[dict]:
    return json.loads(get(f"downloads/listAvailabilityData/{as_of}", {"category": "State"})).get("data") or []


def fiber_files(as_of: str, rows: list[dict] | None = None) -> list[dict]:
    """The state-level fixed-broadband availability files for fiber at this as-of date."""
    rows = listing(as_of) if rows is None else rows
    return [f for f in rows if str(f.get("technology_code")) == FIBER
            and "fixed" in str(f.get("subcategory", f.get("technology_type", "fixed"))).lower()]


def describe(rows: list[dict]) -> dict:
    """The listing's shape: field names and the distinct values of the short fields."""
    keys = sorted({k for r in rows for k in r})
    vals = {k: sorted({str(r.get(k)) for r in rows})[:15] for k in keys
            if len({str(r.get(k)) for r in rows}) <= 15}
    return {"rows": len(rows), "fields": keys, "values": vals, "first": rows[:2]}


def state_of(f: dict) -> str:
    """USPS code of a listing row (the API gives state_fips; be lenient about the name)."""
    fips = str(f.get("state_fips") or "").zfill(2)
    return FIPS_TO_USPS.get(fips) or str(f.get("state_usps") or f.get("state_name") or fips)


def _fips_to_usps() -> dict:
    import pandas as pd
    m = pd.read_csv(REPO / "data" / "county_master.csv", dtype=str, usecols=["state_fips", "state_abbr"])
    return dict(zip(m["state_fips"].str.zfill(2), m["state_abbr"]))


FIPS_TO_USPS = _fips_to_usps()


def aggregate_state(csv_paths: list[pathlib.Path], out: pathlib.Path, tag: str) -> None:
    """One state's fiber rows -> partial hexagon, county and provider tables. location_id is counted, never written."""
    import duckdb
    con = duckdb.connect()
    files = ", ".join(f"'{p}'" for p in csv_paths)
    con.sql(f"""CREATE TABLE f AS SELECT provider_id, frn, brand_name, location_id,
                  TRY_CAST(max_advertised_download_speed AS DOUBLE) down,
                  TRY_CAST(max_advertised_upload_speed AS DOUBLE) up,
                  business_residential_code brc, state_usps,
                  substr(lpad(block_geoid, 15, '0'), 1, 5) fips5, h3_res8_id h3
                FROM read_csv([{files}], header=true, all_varchar=true)
                WHERE technology = '{FIBER}'""")
    q = lambda sql, name: con.sql(f"COPY ({sql}) TO '{out / f'{name}_{tag}.parquet'}' (FORMAT parquet)")  # noqa: E731
    q("""WITH loc AS (SELECT location_id, h3, fips5, any_value(state_usps) state, max(down) down, max(up) up,
                             bool_or(brc IN ('R', 'X')) res, bool_or(brc IN ('B', 'X')) bus
                      FROM f GROUP BY location_id, h3, fips5),
              prov AS (SELECT h3, fips5, count(DISTINCT provider_id) providers FROM f GROUP BY h3, fips5)
         SELECT l.h3 h3_res8_id, l.fips5, any_value(l.state) state, count(*) fiber_locations,
                count(*) FILTER (WHERE res) residential, count(*) FILTER (WHERE bus) business,
                any_value(p.providers) providers, max(down) max_down_mbps, max(up) max_up_mbps,
                count(*) FILTER (WHERE down >= 1000) locations_ge_1000_mbps
         FROM loc l JOIN prov p USING (h3, fips5) GROUP BY l.h3, l.fips5""", "h3")
    q("""SELECT fips5, any_value(state_usps) state, count(DISTINCT provider_id) fiber_providers,
                string_agg(DISTINCT provider_id, ',' ORDER BY provider_id) provider_ids,
                string_agg(DISTINCT brand_name, '; ' ORDER BY brand_name) brand_names,
                count(DISTINCT location_id) fiber_locations, count(DISTINCT h3) hexes_with_fiber
         FROM f GROUP BY 1""", "county")
    q("""SELECT provider_id, any_value(frn) frn, any_value(brand_name) brand_name, any_value(state_usps) state,
                count(DISTINCT location_id) locations, count(*) n_rows
         FROM f GROUP BY 1""", "prov")


def combine(parts: pathlib.Path, out: pathlib.Path) -> dict:
    """Per-state partials -> the three national tables. States share no location or county."""
    import duckdb
    con = duckdb.connect()
    w = lambda sql, name: con.sql(f"COPY ({sql}) TO '{out / name}' (FORMAT parquet, COMPRESSION zstd)")  # noqa: E731
    w(f"SELECT * FROM '{parts}/h3_*.parquet' ORDER BY fips5, h3_res8_id", "fiber_h3.parquet")
    w(f"SELECT * FROM '{parts}/county_*.parquet' ORDER BY fips5", "fiber_county.parquet")
    w(f"""SELECT provider_id, any_value(frn) frn, any_value(brand_name) brand_name,
                 string_agg(DISTINCT state, ',' ORDER BY state) states, CAST(sum(locations) AS BIGINT) locations
          FROM '{parts}/prov_*.parquet' GROUP BY 1 ORDER BY 1""", "fiber_providers.parquet")
    one = lambda sql: con.sql(sql).fetchone()[0]  # noqa: E731
    return {"rows": one(f"SELECT sum(n_rows) FROM '{parts}/prov_*.parquet'"),
            "fiber_locations": one(f"SELECT sum(fiber_locations) FROM '{parts}/county_*.parquet'"),
            "hexagons": one(f"SELECT count(DISTINCT h3_res8_id) FROM '{parts}/h3_*.parquet'"),
            "counties_with_fiber": one(f"SELECT count(*) FROM '{parts}/county_*.parquet'"),
            "providers": one(f"SELECT count(DISTINCT provider_id) FROM '{parts}/prov_*.parquet'")}


def extract(zbytes: bytes, d: pathlib.Path, name: str) -> list[pathlib.Path]:
    out = []
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        for n in z.namelist():
            if n.lower().endswith(".csv"):
                p = d / f"{name}_{pathlib.Path(n).name}"
                p.write_bytes(z.read(n)); out.append(p)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", help="BDC as-of date, YYYY-MM-DD (default: latest)")
    ap.add_argument("--state", nargs="*", default=[])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--from-dir", metavar="DIR", help="state fiber zips or CSVs downloaded by hand")
    ap.add_argument("--local", metavar="DIR")
    a = ap.parse_args(argv)
    states = {s.upper() for s in a.state} or set(STATES)
    with tempfile.TemporaryDirectory() as td:
        work = pathlib.Path(td)
        parts, out = work / "parts", work / "out"
        parts.mkdir(); out.mkdir()
        files_read = []
        if a.from_dir:
            if not a.as_of:
                raise SystemExit("--from-dir needs --as-of (the date on the files)")
            as_of = a.as_of
            for i, p in enumerate(sorted(pathlib.Path(a.from_dir).iterdir())):
                if p.suffix.lower() not in (".zip", ".csv"):
                    continue
                csvs = extract(p.read_bytes(), work, p.stem) if p.suffix.lower() == ".zip" else [p]
                aggregate_state(csvs, parts, f"f{i}")
                files_read.append({"file_name": p.name})
                for c in csvs:
                    if c.parent == work:
                        c.unlink()
        else:
            dates = as_of_dates()
            as_of = a.as_of or dates[-1]
            if a.list:  # show the raw listing for the latest two dates, so the filter can be checked
                out = {"as_of_dates": dates}
                for d in ([as_of] if a.as_of else dates[-2:][::-1]):
                    rows = listing(d)
                    out[d] = describe(rows) | {"fiber_files": len(fiber_files(d, rows))}
                print(json.dumps(out, indent=2, default=str)); return
            files = fiber_files(as_of)
            files = [f for f in files if state_of(f) in states]
            print(f"as of {as_of}: {len(files)} state fiber files", flush=True)
            for i, f in enumerate(files, 1):
                z = get(f"downloads/downloadFile/availability/{f['file_id']}")
                csvs = extract(z, work, str(f["file_id"]))
                aggregate_state(csvs, parts, str(f["file_id"]))
                for c in csvs:
                    c.unlink()
                files_read.append({k: f.get(k) for k in ("file_id", "file_name", "state_fips", "record_count")})
                print(f"  {i}/{len(files)} {state_of(f)} {f.get('file_name')} {len(z) / 1e6:.0f} MB", flush=True)
        if not files_read:
            raise SystemExit("no fiber files read")
        counts = combine(parts, out)
        meta = {"source": "FCC Broadband Data Collection, National Broadband Map, fixed availability, technology 50 (fiber)",
                "api": API, "as_of": as_of, "files": files_read, "states": sorted(states) if a.state else "all",
                "fabric": "excluded: no location id, address or coordinate written; locations only counted",
                **counts, "written_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        (out / "_meta.json").write_text(json.dumps(meta, indent=2))
        if a.local:
            dest = pathlib.Path(a.local) / as_of; dest.mkdir(parents=True, exist_ok=True)
            for p in out.iterdir():
                (dest / p.name).write_bytes(p.read_bytes())
        else:
            from publish_world import bucket, client
            s3 = client()
            for name in ("fiber_h3.parquet", "fiber_county.parquet", "fiber_providers.parquet", "_meta.json"):
                s3.upload_file(str(out / name), bucket(), f"{PREFIX}{as_of}/{name}",
                               ExtraArgs={"ContentType": "application/json" if name.endswith(".json") else
                                          "application/octet-stream", "CacheControl": "public, max-age=86400"})
        print(json.dumps({k: v for k, v in meta.items() if k != "files"} | {"files": len(files_read)}, indent=2))


if __name__ == "__main__":
    main()
