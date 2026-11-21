#!/usr/bin/env python3
"""Offline tests for the canary-run fixes (D-036).

    python3 tests/test_canary_fixes.py

- New Jersey served-town names ("ALLOWAY TWP-.1701") normalize to the Census name.
- An OSM extract comes from the R2 mirror when it has one, and from Geofabrik when the
  mirror lacks it; a Geofabrik refusal is retried before the county fails.
No network: downloads are replaced with local stand-ins.
"""
import hashlib, pathlib, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import fetch_osm as fo  # noqa: E402
import place_water_systems as pw  # noqa: E402


def test_nj_town_names():
    pairs = {"ALLOWAY TWP-.1701": "Alloway township", "PENNS GROVE BORO-.1708": "Penns Grove borough",
             "SALEM CITY-.1712": "Salem city", "Carneys Point Township": "Carneys Point township",
             "Pittsgrove twp": "Pittsgrove township", "Lebanon CCD": "Lebanon",
             "PITTSGROVE TWP.-1710": "Pittsgrove township",
             "UPPER PITTSGROVE TWP.-1714": "Upper Pittsgrove township",
             "LOWER ALLOWAYS CR.-1704": "Lower Alloways Creek township",
             "CARNEY'S POINT TWP.-1713": "Carneys Point township",
             "Mount Pleasant": "Mt. Pleasant city", "Saint Marys": "St. Marys city"}
    for sdwis, census in pairs.items():
        assert pw.norm(sdwis) == pw.norm(census), (sdwis, pw.norm(sdwis), pw.norm(census))
    # a name that merely ends in a number is not a municipal code
    assert pw.norm("Route 9") == "ROUTE 9"


def _fake_env(tmp, mirror_has, geofabrik_fail_times):
    data = b"pretend pbf"
    md5 = hashlib.md5(data).hexdigest()
    calls = {"mirror": [], "geofabrik": 0}

    def mirror_get(name, dest):
        calls["mirror"].append(name)
        if not mirror_has:
            return False
        dest.write_bytes(data if not name.endswith(".md5") else f"{md5}  x\n".encode())
        return True

    def download(url, dest, timeout=3600):
        if url.endswith(".md5"):
            dest.write_text(f"{md5}  x\n")
            return
        calls["geofabrik"] += 1
        if calls["geofabrik"] <= geofabrik_fail_times:
            raise OSError("[Errno 101] Network is unreachable")
        dest.write_bytes(data)

    fo.CACHE = pathlib.Path(tmp) / "not-yet-created" / "osm"  # run 43928880530
    fo._mirror_get, fo._download = mirror_get, download
    fo.OSM_MIRROR = "https://example.invalid/osm"
    fo._replication_ts = lambda p: None
    fo.time.sleep = lambda s: None
    return calls


PROPS = {"id": "delaware", "urls": {"pbf": "https://download.geofabrik.de/north-america/us/delaware-latest.osm.pbf"}}


_SAVED = {k: getattr(fo, k) for k in ("CACHE", "_mirror_get", "_download", "OSM_MIRROR", "_replication_ts")}
_SLEEP = fo.time.sleep


def test_mirror_then_fallback():
    try:
        _mirror_then_fallback()
    finally:  # leave fetch_osm as found for the other tests in this process
        for k, v in _SAVED.items():
            setattr(fo, k, v)
        fo.time.sleep = _SLEEP


def _mirror_then_fallback():
    with tempfile.TemporaryDirectory() as d:
        calls = _fake_env(d, mirror_has=True, geofabrik_fail_times=0)
        prov = fo.ensure_extract(PROPS, max_age_days=7)
        assert calls["geofabrik"] == 0 and prov["fetched_from"].startswith("r2:"), (calls, prov)
    with tempfile.TemporaryDirectory() as d:
        calls = _fake_env(d, mirror_has=False, geofabrik_fail_times=3)
        prov = fo.ensure_extract(PROPS, max_age_days=7)
        assert calls["geofabrik"] == 4 and "fetched_from" not in prov, (calls, prov)
    with tempfile.TemporaryDirectory() as d:
        _fake_env(d, mirror_has=False, geofabrik_fail_times=99)
        try:
            fo.ensure_extract(PROPS, max_age_days=7)
        except RuntimeError as e:
            assert "could not download" in str(e)
        else:
            raise AssertionError("an unreachable Geofabrik must fail the step")


if __name__ == "__main__":
    test_nj_town_names()
    test_mirror_then_fallback()
    print("ok")


