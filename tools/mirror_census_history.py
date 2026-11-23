#!/usr/bin/env python3
"""Census population inputs for the back-test, as published at the time, in R2 (D-064; LR-12).

    python3 tools/mirror_census_history.py                          # all vintages + Census 2000 -> R2
    python3 tools/mirror_census_history.py --vintage 2007 2009 --decennial 2000
    python3 tools/mirror_census_history.py --local out/             # no upload (testing)

PREREGISTRATION §4.2.3 (D-200) and D-112 build a back-test county's existing load from the
population estimate for July of T0-1 *as published in vintage T0-1*, divided by persons per
household from the latest decennial census not after T0-1. Later vintages and the
intercensal series revise the numbers with hindsight, so they are not used. This writes
the two tables the engine reads (tools/engines/ai_infra/data.py):

    census/popest/v<vintage>/county.parquet   fips5, year, population (every July estimate the
                                              vintage published), state, county, vintage
    census/decennial/2000/households.parquet  fips5, population (P001001), households
                                              (P015001), persons_per_household

Population estimates: the Census Bureau's own vintage files, co-est<vintage>-alldata.csv,
POPESTIMATE<year> columns (vintages 2004-2007 and 2009 cover 2000 onward, 2014 covers 2010
onward). Census 2000: Summary File 1, national file (0Final_National): geography file rows
with summary level 050 and geographic component 00, population from segment 1 and
households from segment 3, checked against the published national totals (281,421,906
persons and 105,480,101 households in the 50 states and DC). FIPS codes are as published;
the back-test counties' codes are unchanged since 2000. Census 2010 households (for
Jackson AL) are not here yet. Public domain (U.S. Census Bureau).
"""
from __future__ import annotations

import argparse, datetime, io, json, pathlib, sys, tempfile, zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import pandas as pd  # noqa: E402

from eia_files import ensure  # noqa: E402  (retrying shared download)

POPEST = {2004: "2000-2004", 2005: "2000-2005", 2006: "2000-2006", 2007: "2000-2007", 2009: "2000-2009",
          2014: "2010-2014"}
POPEST_URL = "https://www2.census.gov/programs-surveys/popest/datasets/{span}/counties/totals/co-est{v}-alldata.csv"
SF1_2000 = "https://www2.census.gov/census_2000/datasets/Summary_File_1/0Final_National/{f}"
US_2000 = {"population": 281_421_906, "households": 105_480_101}  # 50 states + DC, published


def popest(vintage: int) -> pd.DataFrame:
    path = ensure(POPEST_URL.format(span=POPEST[vintage], v=vintage), sub="census", name=f"co-est{vintage}-alldata.csv")
    d = pd.read_csv(path, dtype=str, encoding="latin-1")
    d.columns = [c.upper() for c in d.columns]
    d = d[d["SUMLEV"].str.zfill(3) == "050"]  # 2004 and 2006 drop leading zeros ("50", state "1")
    years = sorted(int(c[11:]) for c in d.columns if c.startswith("POPESTIMATE") and c[11:].isdigit())
    long = d.melt(id_vars=["STATE", "COUNTY", "STNAME", "CTYNAME"], value_vars=[f"POPESTIMATE{y}" for y in years],
                  var_name="col", value_name="population")
    out = pd.DataFrame({"fips5": long["STATE"].str.zfill(2) + long["COUNTY"].str.zfill(3),
                        "year": long["col"].str[11:].astype(int),
                        "population": pd.to_numeric(long["population"]).astype("int64"),
                        "state": long["STNAME"], "county": long["CTYNAME"], "vintage": vintage})
    return out.sort_values(["fips5", "year"]).reset_index(drop=True)


def _lines(zpath):
    with zipfile.ZipFile(zpath) as z:
        with z.open(z.namelist()[0]) as f:
            yield from io.TextIOWrapper(f, encoding="latin-1")


