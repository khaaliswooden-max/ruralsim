#!/usr/bin/env python3
"""EIA-860/861 tables for past years, in R2, for the back-test's T0-1 rule (D-062).

    python3 tools/mirror_eia_history.py --year 2004 2005 2006 2014     # -> R2 eia/<year>/
    python3 tools/mirror_eia_history.py --year 2014 --local out/        # no upload (testing)

PREREGISTRATION.md section 4.2.1 (step 3, D-200) has each back-test run read the EIA-860
and EIA-861 tables of the year before the site's announcement: Wasco OR 2004, Grant WA
2005, Mayes OK 2006, Jackson AL 2014. The engine refuses a back-test run until
eia/<T0-1>/_meta.json exists (tools/engines/ai_infra/gate.py) and never substitutes 2024.
This writes the same six tables as tools/mirror_eia.py does for 2024, with the same
column names wherever the year's files carry the field:

    eia860_generators, eia860_plants (county_fips, county_fips_method), eia861_utility_data,
    eia861_sales_ult_cust, eia861_short_form, eia861_service_territory (county_fips)

How the years differ, and what this does about it:
- EIA-861 2004-2006: EIA's republished archives (861_<year>.zip) use the 2012+ layout
  (Sales_Ult_Cust, Utility_Data, Service_Territories), read as for 2024. There was no
  short form before 2012, so eia861_short_form is empty, with the 2024 columns.
- EIA-861 2014 and EIA-860 2014: the 2012+ layouts, under that year's file names.
- EIA-860 2004-2010: the old flat files (PlantY04.xls, GenY04.xls, PRGenY04.xls; GeneratorY09.xls
  with Exist/Prop/Ret_IP sheets), whose column names change in 2007 and 2009. Columns
  are renamed to the 2024 names (PLNTCODE -> plant_code, NAMEPLATE -> nameplate_capacity_mw,
  ...) and the original columns are kept too. These years have no plant coordinates, so
  a plant takes its county from the 2024 table's point-in-polygon county for the same plant
  code (county_fips_method "plant_code_2024"), else from its county name ("name_match").
  A plant retired before 2024 and absent from that table has only the name match.
Counties are 2024 counties throughout (Census cb_2024), as in the worlds the engine reads.
Public domain (U.S. EIA).
"""
from __future__ import annotations

import argparse, datetime, io, json, pathlib, re, sys, tempfile, zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import pandas as pd  # noqa: E402

import mirror_eia as M  # noqa: E402  (shared readers and county matching)
from eia_files import ensure  # noqa: E402

PUBLIC = "https://data.ruralsim.io"


def urls(year: int) -> tuple[str, str]:
    e860 = f"https://www.eia.gov/electricity/data/eia860/archive/xls/eia860{year}.zip"
    # the republished 2001-2011 EIA-861 archives are 861_<year>.zip; 2012+ are f861<year>.zip
    e861 = (f"https://www.eia.gov/electricity/data/eia861/archive/zip/861_{year}.zip" if year < 2012
            else f"https://www.eia.gov/electricity/data/eia861/archive/zip/f861{year}.zip")
    return e860, e861


def member(z: zipfile.ZipFile, pattern: str) -> str:
    hits = [n for n in z.namelist() if re.search(pattern, n.rsplit("/", 1)[-1], re.I) and not n.endswith("/")]
    if not hits:
        raise KeyError(f"no file matching {pattern!r} in {z.filename}: {z.namelist()[:12]}")
    return hits[0]


class Renamed(zipfile.ZipFile):
    """A zip whose 2024 member names resolve to this year's files, so mirror_eia's readers run unchanged."""

    def __init__(self, path, names: dict):
        super().__init__(path)
        self._names = names

    def read(self, name, pwd=None):
        return super().read(self._names.get(name, name), pwd)


def z861(path, year: int) -> Renamed:
    z = zipfile.ZipFile(path)
    names = {"Sales_Ult_Cust_2024.xlsx": member(z, rf"^Sales_Ult_Cust_{year}\.xlsx?$"),
             "Utility_Data_2024.xlsx": member(z, rf"^Utility_Data_{year}\.xlsx?$"),
             "Service_Territory_2024.xlsx": member(z, rf"^Service_Territor(y|ies)_{year}\.xlsx?$")}
    try:
        names["Short_Form_2024.xlsx"] = member(z, rf"^Short_Form_{year}\.xlsx?$")
    except KeyError:
        pass
    return Renamed(path, names)


SHORT_FORM_COLUMNS = ["data_year", "utility_number", "utility_name", "state", "total_revenue_thousand_dollars",
                      "total_sales_mwh", "total_customers", "avg_rate_all_sectors_usd_per_kwh",
                      "kwh_per_customer_all_sectors", "ownership"]


def short_form(z: Renamed) -> pd.DataFrame:
    if "Short_Form_2024.xlsx" not in z._names:  # no EIA-861S before 2012
        return pd.DataFrame({c: pd.Series(dtype="object") for c in SHORT_FORM_COLUMNS})
    return M.read_short_form(z)


