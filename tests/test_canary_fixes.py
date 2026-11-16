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
