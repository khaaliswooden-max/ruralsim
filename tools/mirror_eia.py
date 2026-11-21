#!/usr/bin/env python3
"""National EIA-860 / EIA-861 tables in R2 for the AI-infrastructure engine (D-051).

    python3 tools/mirror_eia.py                 # build the tables and upload them to R2
    python3 tools/mirror_eia.py --local out/    # build them into out/, no upload (testing)

Layer requests LR-1, LR-2 and LR-9 from the step-2 spec (specs/ai_infra_engine.yaml):

- LR-1  generator capacity: the EIA-860 Generator workbook (operable, proposed, retired
        and canceled sheets): nameplate / summer / winter MW, technology, status and
        operating and retirement years for every generator.
- LR-2  utility ownership type and residential rates: EIA-861 Utility_Data (ownership
        type, NERC region, activities) and Sales_Ult_Cust (revenue, MWh and customers
        by sector, per utility and state).
- LR-9  plant-to-county matching: fetch_grid.py matches plants on a substring of the
        county name, so "Clay" also takes "Clayton". Here every plant gets a county FIPS
        from its coordinates, point-in-polygon against the Census 2024 county boundaries
        (the same 3,144 counties the build uses), falling back to an exact
        normalized-name match only where coordinates are missing. EIA-861 service
        territory rows get a FIPS by the exact name match.

These are national tables, not per-county files, so nothing already published has to be
rebuilt: the engine joins them on plant code, utility number or county FIPS. Written to R2:

    eia/2024/eia860_generators.parquet
    eia/2024/eia860_plants.parquet           with county_fips, county_fips_method
    eia/2024/eia861_utility_data.parquet
    eia/2024/eia861_sales_ult_cust.parquet   with residential_avg_rate_usd_per_kwh
    eia/2024/eia861_short_form.parquet       EIA-861S small utilities: totals only (LR-10)
    eia/2024/eia861_service_territory.parquet with county_fips
    eia/2024/_meta.json                      sources, row counts, match rates (written last)

Column names are snake_case versions of EIA's. All tables are public domain (U.S. EIA,
Census). The per-county files written by fetch_grid.py are unchanged.
"""
from __future__ import annotations

import argparse, datetime, io, json, pathlib, re, sys, tempfile, unicodedata, zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import pandas as pd  # noqa: E402

from eia_files import EIA860, EIA861, ensure  # noqa: E402

YEAR = 2024
PREFIX = f"eia/{YEAR}/"
CENSUS = f"https://www2.census.gov/geo/tiger/GENZ{YEAR}/shp/cb_{YEAR}_us_county_500k.zip"
_SUFFIX = re.compile(r"\s+(county|parish|borough|census area|city and borough|municipality|"
                     r"planning region|municipio)$")


def snake(c) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(c)).strip("_").lower()
    return re.sub(r"_+", "_", s)


def norm_county(name: str, keep_city: bool = False) -> str:
    """'St. Clair County' -> 'saintclair'; 'Richmond city' -> 'richmond city' (keep_city)."""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\s+", " ", s.replace(".", " ").replace("'", "")).strip()
    s = re.sub(r"\bste\b", "sainte", re.sub(r"\bst\b", "saint", s))
    if not keep_city:
        s = _SUFFIX.sub("", s)
    # spacing differs between sources ("DeSoto" / "De Soto", "LaSalle" / "La Salle")
    return re.sub(r"[^a-z]", "", s[:-5]) + " city" if s.endswith(" city") else re.sub(r"[^a-z]", "", s)


def county_lookup(master: pd.DataFrame) -> dict:
    """(state, normalized name) -> fips5. Independent cities keep 'city', so Richmond
    city VA and Richmond County VA stay apart."""
    out = {}
    for r in master.itertuples():
        name = r.county_name
        city = name.lower().endswith(" city") and not name.lower().endswith("county")
        key = norm_county(name, keep_city=True) if city else norm_county(name)
        out[(r.state_abbr, key)] = r.fips5
    return out


def match_name(lookup: dict, state: str, county: str):
    if not isinstance(county, str) or not county.strip():
        return None
    for key in (norm_county(county, keep_city=True), norm_county(county),
                norm_county(county) + " city"):
        f = lookup.get((state, key))
        if f:
            return f
    return None


def strings(df: pd.DataFrame) -> pd.DataFrame:
    """Object columns as text (EIA mixes numbers and blanks), so parquet types are stable."""
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].map(lambda v: None if pd.isna(v) else str(v).strip())
    return df