# EIA-860 before 2011: flat files, upper-case names -> the 2024 snake_case names
# (2004-2006 spell it PLNTCODE/CNTYNAME; 2007 COUNTY; 2009-2010 PLANT_CODE/UTILITY_ID)
OLD_PLANT = {"UTILCODE": "utility_id", "UTILITY_ID": "utility_id", "PLNTCODE": "plant_code", "PLANT_CODE": "plant_code",
             "PLNTNAME": "plant_name", "PLANT_NAME": "plant_name", "CNTYNAME": "county", "COUNTY": "county",
             "STATE": "state", "PLNTZIP": "zip", "ZIP5": "zip", "NERC": "nerc_region",
             "SERVAREA": "balancing_authority_name"}
OLD_GEN = {"UTILCODE": "utility_id", "UTILNAME": "utility_name", "PLNTCODE": "plant_code", "PLNTNAME": "plant_name",
           "STATE": "state", "GENCODE": "generator_id", "PRIMEMOVER": "prime_mover", "UNIT_CODE": "unit_code",
           "NAMEPLATE": "nameplate_capacity_mw", "SUMMCAP": "summer_capacity_mw", "WINTCAP": "winter_capacity_mw",
           "STATUS": "status", "INSVMONTH": "operating_month", "INSVYEAR": "operating_year",
           "RETIREMONTH": "planned_retirement_month", "RETIREYEAR": "planned_retirement_year",
           "ENERGY_SOURCE_1": "energy_source_1", "ENERGY_SOURCE1": "energy_source_1",
           # 2007-2010 spellings
           "UTILITY_ID": "utility_id", "UTILITY_NAME": "utility_name", "PLANT_CODE": "plant_code",
           "PLANT_NAME": "plant_name", "GENERATOR_ID": "generator_id", "PRIME_MOVER": "prime_mover",
           "SUMMER_CAPACITY": "summer_capacity_mw", "WINTER_CAPACITY": "winter_capacity_mw",
           "SUMMER_CAPABILITY": "summer_capacity_mw", "WINTER_CAPABILITY": "winter_capacity_mw",
           "OPERATING_MONTH": "operating_month", "OPERATING_YEAR": "operating_year",
           "RETIREMENT_MONTH": "retirement_month", "RETIREMENT_YEAR": "retirement_year", "COUNTY": "county"}
# 2009-2010 put existing, proposed and retired generators in one workbook
OLD_SHEETS = {"exist": "Operable", "prop": "Proposed", "ret_ip": "Retired and Canceled"}


