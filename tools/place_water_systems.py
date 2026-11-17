#!/usr/bin/env python3
"""Give each active EPA SDWIS water system in a county a map position (D-030).

    python3 tools/place_water_systems.py 31173

SDWIS carries no coordinates, only the town(s) a system serves. The stage builder used
to place a system only when that town matched a node in the county's OSM `places` layer,
and validation compared placed systems against *all* SDWIS rows — inactive systems
included — so most pilots flagged. This step writes
layers_raw/water_systems/sdwis_locations_<fips>.csv, one row per active system:

    pwsid, pws_name, lon, lat, method, matched_town

method is, in order of preference:
  epa_service_area — the system's service area polygon from EPA's Public Water System
                  Service Areas v3 (March 2026; ~44,000 community systems, ~56% state- or
                  utility-sourced, the rest EPA-modelled). The marker sits at a point inside
                  the part of that polygon within the county (plus ~1 km). The polygons
                  are kept in epa_service_areas_<fips>.geojson with their source flags.
  osm_place     — the served town matches an OSM place node in the county's buffered bbox
  census_place  — it matches a Census Gazetteer place or county subdivision (2024; the
                  township layer matters in NJ, PA, New England) in the same state whose
                  internal point lies inside the buffered bbox (so a same-named town
                  elsewhere in the state cannot capture it)
  census_zcta   — no served town matched, but the system's ZIP code is a Census ZCTA
                  whose internal point lies inside the buffered bbox
  unplaced      — nothing matched; lon/lat blank

Systems whose county record names no town (common: Teton ID has 22 of 26) are looked up
once in the EPA WATER_SYSTEM table for city and ZIP. Those are the system's mailing
address, which can be far away, so they count only if the matched point falls inside
the county's buffered bbox. Only city, ZIP and name are kept from that lookup; contact
fields (owner, administrator, email, phone) are never stored.

Positions are town points, not intake or plant sites: provenance "derived (served-town
point)". A system serving several towns is placed at the first that matches.
The Census Gazetteer file is downloaded once into $RURALSIM_CACHE (public domain).
"""
from __future__ import annotations

import io, json, os, pathlib, re, sys, time, urllib.request, zipfile

import pandas as pd

REPO = pathlib.Path(__file__).resolve().parent.parent
CACHE = pathlib.Path(os.environ.get("RURALSIM_CACHE", "/tmp/ruralsim_cache")) / "census"
GAZ_BASE = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/"
EF_BASE = "https://data.epa.gov/efservice"
# EPA ORD Public Water System Service Areas v3 (2026-03-17), public domain:
# community systems (~44,000) and transient/non-transient non-community systems (~78,000,
# parcel-level: camps, schools, gas stations, plants)
_EPA_ORG = "https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/"
SAB_LAYERS = (
    ("community", _EPA_ORG + "Water_System_Boundaries/FeatureServer/0/query",
     ("PWSID", "PWS_Name", "Data_Provider_Type", "Model_Method", "Service_Area_Type")),
    ("non-community", _EPA_ORG + "Transient_and_Non_Transient_Non_Community_Water_System_"
     "Service_Areas/FeatureServer/0/query",
     ("PWSID", "PWS_Name", "LOCATION_CONFIDENCE", "Data_Source", "SERVICE_AREA_TYPE")),
)
KEEP_WS_FIELDS = ("pws_name", "city_name", "zip_code")  # never contact fields
UA = {"User-Agent": "RuralSim/1.0 (+https://www.ruralsim.io; county twin build)"}
_SUFFIX = re.compile(r"\s+(city|town|village|borough|boro|CDP|municipality|city and borough|"
                     r"consolidated government|unified government|metro government|"
                     r"urban county|plantation|township|twp|charter township|gore|grant|"
                     r"location|purchase|unorganized territory|CCD|precinct)(\s+\(balance\))?$", re.I)
# New Jersey writes served towns with its municipal code: "ALLOWAY TWP-.1701",
# "PITTSGROVE TWP.-1710", "LOWER ALLOWAYS CR.-1704". Salem NJ placed 0 of 105 systems
# until the code, the period and the abbreviation were handled (canary run 43794676050).
_MUNI_CODE = re.compile(r"[\s.]*-[\s.]*\d+\s*$")
_ABBREV = {"CR": "CREEK", "CRK": "CREEK", "PT": "POINT", "HTS": "HEIGHTS", "SPGS": "SPRINGS",
           "LK": "LAKE", "FT": "FORT", "TWP": "TOWNSHIP", "BORO": "BOROUGH"}


