#!/usr/bin/env python3
"""FEMA flood zones clipped to each county, with each county's FIRM status, in R2 (D-057; LR-8).

    python3 tools/mirror_nfhl.py --state AL                  # one state's counties -> R2
    python3 tools/mirror_nfhl.py --fips 01131 22075          # just these
    python3 tools/mirror_nfhl.py --summarize                 # per-county rows -> county_status.parquet
    python3 tools/mirror_nfhl.py --local out/ --fips 01131   # no upload (testing)

D-013 kept flood out of the worlds because the pilot sandbox could not reach FEMA. The
National Flood Hazard Layer (hazards.fema.gov, ArcGIS REST, public domain) now answers
from GitHub runners and from the build sandbox. For each 2024 county (Census
cb_2024_us_county_500k), this queries the NFHL Flood Hazard Zones layer (28) with the
county's outline, pages 2,000 features at a time, and clips the polygons to the county:

    flood/nfhl/zones/<fips5>.parquet   one row per clipped hazard-zone polygon (1% and 0.2% annual
                                       chance, and zone D; not zone X unshaded): dfirm_id, version_id,
                                       fld_zone, zone_subty, sfha_tf, static_bfe, depth,
                                       study_typ, area_m2, geometry (WKB, EPSG:4326)
    flood/nfhl/status/<fips5>.json     the county's FIRM status (below)
    flood/nfhl/county_status.parquet   every county's status row (--summarize)
    flood/nfhl/_meta.json              source, counts, failures (written last by --summarize)

FIRM status comes from the coverage layers, measured as a share of the county's area:
effective NFHL coverage (NFHL Availability, layer 0), the effective dates and panel
types of the FIRM panels (layer 3), and preliminary and pending studies
(PrelimPending/Prelim_NFHL and Pending_NFHL, layer 0). status is "effective" when
digital effective maps cover at least 95% of the county, "partial" above 5%, and "none"
below: those counties have paper maps only or no map, and their zones file is empty.
Absence of a zone is not absence of risk; an engine must say "no digital FIRM" for them.

Zone classes: sfha (SFHA_TF = T: zones A, AE, AH, AO, AR, A99, V, VE; 1% annual chance),
x_shaded (zone X, 0.2% annual chance), d (zone D, undetermined). Zone X unshaded (minimal
hazard) is not fetched: it is most of NFHL's features and vertices, and inside the
effective coverage it is the complement of the others, so x_unshaded_km2 is that
difference (open water included). Geometry is generalized on FEMA's server to about 2 m. Areas are computed in EPSG:6933 (equal area). A county already in
R2 is skipped unless --force, so a run resumes.
"""
from __future__ import annotations

import argparse, concurrent.futures as cf, datetime, json, pathlib, sys, tempfile, time, urllib.parse, urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import pandas as pd  # noqa: E402

BASE = "https://hazards.fema.gov/arcgis/rest/services"
ZONES = f"{BASE}/public/NFHL/MapServer/28/query"
AVAIL = f"{BASE}/public/NFHL/MapServer/0/query"
PANELS = f"{BASE}/public/NFHL/MapServer/3/query"
PRELIM = f"{BASE}/PrelimPending/Prelim_NFHL/MapServer/0/query"
PENDING = f"{BASE}/PrelimPending/Pending_NFHL/MapServer/0/query"
ZONE_FIELDS = ("DFIRM_ID", "VERSION_ID", "FLD_ZONE", "ZONE_SUBTY", "SFHA_TF", "STATIC_BFE", "DEPTH", "STUDY_TYP")
UA = {"User-Agent": "RuralSim/1.0 (+https://www.ruralsim.io; county twin build)"}
SIMPLIFY_DEG = "0.00002"  # about 2 m; FIRM mapping is far coarser
# The hazard zones only. Zone X unshaded (minimal hazard) is most features and most vertices
# and is the complement of these inside the effective coverage, so it is not fetched.
HAZARD = "SFHA_TF = 'T' OR FLD_ZONE = 'D' OR (FLD_ZONE = 'X' AND ZONE_SUBTY LIKE '%0.2 PCT%')"
PREFIX = "flood/nfhl/"
EQUAL_AREA = "EPSG:6933"
FAIL_FAST = 3  # first counties all failing -> stop the state job
WORKERS = 3  # FEMA's server is shared: keep the load modest
FAR_FUTURE_MS = 253_000_000_000_000  # FEMA writes 9999-12-31 for "no date"