def decennial_2000() -> pd.DataFrame:
    """Census 2000 SF1: P001001 (segment 1) and P015001 households (segment 3), per county."""
    geo = {}
    for line in _lines(ensure(SF1_2000.format(f="usgeo_uf1.zip"), sub="census", name="sf1_2000_usgeo_uf1.zip")):
        if line[8:11] == "050" and line[11:13] == "00":      # county, whole (not a geographic component)
            geo[line[18:25]] = line[29:34]                      # LOGRECNO -> state + county FIPS

    def first_cell(seg: str) -> dict:
        out = {}
        for line in _lines(ensure(SF1_2000.format(f=f"us000{seg}_uf1.zip"), sub="census", name=f"sf1_2000_us000{seg}_uf1.zip")):
            p = line.split(",", 6)
            if p[4] in geo:
                out[geo[p[4]]] = int(p[5])
        return out

    pop, hh = first_cell("01"), first_cell("03")
    d = pd.DataFrame({"fips5": sorted(geo.values())})
    d["population"], d["households"] = d["fips5"].map(pop).astype("int64"), d["fips5"].map(hh).astype("int64")
    d["persons_per_household"] = (d["population"] / d["households"]).round(4)
    states = d[d["fips5"].str[:2] != "72"]
    if int(states["population"].sum()) != US_2000["population"] or int(states["households"].sum()) != US_2000["households"]:
        raise SystemExit(f"Census 2000 totals do not match the published ones: {int(states['population'].sum())} persons, "
                         f"{int(states['households'].sum())} households")
    return d


def write(df: pd.DataFrame, path: pathlib.Path) -> None:
    import duckdb
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(); con.register("df", df)
    con.sql(f"COPY df TO '{path}' (FORMAT parquet, COMPRESSION zstd)")


def build(out: pathlib.Path, vintages: list[int], decennials: list[int]) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    written = {}
    for v in vintages:
        d = popest(v)
        key = f"census/popest/v{v}/"
        write(d, out / key / "county.parquet")
        meta = {"source": POPEST_URL.format(span=POPEST[v], v=v), "vintage": v,
                "note": "the vintage as published (not the intercensal revision); PREREGISTRATION 4.2.3, D-112, D-064",
                "license": "public domain (U.S. Census Bureau)", "counties": int(d["fips5"].nunique()),
                "years": sorted(int(y) for y in d["year"].unique()), "written_utc": now}
        (out / key / "_meta.json").write_text(json.dumps(meta, indent=2)); written[key] = meta
    for y in decennials:
        if y != 2000:
            raise SystemExit(f"Census {y} households are not implemented yet")
        d = decennial_2000()
        key = "census/decennial/2000/"
        write(d, out / key / "households.parquet")
        meta = {"source": SF1_2000.format(f="") + " (usgeo, us00001 P001001, us00003 P015001)", "year": 2000,
                "license": "public domain (U.S. Census Bureau)", "counties": int(len(d)),
                "check": f"50 states + DC sum to the published {US_2000['population']:,} persons and "
                         f"{US_2000['households']:,} households", "written_utc": now}
        (out / key / "_meta.json").write_text(json.dumps(meta, indent=2)); written[key] = meta
    return written


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--vintage", type=int, nargs="*", default=sorted(POPEST))
    ap.add_argument("--decennial", type=int, nargs="*", default=[2000])
    ap.add_argument("--local", metavar="DIR")
    a = ap.parse_args(argv)
    if a.local:
        written = build(pathlib.Path(a.local), a.vintage, a.decennial)
    else:
        from publish_world import bucket, client
        s3 = client()
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d)
            written = build(out, a.vintage, a.decennial)
            for key in written:  # data first, _meta.json last, per table
                for f in sorted((out / key).glob("*.parquet")):
                    s3.upload_file(str(f), bucket(), key + f.name, ExtraArgs={
                        "ContentType": "application/octet-stream", "CacheControl": "public, max-age=86400"})
                s3.upload_file(str(out / key / "_meta.json"), bucket(), key + "_meta.json", ExtraArgs={
                    "ContentType": "application/json", "CacheControl": "public, max-age=300"})
    print(json.dumps({k: {x: v[x] for x in ("counties",) if x in v} | {"years": v.get("years", [v.get("year")])[-3:]}
                      for k, v in written.items()}, indent=2))


if __name__ == "__main__":
    main()