def norm(name: str) -> str:
    s = re.sub(r"\(.*?\)", "", str(name)).strip()
    s = _MUNI_CODE.sub("", s).upper()
    s = s.replace("SAINT ", "ST ").replace("ST. ", "ST ").replace("MOUNT ", "MT ")
    s = re.sub(r"[^A-Z0-9 ]", "", s)
    s = " ".join(_ABBREV.get(w, w) for w in s.split())
    return _SUFFIX.sub("", s).strip()


def _s(v) -> str:
    s = "" if v is None else str(v)
    return "" if s.lower() == "nan" else s.strip()


def _gaz(kind: str) -> pd.DataFrame:
    """Census 2024 Gazetteer national file ('place' or 'zcta'), cached."""
    CACHE.mkdir(parents=True, exist_ok=True)
    fname = f"2024_Gaz_{kind}_national.zip"
    p = CACHE / fname
    if not p.exists():
        print(f"  downloading Census Gazetteer ({kind}) ...", flush=True)
        req = urllib.request.Request(GAZ_BASE + fname, headers=UA)
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
        p.with_suffix(".part").write_bytes(data)
        os.replace(p.with_suffix(".part"), p)
    with zipfile.ZipFile(p) as z:
        name = next(n for n in z.namelist() if n.endswith(".txt"))
        g = pd.read_csv(io.BytesIO(z.read(name)), sep="\t", dtype=str, encoding="latin-1")
    g.columns = [c.strip() for c in g.columns]
    g["lat"] = g["INTPTLAT"].astype(float)
    g["lon"] = g["INTPTLONG"].astype(float)
    return g


def gazetteer() -> pd.DataFrame:
    """Census places plus county subdivisions. Townships (NJ, PA, New England, the
    Midwest) are county subdivisions, not places, and are what SDWIS names there."""
    g = _gaz("place")
    try:
        c = _gaz("cousubs")
        c = c[~c["NAME"].str.contains("unorganized|not defined", case=False, na=False)]
        g = pd.concat([g, c[["USPS", "NAME", "lon", "lat"]]], ignore_index=True)
    except Exception as e:  # places alone still work
        print(f"  county-subdivision gazetteer unavailable: {e}", file=sys.stderr)
    g["key"] = g["NAME"].map(norm)
    return g[["USPS", "NAME", "key", "lon", "lat"]]


def zctas() -> pd.DataFrame:
    g = _gaz("zcta")
    return g[["GEOID", "lon", "lat"]]


EPA_WORKERS = 4  # concurrent Envirofacts requests; 8 drew HTTP 429 on Harris TX (run #13)
MAX_FAIL_SHARE = 0.02  # more failed lookups than this fails the step instead of publishing a gap


def epa_get(url: str, timeout: int = 120, tries: int = 6):
    """GET + JSON from Envirofacts, retrying 429 (rate limit) and 5xx/network errors with
    backoff. Honours Retry-After. Run #13 (Harris TX) lost 1,841 violation and 1,319
    WATER_SYSTEM lookups to unretried 429s and still published."""
    import random, urllib.error
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if (e.code != 429 and e.code < 500) or attempt + 1 == tries:
                raise
            ra = e.headers.get("Retry-After") if e.headers else None
            wait = float(ra) if ra and ra.isdigit() else 5 * 2 ** attempt
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt + 1 == tries:
                raise
            wait = 5 * 2 ** attempt
        time.sleep(wait + random.uniform(0, 2))