def test_cropland_pc_retry_rides_out_outage(monkeypatch):
    """Texas run #12: PC STAC returned 'Service is unavailable' for ~2 min; pc_retry must retry."""
    import ast, time as _t
    src = (REPO / "tools" / "fetch_cropland.py").read_text()
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "pc_retry")
    ns = {"time": _t}
    exec(compile(ast.Module([fn], []), "pc_retry", "exec"), ns)
    monkeypatch.setattr(_t, "sleep", lambda s: None)
    calls = []
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError('{"error":"Service is unavailable."}')
        return "ok"
    assert ns["pc_retry"](flaky, "search") == "ok" and len(calls) == 3


def test_ws_lookup_parallel_keeps_cache_and_skips_failures(monkeypatch, tmp_path):
    """Harris TX (run #12): ~2,500 WATER_SYSTEM lookups now run 8 at a time; failures are skipped."""
    import io, json as _j, urllib.request as ur
    def fake(req, timeout=0):
        pid = req.full_url.split("/PWSID/")[1].split("/")[0]
        if pid == "BAD":
            raise OSError("HTTP Error 500")
        return io.BytesIO(_j.dumps([{"city_name": f"TOWN{pid}", "zip_code": "77001"}]).encode())
    monkeypatch.setattr(ur, "urlopen", fake)
    cp = tmp_path / "ws.json"
    cp.write_text(_j.dumps({"OLD": {"city_name": "KEPT"}}))
    out = pw.ws_lookup([f"P{i}" for i in range(50)] + ["BAD", "OLD"], cp)
    assert out["OLD"]["city_name"] == "KEPT" and "BAD" not in out
    assert out["P7"]["city_name"] == "TOWNP7" and len(out) == 51


def test_epa_get_retries_429_then_succeeds(monkeypatch):
    """Run #13 (Harris TX): unretried HTTP 429 dropped 1,841 violation lookups."""
    import io, urllib.error, urllib.request as ur
    calls = []
    def fake(req, timeout=0):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "0"}, None)
        return io.BytesIO(b"[]")
    monkeypatch.setattr(ur, "urlopen", fake)
    monkeypatch.setattr(pw.time, "sleep", lambda s: None)
    assert pw.epa_get("https://data.epa.gov/efservice/X") == b"[]" and len(calls) == 3


def test_ws_lookup_fails_step_when_many_lookups_fail(monkeypatch, tmp_path):
    import urllib.request as ur
    def fake(req, timeout=0):
        raise OSError("down")
    monkeypatch.setattr(ur, "urlopen", fake)
    try:
        pw.ws_lookup([f"P{i}" for i in range(10)], tmp_path / "ws.json")
    except RuntimeError as e:
        assert "10 of 10" in str(e)
    else:
        raise AssertionError("expected the step to fail")


def test_sab_point_inside_county_part_only():
    """D-041: the marker sits inside the part of the service area within the county."""
    from shapely.geometry import box
    county = box(0, 0, 1, 1)
    inside = {"geometry": {"type": "Polygon", "coordinates": [[[0.5, 0.5], [2, 0.5], [2, 0.9], [0.5, 0.9], [0.5, 0.5]]]}}
    outside = {"geometry": {"type": "Polygon", "coordinates": [[[3, 3], [4, 3], [4, 4], [3, 4], [3, 3]]]}}
    x, y = pw.sab_point(inside, county)
    assert 0.5 <= x <= 1 and 0.5 <= y <= 0.9
    assert pw.sab_point(outside, county) is None


def test_sab_lookup_queries_community_then_noncommunity(monkeypatch, tmp_path):
    import io, json as _j, urllib.parse, urllib.request as ur
    seen = []
    def fake(req, timeout=0):
        q = urllib.parse.parse_qs(req.data.decode())
        ids = [x.strip("'") for x in q["where"][0][len("PWSID IN ("):-1].split(",")]
        layer = "community" if "Water_System_Boundaries" in req.full_url else "non-community"
        seen.append((layer, ids))
        hit = {"community": "TX1", "non-community": "TX2"}[layer]
        feats = [{"type": "Feature", "properties": {"PWSID": hit},
                  "geometry": {"type": "Point", "coordinates": [0, 0]}}] if hit in ids else []
        return io.BytesIO(_j.dumps({"type": "FeatureCollection", "features": feats}).encode())
    monkeypatch.setattr(ur, "urlopen", fake)
    out = pw.sab_lookup(["TX1", "TX2", "TX3"], tmp_path / "sab.geojson")
    assert set(out) == {"TX1", "TX2"}
    assert seen[0] == ("community", ["TX1", "TX2", "TX3"]) and seen[1] == ("non-community", ["TX2", "TX3"])
    assert out["TX2"]["properties"]["ruralsim_layer"] == "non-community"
    # cached: no new requests
    n = len(seen); pw.sab_lookup(["TX1", "TX2", "TX3"], tmp_path / "sab.geojson"); assert len(seen) == n


