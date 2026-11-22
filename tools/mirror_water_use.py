#!/usr/bin/env python3
"""USGS county water use, 2015, in R2 (D-056; layer request LR-4, quick version).

    python3 tools/mirror_water_use.py                 # build and upload to R2
    python3 tools/mirror_water_use.py --local out/    # build into out/, no upload (testing)

The cooling-water module compares a site's draw with what a county already withdraws.
The step-2 spec asked for USGS's 2000-2020 monthly reanalysis, which is published by
HUC12 watershed and would need a watershed-to-county crosswalk (2.8 GB of boundaries) and,
for irrigation withdrawals, a 13 GB archive. This is the quick version agreed on
2026-11-21: USGS's own county-level compilation for 2015 (Dieter and others, 2018,
doi:10.5066/F7TB15V5), one table, every sector, withdrawals by groundwater and surface
water, fresh and saline. One year and annual only: the monthly series can follow if the
engine's results depend on seasonal swings.

    water/usgs_wateruse_2015/county.parquet   fips5 (2015 county), fips5_2024 (the same
                                              county today, or null), state, county, and
                                              every USGS column, codes kept, lower-cased
                                              with - as _ (e.g. pt_wfrto = thermoelectric
                                              fresh withdrawals, Mgal/d)
    water/usgs_wateruse_2015/_meta.json       source, units, unmatched counties (written last)

Units are as USGS publishes them: withdrawals in million gallons per day, populations in
thousands. "--" (not estimated) becomes null. Boundaries are 2015's: Connecticut's eight
old counties have no 2024 match (the nine planning regions cut across them), nor do
Alaska's Valdez-Cordova (02261, split in 2019 into 02063 and 02066). Those rows keep a
null fips5_2024 rather than a guessed split. Public domain (USGS).
"""
from __future__ import annotations

import argparse, datetime, io, json, pathlib, sys, tempfile, urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import pandas as pd  # noqa: E402

from eia_files import ensure  # noqa: E402  (retrying shared download)

URL = ("https://www.sciencebase.gov/catalog/file/get/5af3311be4b0da30c1b245d8"
       "?f=__disk__eb%2F74%2Feb%2Feb74ebb41169c76aaf374990bd5a71cac82604c1")
DOI = "https://doi.org/10.5066/F7TB15V5"
PREFIX = "water/usgs_wateruse_2015/"
ID_COLS = ("state", "statefips", "county", "countyfips", "fips5", "year")


def parse(raw: bytes) -> pd.DataFrame:
    d = pd.read_csv(io.BytesIO(raw), skiprows=1, dtype=str)  # row 0 is the citation
    d.columns = [c.strip().lower().replace("-", "_") for c in d.columns]
    d = d.rename(columns={"fips": "fips5"})
    for c in d.columns:
        if c not in ID_COLS:
            d[c] = pd.to_numeric(d[c].replace("--", None), errors="coerce")
    return d


def build(out: pathlib.Path) -> dict:
    master = pd.read_csv(REPO / "data" / "county_master.csv", dtype=str)
    now = set(master.loc[master["geography_vintage"] == "2024", "fips5"])
    # ScienceBase's URL carries no file name: cache it under the published one
    path = ensure(URL, sub="usgs", name="usco2015v2.0.csv")
    d = parse(path.read_bytes())
    d.insert(d.columns.get_loc("fips5") + 1, "fips5_2024", d["fips5"].where(d["fips5"].isin(now)))
    import duckdb
    con = duckdb.connect(); con.register("d", d)
    con.sql(f"COPY (SELECT * FROM d ORDER BY fips5) TO '{out / 'county.parquet'}' (FORMAT parquet, COMPRESSION zstd)")
    matched = set(d["fips5_2024"].dropna())
    meta = {"source": "Dieter and others (2018), Estimated use of water in the United States, county-level data "
                      "for 2015, ver. 2.0", "doi": DOI, "url": URL, "license": "public domain (USGS)",
            "year": 2015, "units": {"withdrawals": "Mgal/d", "population": "thousands"},
            "column_codes": "USGS codes, lower-cased, '-' as '_': sector prefix (ps public supply, do domestic, "
                            "in industrial, ir irrigation, ic crop, ig golf, li livestock, aq aquaculture, "
                            "mi mining, pt thermoelectric total, po once-through, pc recirculating, to total) "
                            "+ measure (wgwfr groundwater fresh, wswfr surface fresh, wfrto fresh total, ...)",
            "rows": int(len(d)), "counties_2024_matched": len(matched),
            "counties_2024_without_2015_row": sorted(now - matched),
            "rows_without_2024_county": sorted(set(d.loc[d["fips5_2024"].isna(), "fips5"])),
            "written_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (out / "_meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", metavar="DIR")
    a = ap.parse_args(argv)
    if a.local:
        out = pathlib.Path(a.local); out.mkdir(parents=True, exist_ok=True)
        meta = build(out)
    else:
        from publish_world import bucket, client
        s3 = client()
        with tempfile.TemporaryDirectory() as dd:
            out = pathlib.Path(dd)
            meta = build(out)
            s3.upload_file(str(out / "county.parquet"), bucket(), PREFIX + "county.parquet",
                           ExtraArgs={"ContentType": "application/octet-stream",
                                      "CacheControl": "public, max-age=86400"})
            s3.put_object(Bucket=bucket(), Key=PREFIX + "_meta.json", Body=json.dumps(meta, indent=2).encode(),
                          ContentType="application/json", CacheControl="public, max-age=300")
    print(json.dumps({k: v for k, v in meta.items() if k != "rows_without_2024_county"}, indent=2))


if __name__ == "__main__":
    main()