def _norm(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    df.columns = [str(c).strip() for c in df.columns]
    df = df.rename(columns={c: mapping[c.upper()] for c in df.columns if c.upper() in mapping})
    df = df.loc[:, ~df.columns.duplicated()]
    df.columns = [M.snake(c) if c not in mapping.values() else c for c in df.columns]
    df = df[pd.to_numeric(df["plant_code"], errors="coerce").notna()].copy()
    df["plant_code"] = df["plant_code"].astype(int)
    return df


def _old(z: zipfile.ZipFile, pattern: str, mapping: dict) -> pd.DataFrame:
    return _norm(pd.read_excel(io.BytesIO(z.read(member(z, pattern))), header=0), mapping)


def generators(path, year: int) -> pd.DataFrame:
    z = zipfile.ZipFile(path)
    if year >= 2011:
        return M.read_generators(Renamed(path, {"3_1_Generator_Y2024.xlsx": member(z, rf"^3_1_Generator_Y{year}\.xlsx?$")}))
    yy = f"{year % 100:02d}"
    book = pd.read_excel(io.BytesIO(z.read(member(z, rf"^(Gen|Generator)Y?{yy}\.xls$"))), sheet_name=None, header=0)
    parts = [_norm(df, OLD_GEN).assign(sheet=OLD_SHEETS.get(name.lower(), "Operable")) for name, df in book.items()]
    try:
        parts.append(_old(z, rf"^PRGenY?{yy}\.xls$", OLD_GEN).assign(sheet="Proposed"))
    except KeyError:
        pass
    g = pd.concat(parts, ignore_index=True)
    for c in ("nameplate_capacity_mw", "summer_capacity_mw", "winter_capacity_mw"):
        if c in g:
            g[c] = pd.to_numeric(g[c], errors="coerce")
    return M.strings(g[["sheet"] + [c for c in g.columns if c != "sheet"]])


def plants(path, year: int, lookup: dict, counties, plants_2024: pd.DataFrame | None) -> pd.DataFrame:
    z = zipfile.ZipFile(path)
    if year >= 2012:  # coordinates are in the file from 2012
        return M.read_plants(Renamed(path, {"2___Plant_Y2024.xlsx": member(z, rf"^2___Plant_Y{year}\.xlsx?$")}),
                             lookup, counties)
    p = _old(z, rf"^PlantY?{year % 100:02d}\.xls$", OLD_PLANT)
    p["eia_county_fips"] = p.apply(lambda r: M.match_name(lookup, r["state"], r["county"]), axis=1)
    p["county_fips"], p["county_fips_method"] = None, None
    if plants_2024 is not None:
        cur = plants_2024[plants_2024["county_fips_method"] == "point_in_polygon"].drop_duplicates("plant_code")
        cur = cur.assign(plant_code=cur["plant_code"].astype(int)).set_index("plant_code")
        same_state = p["plant_code"].map(cur["state"]) == p["state"]  # a reused code in another state is not the plant
        hit = p["plant_code"].map(cur["county_fips"]).where(same_state)
        p.loc[hit.notna(), "county_fips"] = hit[hit.notna()]
        p.loc[hit.notna(), "county_fips_method"] = "plant_code_2024"
        p["latitude"] = p["plant_code"].map(cur["latitude"]).where(same_state)
        p["longitude"] = p["plant_code"].map(cur["longitude"]).where(same_state)
    miss = p["county_fips"].isna() & p["eia_county_fips"].notna()
    p.loc[miss, "county_fips"] = p.loc[miss, "eia_county_fips"]
    p.loc[miss, "county_fips_method"] = "name_match"
    return M.strings(p)


def build(year: int, out: pathlib.Path) -> dict:
    import geopandas as gpd
    master = pd.read_csv(REPO / "data" / "county_master.csv", dtype=str)
    master = master[master["geography_vintage"] == "2024"]
    lookup = M.county_lookup(master)
    counties = gpd.read_file(f"zip://{ensure(M.CENSUS)}").to_crs("EPSG:4326")
    counties["fips5"] = counties["GEOID"]
    counties = counties[counties["fips5"].isin(set(master["fips5"]))]
    e860, e861 = urls(year)
    p860, p861 = ensure(e860, name=f"eia860{year}.zip"), ensure(e861, name=f"f861{year}.zip")
    p2024 = None
    if year < 2012:
        import duckdb
        src = ensure(f"{PUBLIC}/eia/2024/eia860_plants.parquet", name="eia860_plants_2024.parquet")
        p2024 = duckdb.sql(f"SELECT plant_code, state, latitude, longitude, county_fips, county_fips_method "
                           f"FROM '{src}'").df()
    z = z861(p861, year)
    tables = {
        "eia860_generators": generators(p860, year),
        "eia860_plants": plants(p860, year, lookup, counties, p2024),
        "eia861_utility_data": M.read_utility_data(z),
        "eia861_sales_ult_cust": M.read_sales(z),
        "eia861_short_form": short_form(z),
        "eia861_service_territory": M.read_territory(z, lookup),
    }
    t = tables["eia861_service_territory"]
    if "short_form" not in t.columns:
        # the 2024 territory file flags short-form filers; older files do not. Derive it
        # from that year's short form (none before 2012, so every row is "N").
        sf = set(tables["eia861_short_form"]["utility_number"].dropna().astype(int))
        t["short_form"] = t["utility_number"].astype(int).map(lambda u: "Y" if u in sf else "N")
    for name, df in tables.items():
        M.write_parquet(df, out / f"{name}.parquet")
    p, t = tables["eia860_plants"], tables["eia861_service_territory"]
    us = p[p["state"].isin(set(master["state_abbr"]))]
    meta = {
        "year": year, "purpose": "back-test T0-1 inputs (PREREGISTRATION.md 4.2.1, D-062)",
        "sources": {"eia860": e860, "eia861": e861, "census_counties": M.CENSUS},
        "license": "public domain (U.S. EIA; U.S. Census Bureau)",
        "rows": {k: int(len(v)) for k, v in tables.items()},
        "short_form": "none before 2012 (empty table, 2024 columns)" if year < 2012 else "present",
        "plants_us_50_dc": int(len(us)),
        "plants_county_by_method": {str(k): int(v) for k, v in
                                    us["county_fips_method"].fillna("none").value_counts().items()},
        "territory_rows_matched": int(t["county_fips"].notna().sum()),
        "territory_rows_unmatched": int(t["county_fips"].isna().sum()),
        "counties": "2024 Census counties (cb_2024), as in the worlds",
        "written_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    (out / "_meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, nargs="+", required=True)
    ap.add_argument("--local", metavar="DIR")
    a = ap.parse_args(argv)
    for year in a.year:
        if year == M.YEAR:
            raise SystemExit(f"{year} is written by mirror_eia.py")
        if a.local:
            out = pathlib.Path(a.local) / str(year); out.mkdir(parents=True, exist_ok=True)
            print(json.dumps(build(year, out), indent=2))
            continue
        from publish_world import bucket, client
        s3 = client()
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d)
            meta = build(year, out)
            for f in sorted(out.glob("*.parquet")):
                s3.upload_file(str(f), bucket(), f"eia/{year}/{f.name}",
                               ExtraArgs={"ContentType": "application/octet-stream",
                                          "CacheControl": "public, max-age=86400"})
            s3.put_object(Bucket=bucket(), Key=f"eia/{year}/_meta.json", Body=json.dumps(meta, indent=2).encode(),
                          ContentType="application/json", CacheControl="public, max-age=300")  # last
        print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