def post(url: str, form: dict, tries: int = 7) -> dict:
    data = urllib.parse.urlencode(form).encode()
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=UA | {"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read())
            if "error" in d:  # ArcGIS reports server trouble inside a 200
                raise RuntimeError(f"arcgis error {d['error'].get('code')}: {d['error'].get('message')}")
            return d
        except Exception as e:
            if attempt + 1 == tries or (isinstance(e, urllib.error.HTTPError) and e.code < 500 and e.code != 429):
                raise
            time.sleep(min(10 * 2 ** attempt, 300))


def query(url: str, geom_json: str, fields: str, with_geometry: bool, where: str = "1=1",
          batch: int = 200) -> list[dict]:
    """Every feature intersecting the polygon: object ids first, then the features in batches.

    NFHL features are whole-study polygons (one zone X polygon can carry a county's worth of
    vertices), so geometry is generalized on the server to SIMPLIFY_DEG (about 2 m) and
    requested a few features at a time."""
    ids = post(url, {"where": where, "geometry": geom_json, "geometryType": "esriGeometryPolygon", "inSR": "4326",
                     "spatialRel": "esriSpatialRelIntersects", "returnIdsOnly": "true", "f": "json"}).get("objectIds") or []
    out = []
    for i in range(0, len(ids), batch):
        form = {"objectIds": ",".join(map(str, sorted(ids)[i:i + batch])), "outFields": fields,
                "returnGeometry": "true" if with_geometry else "false", "outSR": "4326",
                "f": "geojson" if with_geometry else "json"}
        if with_geometry:
            form |= {"geometryPrecision": "6", "maxAllowableOffset": SIMPLIFY_DEG}
        out += post(url, form).get("features", [])
    if len(out) != len(ids):
        raise RuntimeError(f"{url.rsplit('/services/', 1)[1]}: {len(out)} of {len(ids)} features returned")
    return out


def esri_polygon(geom) -> str:
    """Shapely (multi)polygon -> esriGeometryPolygon JSON, simplified for the request only."""
    g = geom.buffer(0.002).simplify(0.001)
    rings = []
    for poly in getattr(g, "geoms", [g]):
        rings.append([list(c[:2]) for c in poly.exterior.coords])
        rings += [[list(c[:2]) for c in i.coords] for i in poly.interiors]
    return json.dumps({"rings": rings, "spatialReference": {"wkid": 4326}})


def county_shapes():
    import geopandas as gpd
    from eia_files import ensure
    from mirror_eia import CENSUS
    c = gpd.read_file(f"zip://{ensure(CENSUS)}").to_crs("EPSG:4326")
    master = pd.read_csv(REPO / "data" / "county_master.csv", dtype=str)
    c = c[c["GEOID"].isin(master.loc[master["geography_vintage"] == "2024", "fips5"])]  # 50 states and DC
    return c[["GEOID", "STUSPS", "NAME", "geometry"]].rename(columns={"GEOID": "fips5"})


def coverage(url: str, county, area: float, fields: str) -> tuple[float, list[dict]]:
    """Share of the county covered by this layer's study polygons, and the studies that count.

    The request outline is buffered by about 200 m so no edge sliver is missed. That also
    brings in neighbouring counties' studies along the line, as slivers (under 0.05% of the
    county in Wilcox AL); a study is kept only if it covers at least 0.5% of the county."""
    import geopandas as gpd
    from shapely.geometry import shape
    from shapely.ops import unary_union
    from shapely.validation import make_valid
    feats = [f for f in query(url, esri_polygon(county), fields, with_geometry=True) if f.get("geometry")]
    if not feats:
        return 0.0, []
    g = gpd.GeoSeries([make_valid(shape(f["geometry"])) for f in feats], crs="EPSG:4326").intersection(county)
    part = g.to_crs(EQUAL_AREA).area
    keep = [i for i in range(len(feats)) if part.iloc[i] >= 0.005 * area]
    if not keep:
        return 0.0, []
    cov = gpd.GeoSeries([unary_union([g.iloc[i] for i in keep])], crs="EPSG:4326").to_crs(EQUAL_AREA).area.iloc[0]
    return round(min(float(cov) / area, 1.0), 4), [feats[i]["properties"] for i in keep]


def one_county(row) -> tuple[pd.DataFrame, dict]:
    import geopandas as gpd
    from shapely.geometry import shape
    from shapely.validation import make_valid
    t0 = time.time()
    county = make_valid(row.geometry)
    area = float(gpd.GeoSeries([county], crs="EPSG:4326").to_crs(EQUAL_AREA).area.iloc[0])
    eff, avail = coverage(AVAIL, county, area, "STUDY_ID")
    pre, prelim = coverage(PRELIM, county, area, "DFIRM_ID,PRELM_ISSUE_DATE")
    pen, pending = coverage(PENDING, county, area, "DFIRM_ID,EFF_DATE")
    # Panels are rectangles that run past their own study's edge, so they are attributed by
    # study (DFIRM_ID of a study kept above), not by geometry.
    studies = {a["STUDY_ID"] for a in avail if a.get("STUDY_ID")}
    pattrs = [p["attributes"] for p in query(PANELS, esri_polygon(county), "DFIRM_ID,PANEL_TYP,EFF_DATE", False)
              if p["attributes"].get("DFIRM_ID") in studies]
    eff_dates = [p["EFF_DATE"] for p in pattrs if p.get("EFF_DATE") and p["EFF_DATE"] < FAR_FUTURE_MS]
    ms = lambda v: datetime.datetime.fromtimestamp(v / 1000, datetime.timezone.utc).date().isoformat()  # noqa: E731
    zones = []
    if eff > 0:
        feats = query(ZONES, esri_polygon(county), ",".join(ZONE_FIELDS), with_geometry=True, where=HAZARD, batch=20)
        for f in feats:
            if not f.get("geometry"):
                continue
            g = make_valid(shape(f["geometry"])).intersection(county)
            if g.is_empty:
                continue
            p = f["properties"]
            zones.append({k.lower(): p.get(k) for k in ZONE_FIELDS} | {"geometry": g})
    z = gpd.GeoDataFrame(zones, geometry="geometry", crs="EPSG:4326") if zones else \
        gpd.GeoDataFrame({k.lower(): [] for k in ZONE_FIELDS}, geometry=[], crs="EPSG:4326")
    z = z[z.geometry.geom_type.isin(["Polygon", "MultiPolygon", "GeometryCollection"])]
    z["geometry"] = z.geometry.map(lambda g: g if g.geom_type != "GeometryCollection" else
                                   __import__("shapely").ops.unary_union([p for p in g.geoms if p.area > 0]))
    z = z[~z.geometry.is_empty & z.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    z["area_m2"] = z.to_crs(EQUAL_AREA).area.round(1)
    zone = z["fld_zone"].astype("string").fillna("")
    sub = z["zone_subty"].astype("string").fillna("").str.upper()
    km2 = lambda m: round(float(z.loc[m, "area_m2"].sum()) / 1e6, 3)  # noqa: E731
    sfha = z["sfha_tf"] == "T"
    shaded = (zone == "X") & sub.str.contains("0.2 PCT")
    status = {"fips5": row.fips5, "state": row.STUSPS, "county": row.NAME,
              "county_km2": round(area / 1e6, 3),
              "status": "effective" if eff >= 0.95 else "partial" if eff > 0.05 else "none",
              "effective_coverage": eff, "dfirm_ids": sorted({a["STUDY_ID"] for a in avail if a.get("STUDY_ID")}),
              "panels": len(pattrs),
              "panels_printed": sum(1 for p in pattrs if "Not Printed" not in (p.get("PANEL_TYP") or "")),
              "eff_date_min": ms(min(eff_dates)) if eff_dates else None,
              "eff_date_max": ms(max(eff_dates)) if eff_dates else None,
              "prelim_coverage": pre, "prelim_issue_date_max":
                  ms(max(v)) if (v := [a["PRELM_ISSUE_DATE"] for a in prelim if a.get("PRELM_ISSUE_DATE")]) else None,
              "pending_coverage": pen, "pending_eff_date_min":
                  ms(min(v)) if (v := [a["EFF_DATE"] for a in pending if a.get("EFF_DATE")]) else None,
              "zones": int(len(z)), "sfha_km2": km2(sfha), "x_shaded_km2": km2(shaded),
              "d_km2": km2(zone == "D"),
              "x_unshaded_km2": round(max(eff * area / 1e6 - km2(sfha | shaded | (zone == "D")), 0), 3),
              "sfha_share": round(km2(sfha) * 1e6 / area, 4),
              "seconds": round(time.time() - t0, 1)}
    return z, status


def zones_parquet(z) -> bytes:
    import duckdb
    df = pd.DataFrame(z.drop(columns="geometry"))
    df["geometry"] = z.geometry.to_wkb().values
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "z.parquet"
        con = duckdb.connect(); con.register("df", df)
        con.sql(f"COPY (SELECT * FROM df) TO '{p}' (FORMAT parquet, COMPRESSION zstd)")
        return p.read_bytes()


def summarize(store) -> dict:
    import duckdb
    rows = [json.loads(b) for b in store.read_all("status/")]
    df = pd.DataFrame(rows).sort_values("fips5")
    df["dfirm_ids"] = df["dfirm_ids"].map(lambda v: ",".join(v))
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "s.parquet"
        con = duckdb.connect(); con.register("df", df)
        con.sql(f"COPY (SELECT * FROM df) TO '{p}' (FORMAT parquet, COMPRESSION zstd)")
        store.put("county_status.parquet", p.read_bytes())
    master = pd.read_csv(REPO / "data" / "county_master.csv", dtype=str)
    now = set(master.loc[master["geography_vintage"] == "2024", "fips5"])
    meta = {"source": "FEMA National Flood Hazard Layer (hazards.fema.gov ArcGIS REST: public/NFHL layers 0, 3, 28; "
                      "PrelimPending/Prelim_NFHL and Pending_NFHL layer 0)",
            "license": "public domain (FEMA)", "clip": "Census cb_2024_us_county_500k", "area_crs": EQUAL_AREA,
            "counties": int(len(df)), "counties_missing": sorted(now - set(df["fips5"])),
            "by_status": df["status"].value_counts().to_dict(), "zones": int(df["zones"].sum()),
            "with_prelim": int((df["prelim_coverage"] > 0).sum()), "with_pending": int((df["pending_coverage"] > 0).sum()),
            "written_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    store.put("_meta.json", json.dumps(meta, indent=2).encode())
    return meta


class Store:
    def __init__(self, local: str | None):
        self.local = pathlib.Path(local) if local else None
        if not self.local:
            from publish_world import bucket, client
            self.s3, self.b = client(), bucket()

    def put(self, key: str, body: bytes):
        if self.local:
            (self.local / key).parent.mkdir(parents=True, exist_ok=True)
            (self.local / key).write_bytes(body)
        else:
            self.s3.put_object(Bucket=self.b, Key=PREFIX + key, Body=body, CacheControl="public, max-age=86400",
                               ContentType="application/json" if key.endswith(".json") else "application/octet-stream")

    def keys(self, sub: str) -> list[str]:
        if self.local:
            return [str(p.relative_to(self.local)) for p in (self.local / sub).glob("*")] if (self.local / sub).exists() else []
        out = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.b, Prefix=PREFIX + sub):
            out += [o["Key"].removeprefix(PREFIX) for o in page.get("Contents", [])]
        return out

    def read_all(self, sub: str) -> list[bytes]:
        ks = self.keys(sub)
        if self.local:
            return [(self.local / k).read_bytes() for k in ks]
        with cf.ThreadPoolExecutor(16) as ex:
            return list(ex.map(lambda k: self.s3.get_object(Bucket=self.b, Key=PREFIX + k)["Body"].read(), ks))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", nargs="*", default=[])
    ap.add_argument("--fips", nargs="*", default=[])
    ap.add_argument("--local", metavar="DIR")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--summarize", action="store_true")
    a = ap.parse_args(argv)
    store = Store(a.local)
    if a.summarize:
        print(json.dumps(summarize(store), indent=2)); return
    c = county_shapes()
    if a.state:
        c = c[c["STUSPS"].isin([s.upper() for s in a.state])]
    if a.fips:
        c = c[c["fips5"].isin(a.fips)]
    have = set() if a.force else {k.rsplit("/", 1)[1][:5] for k in store.keys("status/")}
    todo = c[~c["fips5"].isin(have)]
    print(f"{len(c)} counties, {len(c) - len(todo)} already in R2, {len(todo)} to fetch", flush=True)

    # FEMA's server sometimes resets every connection from one runner for hours (run 1: all of
    # Arkansas and Kansas, and Hawaii, while 48 other states ran clean). Seven retries per request
    # then turn a state into a six-hour timeout. Once the first FAIL_FAST counties have all failed
    # and none succeeded, the rest are skipped so the job ends quickly and "Re-run failed jobs"
    # gets a fresh runner.
    import threading
    stop, tally, lock = threading.Event(), {"ok": 0, "bad": 0}, threading.Lock()

    def run(row):
        if stop.is_set():
            return row.fips5, None, "skipped: this runner looks blocked by FEMA"
        try:
            z, s = one_county(row)
            store.put(f"zones/{row.fips5}.parquet", zones_parquet(z))
            store.put(f"status/{row.fips5}.json", json.dumps(s).encode())  # last: marks the county done
            with lock:
                tally["ok"] += 1
            return row.fips5, s, None
        except Exception as e:
            with lock:
                tally["bad"] += 1
                if tally["ok"] == 0 and tally["bad"] >= FAIL_FAST:
                    stop.set()
            return row.fips5, None, str(e)[:200]

    failed, t0 = [], time.time()
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for i, (f, s, err) in enumerate(ex.map(run, todo.itertuples()), 1):
            if err:
                failed.append(f); print(f"  {f}: FAILED {err}", flush=True)
            else:
                print(f"  {f} {s['state']} {s['status']} eff={s['effective_coverage']} zones={s['zones']} "
                      f"sfha={s['sfha_share']:.1%} {s['seconds']}s", flush=True)
            if i % 25 == 0:
                print(f"  {i}/{len(todo)} in {time.time() - t0:.0f} s", flush=True)
    if failed:
        raise SystemExit(f"{len(failed)} counties failed: {' '.join(failed)}; rerun to resume")


if __name__ == "__main__":
    main()