def read_generators(z: zipfile.ZipFile) -> pd.DataFrame:
    book = pd.read_excel(io.BytesIO(z.read("3_1_Generator_Y2024.xlsx")), sheet_name=None, header=1)
    parts = []
    for sheet, df in book.items():
        df = df[pd.to_numeric(df["Plant Code"], errors="coerce").notna()].copy()  # drop footnote rows
        df.insert(0, "sheet", sheet)
        parts.append(df)
    g = pd.concat(parts, ignore_index=True)
    g.columns = [snake(c) for c in g.columns]
    g["plant_code"] = g["plant_code"].astype(int)
    for c in ("nameplate_capacity_mw", "summer_capacity_mw", "winter_capacity_mw", "minimum_load_mw"):
        if c in g:
            g[c] = pd.to_numeric(g[c], errors="coerce")
    return strings(g)


def read_plants(z: zipfile.ZipFile, lookup: dict, counties) -> pd.DataFrame:
    import geopandas as gpd
    p = pd.read_excel(io.BytesIO(z.read("2___Plant_Y2024.xlsx")), sheet_name="Plant", header=1)
    p = p[pd.to_numeric(p["Plant Code"], errors="coerce").notna()].copy()
    p.columns = [snake(c) for c in p.columns]
    p["plant_code"] = p["plant_code"].astype(int)
    p["latitude"] = pd.to_numeric(p["latitude"], errors="coerce")
    p["longitude"] = pd.to_numeric(p["longitude"], errors="coerce")
    has = p["latitude"].notna() & p["longitude"].notna()
    pts = gpd.GeoDataFrame(p[has][["plant_code"]], geometry=gpd.points_from_xy(
        p.loc[has, "longitude"], p.loc[has, "latitude"]), crs="EPSG:4326")
    j = gpd.sjoin(pts, counties[["fips5", "geometry"]], how="left", predicate="within")
    j = j.drop_duplicates("plant_code").set_index("plant_code")["fips5"]
    p["county_fips"] = p["plant_code"].map(j)
    p["county_fips_method"] = p["county_fips"].map(lambda v: None if pd.isna(v) else "point_in_polygon")
    miss = p["county_fips"].isna()
    byname = p[miss].apply(lambda r: match_name(lookup, r["state"], r["county"]), axis=1)
    p.loc[miss, "county_fips"] = byname
    p.loc[miss & byname.notna(), "county_fips_method"] = "name_match"
    # EIA's own county name, as a check on the coordinates
    p["eia_county_fips"] = p.apply(lambda r: match_name(lookup, r["state"], r["county"]), axis=1)
    return strings(p)


def read_utility_data(z: zipfile.ZipFile) -> pd.DataFrame:
    u = pd.read_excel(io.BytesIO(z.read("Utility_Data_2024.xlsx")), sheet_name="States", header=1)
    u = u[pd.to_numeric(u["Utility Number"], errors="coerce").notna()].copy()
    u.columns = [snake(c) for c in u.columns]
    u["utility_number"] = u["utility_number"].astype(int)
    return strings(u)


def read_sales(z: zipfile.ZipFile) -> pd.DataFrame:
    raw = pd.read_excel(io.BytesIO(z.read("Sales_Ult_Cust_2024.xlsx")), sheet_name="States", header=None)
    sector, measure, label = raw.iloc[0].ffill(), raw.iloc[1], raw.iloc[2]
    unit = {"Thousand Dollars": "revenue_kusd", "Megawatthours": "mwh", "Count": "customers"}
    cols = []
    for s, m, lab in zip(sector, measure, label):
        if pd.notna(m) and str(lab) in unit:
            cols.append(f"{snake(s)}_{unit[str(lab)]}")
        else:
            cols.append("data_type" if str(lab).startswith("Data Type") else snake(lab))
    s = raw.iloc[3:].copy()
    s.columns = cols
    s = s[pd.to_numeric(s["utility_number"], errors="coerce").notna()].copy()
    s["utility_number"] = s["utility_number"].astype(int)
    for c in cols:
        if c.endswith(("_revenue_kusd", "_mwh", "_customers")):
            s[c] = pd.to_numeric(s[c], errors="coerce")
    # average revenue per kWh (not a tariff): thousand dollars / MWh = $/kWh
    s["residential_avg_rate_usd_per_kwh"] = (s["residential_revenue_kusd"] / s["residential_mwh"]).where(
        s["residential_mwh"] > 0)
    s["residential_kwh_per_customer"] = (s["residential_mwh"] * 1000 / s["residential_customers"]).where(
        s["residential_customers"] > 0)
    return strings(s)


