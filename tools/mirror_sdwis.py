#!/usr/bin/env python3
"""National EPA SDWIS water-system table in R2, one consistent column set (D-054; LR-5).

    python3 tools/mirror_sdwis.py                 # build and upload to R2
    python3 tools/mirror_sdwis.py --local out/    # build into out/, no upload (testing)

The cooling-water module needs each system's size and source, and the per-county
sdwis_systems_<fips>.csv files lack them: GEOGRAPHIC_AREA holds no population or source,
and the WATER_SYSTEM lookup keeps only city, ZIP and name. Their columns also differ by
county (Pottawattamie publishes 44, mostly empty, and Wilcox 13). This writes one national
table from EPA Envirofacts WATER_SYSTEM, every primacy agency, paged 5,000 rows at a time:

    water/sdwis/water_systems.parquet   pwsid, pws_name, primacy_agency_code, epa_region,
                                        state_code, pws_activity_code, pws_type_code,
                                        owner_type_code, population_served_count,
                                        service_connections_count, gw_sw_code,
                                        primary_source_code, is_wholesaler_ind,
                                        is_school_or_daycare_ind, pws_deactivation_date,
                                        season_begin_date, season_end_date, city_name, zip_code
    water/sdwis/_meta.json              source, rows per agency, failures (written last)

Join on pwsid. Contact fields (administrator, organisation, address, phone, fax, email)
are never requested into the table: KEEP is an allow-list, as in place_water_systems.py.
Public domain (U.S. EPA).
"""
from __future__ import annotations

import argparse, datetime, json, pathlib, sys, tempfile, time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import pandas as pd  # noqa: E402

from place_water_systems import epa_get  # noqa: E402  (retries 429/5xx, D-030)

BASE = "https://data.epa.gov/efservice/WATER_SYSTEM"
PAGE = 5000
KEEP = ("pwsid", "pws_name", "primacy_agency_code", "epa_region", "state_code", "pws_activity_code",
        "pws_type_code", "owner_type_code", "population_served_count", "service_connections_count",
        "gw_sw_code", "primary_source_code", "is_wholesaler_ind", "is_school_or_daycare_ind",
        "pws_deactivation_date", "season_begin_date", "season_end_date", "city_name", "zip_code")
# 50 states, DC, territories, and the ten EPA regions (tribal primacy, codes 01-10)
AGENCIES = ("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH "
            "NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR VI GU AS MP NN "
            "01 02 03 04 05 06 07 08 09 10").split()


def agency_rows(code: str) -> list[dict]:
    n = int(json.loads(epa_get(f"{BASE}/PRIMACY_AGENCY_CODE/{code}/COUNT/JSON", timeout=300))[0]["TOTALQUERYRESULTS"])
    rows = []
    for a in range(0, n, PAGE):
        page = json.loads(epa_get(f"{BASE}/PRIMACY_AGENCY_CODE/{code}/ROWS/{a}:{min(a + PAGE, n) - 1}/JSON",
                                  timeout=300))
        rows.extend({k: r.get(k) for k in KEEP} for r in page)
    if len(rows) != n:
        raise RuntimeError(f"{code}: {len(rows)} of {n} rows")
    return rows


def build(out: pathlib.Path) -> dict:
    allrows, counts, failed = [], {}, {}
    t0 = time.time()
    for code in AGENCIES:
        try:
            r = agency_rows(code)
            allrows.extend(r); counts[code] = len(r)
        except Exception as e:
            failed[code] = str(e)[:160]
            print(f"  {code}: FAILED {failed[code]}", flush=True)
    df = pd.DataFrame(allrows, columns=list(KEEP)).drop_duplicates("pwsid")
    for c in ("population_served_count", "service_connections_count"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].map(lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
    import duckdb
    con = duckdb.connect(); con.register("df", df)
    con.sql(f"COPY (SELECT * FROM df ORDER BY pwsid) TO '{out / 'water_systems.parquet'}' "
            "(FORMAT parquet, COMPRESSION zstd)")
    active = df[df["pws_activity_code"] == "A"]
    meta = {"source": "EPA Envirofacts SDWIS WATER_SYSTEM (data.epa.gov/efservice)",
            "license": "public domain (U.S. EPA)", "columns": list(KEEP),
            "contact_fields": "excluded (allow-list)", "rows": int(len(df)), "active": int(len(active)),
            "active_with_population": int(active["population_served_count"].notna().sum()),
            "rows_by_agency": counts, "failed_agencies": failed,
            "seconds": round(time.time() - t0),
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
        s3, prefix = client(), "water/sdwis/"
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d)
            meta = build(out)
            if meta["failed_agencies"]:
                raise SystemExit(f"not uploading a partial table: {sorted(meta['failed_agencies'])} failed")
            s3.upload_file(str(out / "water_systems.parquet"), bucket(), prefix + "water_systems.parquet",
                           ExtraArgs={"ContentType": "application/octet-stream",
                                      "CacheControl": "public, max-age=86400"})
            s3.put_object(Bucket=bucket(), Key=prefix + "_meta.json", Body=json.dumps(meta, indent=2).encode(),
                          ContentType="application/json", CacheControl="public, max-age=300")
    print(json.dumps({k: v for k, v in meta.items() if k != "rows_by_agency"}, indent=2))


if __name__ == "__main__":
    main()
