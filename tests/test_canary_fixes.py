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