def ws_lookup(pwsids: list[str], cache_path: pathlib.Path) -> dict:
    """city/ZIP/name from EPA WATER_SYSTEM for systems whose county record has no town.
    Eight lookups at a time: Harris TX has ~2,500 systems and one-at-a-time lookups ran
    past the 300-minute job limit (Texas run #12)."""
    import concurrent.futures as cf
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    def one(pid):
        try:
            recs = json.loads(epa_get(f"{EF_BASE}/WATER_SYSTEM/PWSID/{pid}/JSON"))
            rec = recs[0] if isinstance(recs, list) and recs else {}
            return pid, {k: rec.get(k) for k in KEEP_WS_FIELDS}
        except Exception as e:
            print(f"  WATER_SYSTEM lookup failed for {pid}: {e}", file=sys.stderr)
            return pid, None

    todo = [pid for pid in pwsids if pid not in cache]
    failed = 0
    with cf.ThreadPoolExecutor(EPA_WORKERS) as ex:
        for pid, rec in ex.map(one, todo):
            if rec is not None:
                cache[pid] = rec
            else:
                failed += 1
    cache_path.write_text(json.dumps(cache, indent=1))  # keep what worked for the retry
    if todo and failed / len(todo) > MAX_FAIL_SHARE:
        raise RuntimeError(f"WATER_SYSTEM lookups failed for {failed} of {len(todo)} systems")
    cache_path.write_text(json.dumps(cache, indent=1))
    return cache


def sab_lookup(pwsids: list[str], cache_path: pathlib.Path) -> dict:
    """{pwsid: GeoJSON feature} from EPA's service-area layers (community first, then
    non-community), 100 IDs per POST, cached."""
    import urllib.parse
    if cache_path.exists():
        fc = json.loads(cache_path.read_text())
        cached = {f["properties"]["PWSID"]: f for f in fc["features"]}
        if set(pwsids) <= set(cached) | set(fc.get("not_found", [])):
            return cached
    found, ids = {}, sorted(set(pwsids))
    for kind, url, fields in SAB_LAYERS:
        todo = [x for x in ids if x not in found and re.fullmatch(r"[A-Z0-9]+", x)]
        for i in range(0, len(todo), 100):
            chunk = todo[i:i + 100]
            body = urllib.parse.urlencode({
                "where": "PWSID IN (" + ",".join(f"'{x}'" for x in chunk) + ")",
                "outFields": ",".join(fields), "returnGeometry": "true", "outSR": "4326",
                "maxAllowableOffset": "0.0005", "geometryPrecision": "5", "f": "geojson"}).encode()
            for attempt in range(5):
                try:
                    req = urllib.request.Request(url, data=body, headers=UA)
                    with urllib.request.urlopen(req, timeout=180) as r:
                        fc = json.load(r)
                    if "error" in fc:
                        raise RuntimeError(str(fc["error"])[:200])
                    break
                except Exception as e:
                    if attempt == 4:
                        raise
                    print(f"  EPA {kind} service areas retry ({e})", flush=True)
                    time.sleep(10 * (attempt + 1))
            for f in fc.get("features", []):
                props = f.get("properties") or {}
                pid = props.get("PWSID")
                if pid and f.get("geometry"):
                    props["ruralsim_layer"] = kind
                    found.setdefault(pid, f)  # a system can have several rows; keep the first
    cache_path.write_text(json.dumps({"type": "FeatureCollection", "features": list(found.values()),
                                      "not_found": [x for x in ids if x not in found],
                                      "source": "EPA Public Water System Service Areas v3 (2026-03-17)",
                                      "license": "public domain",
                                      "urls": [u.rsplit("/query", 1)[0] for _, u, _ in SAB_LAYERS]}))
    return found


def sab_point(feature, area):
    """A point inside the system's service area, within `area` (county + ~1 km) when the
    two overlap; None when the service area lies wholly outside the county."""
    from shapely.geometry import shape
    try:
        g = shape(feature["geometry"]).buffer(0)
    except Exception:
        return None
    if g.is_empty:
        return None
    part = g.intersection(area)
    if part.is_empty:
        return None
    p = part.representative_point()
    return round(p.x, 6), round(p.y, 6)


def served_towns(r) -> list[str]:
    raw = [_s(r.get("city_name")), _s(r.get("city_served"))]
    towns = []
    for field in raw:
        for t in re.split(r"[,;/]", field):
            t = t.strip()
            if t and t.upper() not in {x.upper() for x in towns}:
                towns.append(t)
    return towns


