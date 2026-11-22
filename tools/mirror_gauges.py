#!/usr/bin/env python3
"""USGS stream-gauge flow statistics, national, in R2 (D-056; layer request LR-6, quick version).

    python3 tools/mirror_gauges.py                       # all states -> R2
    python3 tools/mirror_gauges.py --local out/ --state AL KS    # no upload (testing)

The cooling-water module compares a site's draw with local streamflow. NHD flowlines in
the county worlds carry no flow. This quick version uses what USGS measures: every active
stream gauge with daily discharge (parameter 00060) from the NWIS site service, and for
each one the NWIS statistics service's day-of-year statistics (mean, 10th and 50th
percentile of daily flow over the gauge's record). Modelled flow for every NHD segment
(NHDPlus EROM) is the full version, left for later.

    water/nwis/gauges.parquet   site_no, station_nm, dec_lat_va, dec_long_va, drain_area_sqmi,
                                huc_cd, fips5_nwis (NWIS's county), fips5 (2024 county by
                                point-in-polygon), begin_yr, end_yr, years,
                                mean_flow_cfs (mean of the 366 day-of-year means),
                                p10_min_cfs (lowest day-of-year 10th percentile: a low-flow
                                index for the driest time of year), p50_min_cfs,
                                p10_mMM_cfs and mean_mMM_cfs (monthly averages of the
                                day-of-year values)
    water/nwis/_meta.json       source, counts, failures (written last)

Gauges sit on rivers, not in counties: a county may have none, or only a gauge on a river
that drains a far larger area (drain_area_sqmi says which). The engine should pick the
gauge on the stream a site would draw from and scale by drainage area, and say so.
NWIS statistics are provisional where recent data are. Public domain (USGS).
"""
from __future__ import annotations

import argparse, concurrent.futures as cf, datetime, io, json, pathlib, sys, tempfile, time, urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import pandas as pd  # noqa: E402

SITE = ("https://waterservices.usgs.gov/nwis/site/?format=rdb&stateCd={st}&siteType=ST&hasDataTypeCd=dv"
        "&parameterCd=00060&siteOutput=expanded&siteStatus=active")
STAT = ("https://waterservices.usgs.gov/nwis/stat/?format=rdb&sites={sites}&statReportType=daily"
        "&statTypeCd=mean,p10,p50&parameterCd=00060")
UA = {"User-Agent": "RuralSim/1.0 (+https://www.ruralsim.io; county twin build)"}
STATES = ("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH "
          "NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY").split()
BATCH = 10  # the statistics service takes at most 10 sites per request
WORKERS = 4
PREFIX = "water/nwis/"


def get(url: str, tries: int = 6) -> str:
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r:
                return r.read().decode()
        except urllib.error.HTTPError as e:
            if e.code == 404:  # NWIS: no data for this request
                return ""
            if e.code < 500 and e.code != 429 or attempt + 1 == tries:
                raise
        except Exception:
            if attempt + 1 == tries:
                raise
        time.sleep(min(10 * 2 ** attempt, 300))


def rdb(text: str) -> pd.DataFrame:
    lines = [l for l in text.splitlines() if l and not l.startswith("#")]
    if len(lines) < 2:
        return pd.DataFrame()
    return pd.read_csv(io.StringIO("\n".join([lines[0]] + lines[2:])), sep="\t", dtype=str)


def sites(st: str) -> pd.DataFrame:
    d = rdb(get(SITE.format(st=st)))
    if d.empty:
        return d
    d = d[d["site_tp_cd"] == "ST"]
    d["fips5_nwis"] = d["state_cd"].str.zfill(2) + d["county_cd"].str.zfill(3)
    return d[["site_no", "station_nm", "dec_lat_va", "dec_long_va", "drain_area_va", "huc_cd", "fips5_nwis"]]


def summarize(stat: pd.DataFrame) -> pd.DataFrame:
    """Day-of-year statistics -> one row per gauge."""
    if stat.empty:
        return pd.DataFrame(columns=["site_no"])
    s = stat.copy()
    for c in ("mean_va", "p10_va", "p50_va", "begin_yr", "end_yr", "month_nu"):
        s[c] = pd.to_numeric(s[c], errors="coerce")
    rows = []
    for site, g in s.groupby("site_no"):
        r = {"site_no": site, "begin_yr": int(g["begin_yr"].min()), "end_yr": int(g["end_yr"].max()),
             "mean_flow_cfs": round(float(g["mean_va"].mean()), 3),
             "p10_min_cfs": round(float(g["p10_va"].min()), 3), "p50_min_cfs": round(float(g["p50_va"].min()), 3)}
        r["years"] = r["end_yr"] - r["begin_yr"] + 1
        for m, gm in g.groupby("month_nu"):
            r[f"mean_m{int(m):02d}_cfs"] = round(float(gm["mean_va"].mean()), 3)
            r[f"p10_m{int(m):02d}_cfs"] = round(float(gm["p10_va"].mean()), 3)
        rows.append(r)
    return pd.DataFrame(rows)