def test_plan_accepts_state_lists():
    """Runs 44087225127 / 44198783636: --state "AL, GA, MS" selected nothing."""
    import contextlib, io, json as _j, plan_build
    def plan(s):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            plan_build.main(["--state", s])
        return _j.loads(out.getvalue().strip().splitlines()[-1])
    assert len(plan("AL, MS")) == 67 + 82 and len(plan("al")) == 67
    for bad in ("AL, GA, MS", "XX"):  # 308 counties > 256; unknown code
        try:
            plan(bad)
        except SystemExit:
            pass
        else:
            raise AssertionError(bad)


def test_eia_download_retries_and_never_keeps_a_partial(monkeypatch, tmp_path):
    """Run #22: Avery NC failed on one DNS error fetching the EIA-860 zip (D-044)."""
    import io, urllib.error, urllib.request as ur, eia_files
    monkeypatch.setattr(eia_files, "CACHE", tmp_path)
    monkeypatch.setattr(eia_files.time, "sleep", lambda s: None)
    calls = []
    class Resp(io.BytesIO):
        headers = {"Content-Length": "5"}
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def fake(req, timeout=0):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.URLError("[Errno -3] Temporary failure in name resolution")
        if len(calls) == 2:
            return Resp(b"abc")  # cut off: 3 of 5 bytes
        return Resp(b"abcde")
    monkeypatch.setattr(ur, "urlopen", fake)
    p = eia_files.ensure("https://www.eia.gov/x/f.zip")
    assert p.read_bytes() == b"abcde" and len(calls) == 3
    assert not (tmp_path / "f.zip.part").exists()


def test_nhd_state_names_match_usgs_staged_products():
    """D-045: Geofabrik region ids map to the names in NHD_H_<name>_State_GPKG.zip."""
    import nhd_mirror as nm
    assert nm.nhd_name("us/north-carolina") == "North_Carolina"
    assert nm.nhd_name("us/district-of-columbia") == "District_of_Columbia"
    assert nm.nhd_name("us/us-virgin-islands") == "United_States_Virgin_Islands"
    assert nm.key("us/new-york", "flowline") == "nhd/new-york_flowline.parquet"


def test_nhd_read_dedupes_across_states_and_clips_to_envelope(tmp_path, monkeypatch):
    """Neighbouring states' GeoPackages share border watersheds; keep each feature once."""
    import duckdb, nhd_mirror as nm
    con = duckdb.connect(); con.sql("INSTALL spatial; LOAD spatial;")
    for st in ("a", "b"):
        con.sql(f"""COPY (SELECT * FROM (VALUES
            ('1', 'Shared Creek', 460, 46000, 'r1', 1.0, 'LINESTRING(0.1 0.1, 0.2 0.2)'),
            ('{st}2', NULL, 460, 46000, 'r2', 1.0, 'LINESTRING(5 5, 6 6)')) t(permanent_identifier,
            gnis_name, ftype, fcode, reachcode, lengthkm, w)
          ) TO '{tmp_path}/raw_{st}.parquet' (FORMAT parquet)""")
        con.sql(f"""COPY (SELECT permanent_identifier, gnis_name, ftype, fcode, reachcode, lengthkm,
              ST_XMin(ST_GeomFromText(w)) xmin, ST_YMin(ST_GeomFromText(w)) ymin,
              ST_XMax(ST_GeomFromText(w)) xmax, ST_YMax(ST_GeomFromText(w)) ymax,
              ST_AsWKB(ST_GeomFromText(w)) geom FROM '{tmp_path}/raw_{st}.parquet')
          TO '{tmp_path}/{st}_flowline.parquet' (FORMAT parquet)""")
    monkeypatch.setattr(nm, "DATA_BASE", str(tmp_path))
    monkeypatch.setattr(nm, "PREFIX", "")
    monkeypatch.setattr(nm.urllib.request, "Request", lambda *a, **k: None)  # HEAD check
    monkeypatch.setattr(nm.urllib.request, "urlopen", lambda *a, **k: None)
    fc = nm.read("flowline", (0, 0, 1, 1), ["us/a", "us/b"])
    assert [f["properties"]["gnis_name"] for f in fc["features"]] == ["Shared Creek"]