def place(C) -> pathlib.Path:
    raw = C.world / "layers_raw"
    sysf = raw / "water_systems" / f"sdwis_systems_{C.fips}.csv"
    wsy = pd.read_csv(sysf, dtype=str, low_memory=False)
    if "pws_activity_code" in wsy.columns:
        wsy = wsy[wsy["pws_activity_code"] == "A"]
    wsy = wsy.drop_duplicates("pwsid")
    w, s, e, n = C.buf_bbox

    osm = {}
    pl = raw / "osm" / "places.geojson"
    if pl.exists():
        for f in json.loads(pl.read_text())["features"]:
            nm = f["properties"].get("name")
            if nm and f["geometry"]["type"] == "Point":
                osm.setdefault(norm(nm), (f["geometry"]["coordinates"], nm))

    gz = gazetteer()
    gz = gz[(gz.USPS == C.st) & gz.lon.between(w, e) & gz.lat.between(s, n)]
    census = {}
    for _, g in gz.iterrows():
        census.setdefault(g.key, ((g.lon, g.lat), g.NAME))

    # 1. EPA service-area polygons (v3). A failure here is not fatal: fall back to towns.
    sab, area = {}, None
    try:
        area = C.geom.buffer(0.01)
        sab = sab_lookup([_s(x) for x in wsy["pwsid"]],
                         raw / "water_systems" / f"epa_service_areas_{C.fips}.geojson")
    except Exception as e:
        print(f"  EPA service areas unavailable ({e}); placing by served town only", flush=True)
    sab_pts = {}
    for pid, f in sab.items():
        pt = sab_point(f, area) if area is not None else None
        if pt:
            pp = f.get("properties") or {}
            if pp.get("ruralsim_layer") == "non-community":
                src = "non-community, " + (_s(pp.get("LOCATION_CONFIDENCE")) or "parcel")
            else:
                src = "EPA-modelled" if _s(pp.get("Model_Method")) else (_s(pp.get("Data_Provider_Type")) or "authoritative")
            sab_pts[pid] = (pt, src)

    # systems with no service area and whose county record names no town: one
    # WATER_SYSTEM lookup each (cached)
    no_town = [_s(r.get("pwsid")) for _, r in wsy.iterrows()
               if not served_towns(r) and _s(r.get("pwsid")) not in sab_pts]
    ws = ws_lookup(no_town, raw / "water_systems" / "_water_system_lookup.json") if no_town else {}
    zc = None

    rows = []
    for _, r in wsy.iterrows():
        pid = _s(r.get("pwsid"))
        extra = ws.get(pid, {})
        rec = {"pwsid": pid, "pws_name": _s(r.get("pws_name")) or _s(extra.get("pws_name")),
               "lon": "", "lat": "", "method": "unplaced", "matched_town": ""}
        if pid in sab_pts:
            (lon, lat), src = sab_pts[pid]
            rec.update(lon=lon, lat=lat, method="epa_service_area", matched_town=f"service area ({src})")
            rows.append(rec)
            continue
        towns = served_towns(r) or ([_s(extra.get("city_name"))] if _s(extra.get("city_name")) else [])
        for town in towns:
            k = norm(town)
            for method, table in (("osm_place", osm), ("census_place", census)):
                if k in table:
                    (lon, lat), name = table[k]
                    rec.update(lon=round(float(lon), 6), lat=round(float(lat), 6),
                               method=method, matched_town=name)
                    break
            if rec["method"] != "unplaced":
                break
        zipc = (_s(r.get("zip_code")) or _s(r.get("zip_code_served")) or _s(extra.get("zip_code")))[:5]
        if rec["method"] == "unplaced" and len(zipc) == 5 and zipc.isdigit():
            if zc is None:
                z = zctas()
                zc = {g.GEOID: (g.lon, g.lat) for g in z.itertuples()
                      if w <= g.lon <= e and s <= g.lat <= n}
            if zipc in zc:
                lon, lat = zc[zipc]
                rec.update(lon=round(float(lon), 6), lat=round(float(lat), 6),
                           method="census_zcta", matched_town=f"ZIP {zipc}")
        rows.append(rec)
    out = raw / "water_systems" / f"sdwis_locations_{C.fips}.csv"
    df = pd.DataFrame(rows, columns=["pwsid", "pws_name", "lon", "lat", "method", "matched_town"])
    df.to_csv(out, index=False)
    counts = df["method"].value_counts().to_dict()
    print(f"water systems placed ({C.fips}): {len(df)} active —",
          ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return out


if __name__ == "__main__":
    sys.path.insert(0, str(REPO / "tools"))
    from county_config import get
    place(get(sys.argv[1] if len(sys.argv) > 1 else None))