def county_fips(df: pd.DataFrame) -> pd.Series:
    """2024 county of each gauge by point-in-polygon (Census 2024 boundaries)."""
    import geopandas as gpd
    from eia_files import ensure
    from mirror_eia import CENSUS
    cty = gpd.read_file(f"zip://{ensure(CENSUS)}").to_crs("EPSG:4326")[["GEOID", "geometry"]]
    pts = gpd.GeoDataFrame(df[["site_no"]], geometry=gpd.points_from_xy(
        pd.to_numeric(df["dec_long_va"]), pd.to_numeric(df["dec_lat_va"])), crs="EPSG:4326")
    j = gpd.sjoin(pts, cty, how="left", predicate="within").drop_duplicates("site_no").set_index("site_no")
    return df["site_no"].map(j["GEOID"])


def build(out: pathlib.Path, states: list[str]) -> dict:
    t0 = time.time()
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        site_frames = list(ex.map(sites, states))
    s = pd.concat([f for f in site_frames if not f.empty], ignore_index=True).drop_duplicates("site_no")
    print(f"{len(s)} active stream gauges with daily discharge in {len(states)} states "
          f"({time.time() - t0:.0f} s)", flush=True)
    batches = [list(s["site_no"][i:i + BATCH]) for i in range(0, len(s), BATCH)]
    stats, failed = [], []

    def one(b):
        try:
            return summarize(rdb(get(STAT.format(sites=",".join(b))))), None
        except Exception as e:
            return None, (b, str(e)[:120])

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for i, (df, err) in enumerate(ex.map(one, batches), 1):
            if err:
                failed += err[0]; print(f"  batch failed: {err[1]}", flush=True)
            elif not df.empty:
                stats.append(df)
            if i % 100 == 0:
                print(f"  {i}/{len(batches)} batches in {time.time() - t0:.0f} s", flush=True)
    st = pd.concat(stats, ignore_index=True) if stats else pd.DataFrame(columns=["site_no"])
    g = s.merge(st, on="site_no", how="left")
    g = g.rename(columns={"drain_area_va": "drain_area_sqmi"})
    for c in ("dec_lat_va", "dec_long_va", "drain_area_sqmi"):
        g[c] = pd.to_numeric(g[c], errors="coerce")
    g.insert(g.columns.get_loc("fips5_nwis") + 1, "fips5", county_fips(g))
    import duckdb
    con = duckdb.connect(); con.register("g", g)
    con.sql(f"COPY (SELECT * FROM g ORDER BY site_no) TO '{out / 'gauges.parquet'}' (FORMAT parquet, COMPRESSION zstd)")
    master = pd.read_csv(REPO / "data" / "county_master.csv", dtype=str)
    now = set(master.loc[master["geography_vintage"] == "2024", "fips5"])
    meta = {"source": "USGS NWIS site service and statistics service (daily, parameter 00060)",
            "sites_url": SITE.split("?")[0], "stat_url": STAT.split("?")[0], "license": "public domain (USGS)",
            "states": states, "gauges": int(len(g)), "gauges_with_stats": int(g["mean_flow_cfs"].notna().sum()),
            "counties_with_a_gauge": len(set(g["fips5"].dropna()) & now),
            "failed_sites": failed, "seconds": round(time.time() - t0),
            "written_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (out / "_meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", metavar="DIR")
    ap.add_argument("--state", nargs="*", default=[])
    a = ap.parse_args(argv)
    states = [x.upper() for x in a.state] or list(STATES)
    if a.local:
        out = pathlib.Path(a.local); out.mkdir(parents=True, exist_ok=True)
        meta = build(out, states)
    else:
        from publish_world import bucket, client
        s3 = client()
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d)
            meta = build(out, states)
            if len(meta["failed_sites"]) > 0.02 * max(meta["gauges"], 1):
                raise SystemExit(f"{len(meta['failed_sites'])} gauges failed; not uploading")
            s3.upload_file(str(out / "gauges.parquet"), bucket(), PREFIX + "gauges.parquet",
                           ExtraArgs={"ContentType": "application/octet-stream",
                                      "CacheControl": "public, max-age=86400"})
            s3.put_object(Bucket=bucket(), Key=PREFIX + "_meta.json", Body=json.dumps(meta, indent=2).encode(),
                          ContentType="application/json", CacheControl="public, max-age=300")
    print(json.dumps({k: v for k, v in meta.items() if k not in ("failed_sites", "states")}
                     | {"failed_sites": len(meta["failed_sites"])}, indent=2))


if __name__ == "__main__":
    main()