def test_osm_mirror_survives_geofabrik_down(monkeypatch, tmp_path):
    """Runs #27/#28: Geofabrik reset every connection and the first missing state failed the
    whole plan. Now a stale R2 copy is kept and a state that cannot be fetched is skipped (D-046)."""
    import datetime, fetch_osm, mirror_osm as mo
    old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
    class S3:
        uploads = []
        def head_object(self, Bucket, Key):
            if "kentucky" in Key:
                return {"LastModified": old}  # stale copy exists
            raise Exception("404")
        def upload_file(self, *a, **k): self.uploads.append(a[2])
        def put_object(self, **k): self.uploads.append(k["Key"])
    s3 = S3()
    monkeypatch.setattr(mo, "client", lambda: s3)
    monkeypatch.setattr(mo, "bucket", lambda: "b")
    monkeypatch.setattr(mo, "geofabrik_up", lambda timeout=30: False)
    monkeypatch.setattr(fetch_osm, "CACHE", tmp_path)
    def fake_cut(r, dest, regional):
        if "west-virginia" in r["id"]:
            dest.write_bytes(b"pbf" * 10)
            return "https://download.openstreetmap.fr/x"
        raise RuntimeError("no region")
    monkeypatch.setattr(mo, "_from_osmfr", fake_cut)
    regions = [{"id": f"us/{s}", "urls": {"pbf": f"https://download.geofabrik.de/north-america/us/{s}-latest.osm.pbf"}}
               for s in ("kentucky", "west-virginia", "alaska")]
    done = mo.mirror(regions)
    assert done == ["kentucky-latest.osm.pbf", "west-virginia-latest.osm.pbf"]
    assert s3.uploads[-1] == "osm/west-virginia-latest.osm.pbf.md5"  # md5 written last


def test_rebrand_replaces_only_the_founder_line():
    import io
    import rebrand_viewers as rv
    from build_site import brand_viewer_html
    # the new line is exactly what new publishes carry
    assert rv.NEW in brand_viewer_html("<html><head></head><body></body></html>")
    old = ('<div id="disclose" style="x">RuralSim is a free, open-source project by Grid &amp; Grain\'s founder. '
           'Simulated, screening-grade results with assumed parameters. Decision support, not a finding.</div>')
    html = f"<html><body>\n{old}\n<script>var a=1;</script></body></html>"
    out, status = rv.rebrand(html)
    assert status == "updated" and rv.NEW in out and "Grain's founder" not in out
    assert out.replace(rv.NEW, "X") == html.replace(rv.OLD[0], "X")  # nothing else changed
    assert rv.rebrand(out) == (out, "current")
    assert rv.rebrand("<html></html>")[1] == "missing"

    class S3:
        def __init__(self): self.puts = []
        def get_object(self, Bucket, Key): return {"Body": io.BytesIO(html.encode())}
        def put_object(self, **kw): self.puts.append(kw)
    e = {"fips5": "20019", "dir": "20019_chautauqua_ks", "viewer": "worlds/20019_chautauqua_ks/current/viewer/index.html"}
    s3 = S3()
    assert rv.one(s3, "b", e, dry=True) == ("20019", "updated") and s3.puts == []
    assert rv.one(s3, "b", e, dry=False) == ("20019", "updated")
    p = s3.puts[0]
    assert p["Key"] == e["viewer"] and p["ContentType"].startswith("text/html") and rv.NEW in p["Body"].decode()


def test_openmeteo_gives_up_on_a_quota_length_retry_after(monkeypatch):
    import email.message, urllib.error
    import fetch_climate as fc
    slept = []
    monkeypatch.setattr(fc.time, "sleep", lambda s: slept.append(s))

    def refuse(wait):
        def f(url, timeout=300):
            h = email.message.Message(); h["Retry-After"] = str(wait)
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", h, None)
        return f
    monkeypatch.setattr(fc, "_fetch", refuse(66812))  # run #38, Clayton IA
    try:
        fc.openmeteo_daily(42.8, -91.3, attempts=3)
        assert False, "should give up"
    except RuntimeError as e:
        assert "daily quota" in str(e)
    assert slept == []
    monkeypatch.setattr(fc, "_fetch", refuse(5))  # a short wait is still honoured
    try:
        fc.openmeteo_daily(42.8, -91.3, attempts=3)
    except urllib.error.HTTPError:
        pass
    assert slept == [5, 5]


