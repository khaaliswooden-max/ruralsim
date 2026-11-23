#!/usr/bin/env python3
"""Daily wet-bulb, dew point and air temperature 1991-2020 per county, in R2 (D-054; LR-3).

    python3 tools/mirror_power.py                       # all 3,144 counties -> R2
    python3 tools/mirror_power.py --fips 01131 54047    # just these
    python3 tools/mirror_power.py --local out/ --fips 01131    # no upload (testing)

The cooling-water module of the step-2 engine needs humidity, and no published climate
file has any (nClimDiv has temperature and precipitation only; the optional Open-Meteo
series has no humidity column and is rate-limited, D-050). NASA POWER's daily API
(MERRA-2 reanalysis, about 0.5 x 0.625 degrees, public, no key) returns 30 years for one
point in about 1.5 s. One request per county, at the county centroid from
data/county_master.csv:

    climate/power/daily/<fips5>.parquet   date, t2m_c, t2mdew_c, t2mwet_c (daily means)
    climate/power/summary.parquet         per county: annual and monthly mean wet-bulb,
                                          99th / 99.6th percentile and maximum of the daily
                                          mean wet-bulb, and days per year at or above 20,
                                          22 and 24 degrees C
    climate/power/_meta.json              source, counts, failures (written last)

These are daily means. A daily-mean wet-bulb percentile is lower than an hourly design
value such as ASHRAE's 0.4% wet-bulb, so the summary names it for what it is. A county
already in R2 is skipped unless --force, so an interrupted run resumes. NASA POWER data
are free and open; NASA asks that it be credited as the source.
"""
from __future__ import annotations

import argparse, concurrent.futures as cf, datetime, io, json, pathlib, sys, tempfile, time, urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

API = ("https://power.larc.nasa.gov/api/temporal/daily/point?parameters=T2M,T2MDEW,T2MWET"
       "&community=AG&longitude={lon:.4f}&latitude={lat:.4f}&start=19910101&end=20201231&format=JSON")
PREFIX = "climate/power/"
UA = {"User-Agent": "RuralSim/1.0 (+https://www.ruralsim.io; county twin build)"}
FILL = -999.0
WORKERS = 4  # NASA POWER is a shared public service: keep the load modest


def fetch(lat: float, lon: float, tries: int = 6) -> dict:
    url = API.format(lat=lat, lon=lon)
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt + 1 == tries:
                raise
            time.sleep(min(10 * 2 ** attempt, 300))
            print(f"  retry {attempt + 1} ({str(e)[:80]})", flush=True)


def to_frame(payload: dict) -> pd.DataFrame:
    p = payload["properties"]["parameter"]
    df = pd.DataFrame({"t2m_c": p["T2M"], "t2mdew_c": p["T2MDEW"], "t2mwet_c": p["T2MWET"]})
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.replace(FILL, np.nan).rename_axis("date").reset_index()
    return df


def summarize(fips: str, df: pd.DataFrame) -> dict:
    tw = df.set_index("date")["t2mwet_c"]
    years = tw.index.year.nunique()
    row = {"fips5": fips, "days": int(tw.notna().sum()),
           "tw_mean_annual_c": round(float(tw.mean()), 2),
           "tw_dailymean_p99_c": round(float(tw.quantile(0.99)), 2),
           "tw_dailymean_p996_c": round(float(tw.quantile(0.996)), 2),
           "tw_dailymean_max_c": round(float(tw.max()), 2)}
    for t in (20, 22, 24):
        row[f"days_per_year_tw_ge_{t}c"] = round(float((tw >= t).sum()) / years, 1)
    for m, v in tw.groupby(tw.index.month).mean().items():
        row[f"tw_mean_m{m:02d}_c"] = round(float(v), 2)
    return row


def counties(fips: list[str]) -> pd.DataFrame:
    m = pd.read_csv(REPO / "data" / "county_master.csv", dtype=str)
    m = m[m["geography_vintage"] == "2024"][["fips5", "centroid_lat", "centroid_lon"]]
    if fips:
        m = m[m["fips5"].isin(fips)]
    return m.astype({"centroid_lat": float, "centroid_lon": float})