def read_short_form(z: zipfile.ZipFile) -> pd.DataFrame:
    """EIA-861S, the short form small utilities file instead of the full 861 (LR-10).
    It has totals only, no split by sector: avg_rate_all_sectors_usd_per_kwh is total
    revenue / total MWh, and stands in for a residential rate only with that caveat."""
    f = pd.read_excel(io.BytesIO(z.read("Short_Form_2024.xlsx")), header=0)
    f = f[pd.to_numeric(f["Utility Number"], errors="coerce").notna()].copy()
    f.columns = [snake(c) for c in f.columns]
    f["utility_number"] = f["utility_number"].astype(int)
    for c in ("total_revenue_thousand_dollars", "total_sales_mwh", "total_customers"):
        f[c] = pd.to_numeric(f[c], errors="coerce")  # "." means not reported
    f["avg_rate_all_sectors_usd_per_kwh"] = (f["total_revenue_thousand_dollars"] / f["total_sales_mwh"]).where(
        f["total_sales_mwh"] > 0)
    f["kwh_per_customer_all_sectors"] = (f["total_sales_mwh"] * 1000 / f["total_customers"]).where(
        f["total_customers"] > 0)
    return strings(f)


def read_territory(z: zipfile.ZipFile, lookup: dict) -> pd.DataFrame:
    t = pd.read_excel(io.BytesIO(z.read("Service_Territory_2024.xlsx")), sheet_name=None)
    t = pd.concat(t.values(), ignore_index=True)
    t.columns = [snake(c) for c in t.columns]
    t = t[pd.to_numeric(t["utility_number"], errors="coerce").notna()].copy()
    t["utility_number"] = t["utility_number"].astype(int)
    t["county_fips"] = t.apply(lambda r: match_name(lookup, r["state"], r["county"]), axis=1)
    return strings(t)


def write_parquet(df: pd.DataFrame, path: pathlib.Path) -> None:
    import duckdb
    con = duckdb.connect()
    con.register("df", df)
    con.sql(f"COPY df TO '{path}' (FORMAT parquet, COMPRESSION zstd)")


def build(out: pathlib.Path) -> dict:
    import geopandas as gpd
    master = pd.read_csv(REPO / "data" / "county_master.csv", dtype=str)
    master = master[master["geography_vintage"] == "2024"]
    lookup = county_lookup(master)
    counties = gpd.read_file(f"zip://{ensure(CENSUS)}").to_crs("EPSG:4326")
    counties["fips5"] = counties["GEOID"]
    counties = counties[counties["fips5"].isin(set(master["fips5"]))]
    z860, z861 = zipfile.ZipFile(ensure(EIA860)), zipfile.ZipFile(ensure(EIA861))
    tables = {
        "eia860_generators": read_generators(z860),
        "eia860_plants": read_plants(z860, lookup, counties),
        "eia861_utility_data": read_utility_data(z861),
        "eia861_sales_ult_cust": read_sales(z861),
        "eia861_short_form": read_short_form(z861),
        "eia861_service_territory": read_territory(z861, lookup),
    }
    for name, df in tables.items():
        write_parquet(df, out / f"{name}.parquet")
    p, t = tables["eia860_plants"], tables["eia861_service_territory"]
    us = p[p["state"].isin(set(master["state_abbr"]))]
    both = us["county_fips"].notna() & us["eia_county_fips"].notna()
    meta = {
        "year": YEAR,
        "sources": {"eia860": EIA860, "eia861": EIA861, "census_counties": CENSUS},
        "license": "public domain (U.S. EIA; U.S. Census Bureau)",
        "rows": {k: int(len(v)) for k, v in tables.items()},
        "counties_in_boundaries": int(len(counties)),
        "plants_us_50_dc": int(len(us)),
        "plants_county_by_method": {str(k): int(v) for k, v in
                                    us["county_fips_method"].fillna("none").value_counts().items()},
        "plants_coords_disagree_with_eia_county_name": int((both & (us["county_fips"] != us["eia_county_fips"])).sum()),
        "territory_rows_matched": int(t["county_fips"].notna().sum()),
        "territory_rows_unmatched": int(t["county_fips"].isna().sum()),
        "written_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    (out / "_meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", metavar="DIR", help="write the tables here and skip the upload")
    a = ap.parse_args(argv)
    if a.local:
        out = pathlib.Path(a.local); out.mkdir(parents=True, exist_ok=True)
        print(json.dumps(build(out), indent=2))
        return
    from publish_world import bucket, client
    s3 = client()
    with tempfile.TemporaryDirectory() as d:
        out = pathlib.Path(d)
        meta = build(out)
        for f in sorted(out.glob("*.parquet")):
            s3.upload_file(str(f), bucket(), PREFIX + f.name,
                           ExtraArgs={"ContentType": "application/octet-stream",
                                      "CacheControl": "public, max-age=86400"})
            print(f"uploaded {PREFIX}{f.name} ({f.stat().st_size / 1e6:.1f} MB)", flush=True)
        s3.put_object(Bucket=bucket(), Key=PREFIX + "_meta.json", Body=json.dumps(meta, indent=2).encode(),
                      ContentType="application/json", CacheControl="public, max-age=300")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