def test_eia_county_names_match_census_names():
    import pandas as pd
    import mirror_eia as me
    master = pd.DataFrame({"fips5": ["17163", "01115", "29186", "22031", "51159", "51760", "24033"],
                           "state_abbr": ["IL", "AL", "MO", "LA", "VA", "VA", "MD"],
                           "county_name": ["St. Clair County", "St. Clair County", "Ste. Genevieve County",
                                           "De Soto Parish", "Richmond County", "Richmond city",
                                           "Prince George's County"]})
    lk = me.county_lookup(master)
    # EIA-861 spellings seen in Service_Territory_2024
    assert me.match_name(lk, "IL", "St Clair") == "17163"
    assert me.match_name(lk, "AL", "St Clair") == "01115"
    assert me.match_name(lk, "MO", "Ste Genevieve") == "29186"
    assert me.match_name(lk, "LA", "DeSoto") == "22031"
    assert me.match_name(lk, "VA", "Richmond") == "51159"        # the county
    assert me.match_name(lk, "VA", "Richmond City") == "51760"   # the independent city
    assert me.match_name(lk, "MD", "Prince Georges") == "24033"
    assert me.match_name(lk, "IL", "Clay") is None               # no substring matches (LR-9)


def test_nbi_comes_from_the_shared_cache_with_retries(monkeypatch, tmp_path):
    """Runs #41/#42: 7 counties lost to four minutes of FHWA 503s / refused connections (D-052)."""
    import io, pathlib, urllib.error, urllib.request as ur, eia_files
    monkeypatch.setattr(eia_files, "CACHE", tmp_path / "eia")
    monkeypatch.setattr(eia_files.time, "sleep", lambda s: None)
    calls = []
    class Resp(io.BytesIO):
        headers = {"Content-Length": "3"}
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def fake(req, timeout=0):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 503, "Service Unavailable", {}, None)
        if len(calls) == 2:
            raise urllib.error.URLError("[Errno 111] Connection refused")
        return Resp(b"nbi")
    monkeypatch.setattr(ur, "urlopen", fake)
    p = eia_files.ensure(eia_files.NBI, sub="nbi")
    assert p == tmp_path / "nbi" / "2024del.zip" and p.read_bytes() == b"nbi" and len(calls) == 3
    src = (pathlib.Path(eia_files.__file__).parent / "fetch_bridges.py").read_text()
    assert "eia_files.ensure(URL, sub=\"nbi\")" in src and "urlopen" not in src


def test_acs_quintiles_parse_counties_sentinels_and_topcodes(tmp_path):
    import mirror_acs as ma
    f = tmp_path / "b19080.dat"
    f.write_text("GEO_ID|B19080_E001|B19080_M001|B19080_E002|B19080_M002|B19080_E003|B19080_M003|"
                 "B19080_E004|B19080_M004|B19080_E005|B19080_M005\n"
                 "0100000US|1|1|2|2|3|3|4|4|5|5\n"
                 "0500000US01131|13024|1942|32585|9398|53194|4797|93254|11403|166719|37417\n"
                 "0500000US51013|62142|2449|113625|2564|172424|3927|250001|-333333333|250001|-333333333\n"
                 "0500000US48301|-666666666|-222222222|1|1|1|1|1|1|1|1\n")
    df = ma.parse(f, "b19080").set_index("fips5")
    assert list(df.index) == ["01131", "51013", "48301"]       # the nation row is dropped
    assert df.loc["01131", "upper_q1"] == 13024 and df.loc["01131", "upper_q1_moe"] == 1942
    assert df.loc["51013", "upper_q4_topcoded"] and df.loc["51013", "upper_q4"] == 250001
    assert df.loc["51013", "upper_q4_moe"] != df.loc["51013", "upper_q4_moe"]   # sentinel -> NaN
    assert df.loc["48301", "upper_q1"] != df.loc["48301", "upper_q1"]


def test_power_daily_parse_and_wetbulb_summary():
    import mirror_power as mp
    days = {f"2020{m:02d}{d:02d}": v for m, d, v in ((1, 1, 2.0), (7, 1, 25.0), (7, 2, 23.0), (7, 3, -999.0))}
    payload = {"properties": {"parameter": {"T2M": days, "T2MDEW": days, "T2MWET": days}}}
    df = mp.to_frame(payload)
    assert len(df) == 4 and df["t2mwet_c"].isna().sum() == 1       # -999 fill -> NaN
    s = mp.summarize("01131", df)
    assert s["days"] == 3 and s["tw_dailymean_max_c"] == 25.0
    assert s["days_per_year_tw_ge_24c"] == 1.0 and s["tw_mean_m07_c"] == 24.0


def test_sdwis_table_never_keeps_contact_fields():
    import mirror_sdwis as ms
    banned = {"admin_name", "org_name", "address_line1", "address_line2", "phone_number",
              "alt_phone_number", "phone_ext_number", "fax_number", "email_addr"}
    assert not banned & set(ms.KEEP)
    assert {"population_served_count", "gw_sw_code", "primary_source_code"} <= set(ms.KEEP)