def parquet_bytes(df: pd.DataFrame) -> bytes:
    import duckdb
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "x.parquet"
        con = duckdb.connect(); con.register("df", df)
        con.sql(f"COPY df TO '{p}' (FORMAT parquet, COMPRESSION zstd)")
        return p.read_bytes()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fips", nargs="*", default=[])
    ap.add_argument("--local", metavar="DIR")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    todo = counties(a.fips)
    if a.local:
        out = pathlib.Path(a.local); (out / "daily").mkdir(parents=True, exist_ok=True)
        put = lambda key, body: (out / key.removeprefix(PREFIX)).write_bytes(body)  # noqa: E731
        have = set()
    else:
        from publish_world import bucket, client
        s3, b = client(), bucket()
        put = lambda key, body: s3.put_object(Bucket=b, Key=key, Body=body,  # noqa: E731
                                              ContentType="application/octet-stream",
                                              CacheControl="public, max-age=86400")
        have = set()
        if not a.force:
            pag = s3.get_paginator("list_objects_v2")
            for page in pag.paginate(Bucket=b, Prefix=PREFIX + "daily/"):
                have |= {o["Key"].rsplit("/", 1)[1][:5] for o in page.get("Contents", [])}

    def one(r):
        key = f"{PREFIX}daily/{r.fips5}.parquet"
        if r.fips5 in have:
            return r.fips5, None, "skipped"
        try:
            df = to_frame(fetch(r.centroid_lat, r.centroid_lon))
            put(key, parquet_bytes(df))
            return r.fips5, summarize(r.fips5, df), "ok"
        except Exception as e:
            return r.fips5, None, f"failed: {str(e)[:160]}"

    rows, failed, skipped = [], [], 0
    t0 = time.time()
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for i, (f, s, status) in enumerate(ex.map(one, todo.itertuples()), 1):
            if s:
                rows.append(s)
            elif status == "skipped":
                skipped += 1
            else:
                failed.append(f); print(f"  {f}: {status}", flush=True)
            if i % 100 == 0:
                print(f"  {i}/{len(todo)} in {time.time() - t0:.0f} s", flush=True)
    summary = pd.DataFrame(rows)
    if not a.local and skipped:  # keep the summary rows of counties skipped this time
        try:
            import duckdb
            import os
            base = (os.environ.get("RURALSIM_DATA_BASE")
                    or "https://data.ruralsim.io").rstrip("/")
            con = duckdb.connect(); con.sql("INSTALL httpfs; LOAD httpfs")
            old = con.sql(f"SELECT * FROM '{base}/{PREFIX}summary.parquet'").df()
            summary = pd.concat([old[~old["fips5"].isin(summary.get("fips5", []))], summary])
        except Exception as e:
            print(f"  previous summary not read ({e}); summary holds this run's counties only", flush=True)
    if len(summary):
        put(PREFIX + "summary.parquet", parquet_bytes(summary.sort_values("fips5")))
    meta = {"source": "NASA POWER daily API v2 (MERRA-2), parameters T2M, T2MDEW, T2MWET, 1991-2020",
            "api": API.split("?")[0], "point": "county centroid (data/county_master.csv)",
            "credit": "Data obtained from the NASA Langley Research Center POWER Project",
            "note": "daily means: percentiles of the daily-mean wet-bulb are lower than hourly design values",
            "counties_requested": int(len(todo)), "fetched": len(rows), "skipped_present": skipped,
            "failed": failed, "summary_counties": int(len(summary)),
            "written_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    put(PREFIX + "_meta.json", json.dumps(meta, indent=2).encode())
    print(json.dumps({k: v for k, v in meta.items() if k != "failed"} | {"failed": len(failed)}, indent=2))
    if failed and len(failed) > 0.01 * len(todo):
        raise SystemExit(f"{len(failed)} counties failed; rerun to resume")


if __name__ == "__main__":
    main()
