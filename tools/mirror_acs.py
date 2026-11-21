#!/usr/bin/env python3
"""ACS 5-year household income by quintile, per county, in R2 (D-053; layer request LR-11).

    python3 tools/mirror_acs.py                 # build and upload to R2
    python3 tools/mirror_acs.py --local out/    # build into out/, no upload (testing)

The step-2 engine withholds its lowest-quintile energy-cost-share output: the
SAIPE-calibrated lognormal in tools/harness/households.py puts the bottom quintile's mean
income near $1,200 in Wilcox AL. The Census Bureau publishes the quintiles themselves:

- B19081: mean household income of each quintile and of the top 5 percent
- B19080: upper limit of each quintile, and the lower limit of the top 5 percent

They come from the ACS table-based summary files on www2.census.gov, one pipe-delimited
file per table for every geography, which need no API key (api.census.gov now requires
one). Rows with GEO_ID 0500000USsssccc are counties. Written to R2:

    acs/<year>/income_quintiles.parquet   fips5, mean_q1..q5, mean_top5, upper_q1..q4,
                                          lower_top5, each with _moe, and *_topcoded flags
    acs/<year>/_meta.json                 sources, counts, missing counties (written last)

Census special values (negative sentinels such as -666666666) become null. 250001 is the
top-code ("250,000 or more"): kept as 250001, with its *_topcoded flag set. Public domain.
"""
from __future__ import annotations

import argparse, datetime, json, pathlib, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import pandas as pd  # noqa: E402

from eia_files import ensure  # noqa: E402

YEAR = 2024  # ACS 2020-2024 5-year
SF = "https://www2.census.gov/programs-surveys/acs/summary_file/{y}/table-based-SF/data/5YRData/acsdt5y{y}-{t}.dat"
TABLES = {
    "b19081": ["mean_q1", "mean_q2", "mean_q3", "mean_q4", "mean_q5", "mean_top5"],
    "b19080": ["upper_q1", "upper_q2", "upper_q3", "upper_q4", "lower_top5"],
}
TOPCODE = 250001


def parse(path: pathlib.Path, table: str) -> pd.DataFrame:
    """County rows of one table-based summary file as named columns."""
    df = pd.read_csv(path, sep="|", dtype=str)
    df = df[df["GEO_ID"].str.startswith("0500000US")].copy()
    out = pd.DataFrame({"fips5": df["GEO_ID"].str[-5:].values})
    for i, name in enumerate(TABLES[table], start=1):
        for kind, suffix in (("E", ""), ("M", "_moe")):
            v = pd.to_numeric(df[f"{table.upper()}_{kind}{i:03d}"], errors="coerce").values
            out[name + suffix] = pd.Series(v).where(pd.Series(v) >= 0).values  # sentinels -> null
        out[name + "_topcoded"] = out[name] == TOPCODE
    return out


def build(out: pathlib.Path, year: int = YEAR) -> dict:
    master = pd.read_csv(REPO / "data" / "county_master.csv", dtype=str)
    want = set(master.loc[master["geography_vintage"] == "2024", "fips5"])
    parts = []
    for t in TABLES:
        url = SF.format(y=year, t=t)
        parts.append(parse(ensure(url, sub="acs"), t))
    df = parts[0].merge(parts[1], on="fips5", how="outer")
    df.insert(1, "acs_year", f"{year - 4}-{year}")
    df = df[df["fips5"].isin(want)].sort_values("fips5")
    import duckdb
    con = duckdb.connect()
    con.register("df", df)
    con.sql(f"COPY df TO '{out / 'income_quintiles.parquet'}' (FORMAT parquet, COMPRESSION zstd)")
    missing = sorted(want - set(df["fips5"]))
    meta = {
        "survey": f"ACS 5-year {year - 4}-{year}",
        "tables": {"B19081": "mean household income by quintile and top 5%",
                   "B19080": "household income quintile upper limits and top-5% lower limit"},
        "sources": [SF.format(y=year, t=t) for t in TABLES],
        "license": "public domain (U.S. Census Bureau)",
        "counties": int(len(df)),
        "counties_missing": missing,
        "mean_q1_null": int(df["mean_q1"].isna().sum()),
        "topcoded_cells": int(sum(df[c].sum() for c in df.columns if c.endswith("_topcoded"))),
        "written_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    (out / "_meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", metavar="DIR")
    ap.add_argument("--year", type=int, default=YEAR)
    a = ap.parse_args(argv)
    if a.local:
        out = pathlib.Path(a.local); out.mkdir(parents=True, exist_ok=True)
        print(json.dumps(build(out, a.year), indent=2))
        return
    from publish_world import bucket, client
    s3, prefix = client(), f"acs/{a.year}/"
    with tempfile.TemporaryDirectory() as d:
        out = pathlib.Path(d)
        meta = build(out, a.year)
        s3.upload_file(str(out / "income_quintiles.parquet"), bucket(), prefix + "income_quintiles.parquet",
                       ExtraArgs={"ContentType": "application/octet-stream", "CacheControl": "public, max-age=86400"})
        s3.put_object(Bucket=bucket(), Key=prefix + "_meta.json", Body=json.dumps(meta, indent=2).encode(),
                      ContentType="application/json", CacheControl="public, max-age=300")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
