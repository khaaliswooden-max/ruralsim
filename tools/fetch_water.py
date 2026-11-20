#!/usr/bin/env python3
"""EPA SDWIS drinking-water systems for Thurston County NE via Envirofacts REST.

Discovery notes (recorded in _meta.json):
- WATER_SYSTEM table ignores COUNTY_SERVED filter (returns national set) - do not use.
- GEOGRAPHIC_AREA honours COUNTY_SERVED but matches both Thurston NE and Thurston WA;
  filter to primacy_agency_code == 'NE'.
- Tribal-primacy systems (EPA Region 07, pwsid 07xxxxxxx) have no county_served
  record; they are assigned by the WATER_SYSTEM city field against county towns.
Manifest layer: water_systems. Provenance: observed (EPA SDWIS via Envirofacts).
"""
import json, pathlib, urllib.error, urllib.parse, urllib.request, datetime, time, sys
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from county_config import get
C = get(sys.argv[1] if len(sys.argv) > 1 else None)
FIPS = C.fips
REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = C.world / "layers_raw" / "water_systems"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(REPO / "tools"))
from place_water_systems import place, epa_get, EPA_WORKERS, MAX_FAIL_SHARE  # noqa: E402  (D-030)
if (OUT / f"sdwis_systems_{FIPS}.csv").exists():
    print(f"water: sdwis_systems_{FIPS}.csv already present, skipping fetch (delete to re-fetch)")
    if not (OUT / f"sdwis_locations_{FIPS}.csv").exists():
        place(C)
    sys.exit(0)
BASE = "https://data.epa.gov/efservice"
UA = {"User-Agent": "RuralSim-research/0.1"}
# towns from the county's own OSM places layer (fetch_osm runs before this tool)
TOWNS = set()
places = C.world / "layers_raw" / "osm" / "places.geojson"
if places.exists():
    for f in json.loads(places.read_text())["features"]:
        nm = (f["properties"].get("name") or "").upper()
        if nm:
            TOWNS.add(nm)
print("county towns for matching:", sorted(TOWNS))

def ef(path):
    # names with spaces ("New York", "District of Columbia", CT planning regions) must be
    # percent-encoded or urllib refuses the URL (canary run 43794676050)
    raw = epa_get(f"{BASE}/{urllib.parse.quote(path)}", timeout=300)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(raw)
        return [{c.tag: (c.text or "") for c in child} for child in root]

geo = ef(f"GEOGRAPHIC_AREA/COUNTY_SERVED/{C.name_short}/JSON")
g = pd.DataFrame(geo)
if g.empty or "primacy_agency_code" not in g.columns:
    g = pd.DataFrame(columns=["pwsid", "primacy_agency_code"])
ne = g[g["primacy_agency_code"] == C.st]
print(f"{C.st}-primacy systems serving {C.name_short} Co:", ne.pwsid.nunique())

# tribal-primacy systems (EPA region set; national table is too slow). Only worth
# querying when the county actually has tribal lands (tribal file from fetch_arcgis).
trib = pd.DataFrame()
reg = f"{C.epa_region:02d}"
tribal_file = C.world / "layers_raw" / "tribal" / f"tribal_{FIPS}.geojson"
has_tribal = tribal_file.exists() and len(json.loads(tribal_file.read_text())["features"]) > 0
if has_tribal:
    ws_all = ef(f"WATER_SYSTEM/PRIMACY_AGENCY_CODE/{reg}/JSON")
    wa = pd.DataFrame(ws_all)
    print(f"region-{reg} tribal systems total:", len(wa))
    citycol = next((c for c in wa.columns if "city" in c.lower()), None)
    if wa.empty or citycol is None or "primacy_agency_code" not in wa.columns:
        # no tribal-primacy systems in this EPA region (DE, HI, LA in the canary): an empty
        # answer has no columns, so there is nothing to match (canary run 43794676050)
        wa = pd.DataFrame(columns=["pwsid", "primacy_agency_code"])
        citycol = "city_name"
        wa[citycol] = []
    trib = wa[(wa["primacy_agency_code"] == reg) & (wa[citycol].astype(str).str.upper().isin(TOWNS))]
    print("tribal-primacy systems in county towns:", len(trib))
    if len(trib):
        print(trib[["pwsid", "pws_name", citycol, "population_served_count"]].to_string())
    systems = pd.concat([
        ne.merge(wa, on="pwsid", how="left", suffixes=("", "_ws")),
        trib], ignore_index=True).drop_duplicates("pwsid")
else:
    print("no tribal lands in county - skipping tribal-primacy query")
    systems = ne.drop_duplicates("pwsid")
systems.to_csv(OUT / f"sdwis_systems_{FIPS}.csv", index=False)
print("total systems:", len(systems))

def viol(pid):
    try:
        v = ef(f"VIOLATION/PWSID/{pid}/JSON")
        return v if isinstance(v, list) else []
    except Exception as e:
        print("viol fail", pid, e)
        return None


# All violations of the county's state-primacy systems in one joined Envirofacts query
# (GEOGRAPHIC_AREA -> VIOLATION on pwsid), paged 5,000 rows at a time (D-049). One request per
# system took Cook IL 15,285 s for 3,105 systems (run #38) and Harris TX past the job limit;
# the joined query returns the same 7,167 Cook rows in ~15 s. Tribal-primacy systems, and
# every system if the joined query fails or comes back short, still go one PWSID at a time.
GEO_ONLY = ["geo_id", "tribal_code", "state_served", "ansi_entity_code", "zip_code_served",
            "city_served", "area_type_code", "county_served"]
PAGE = 5000


def county_violations():
    """Violations of the state-primacy systems serving the county, or None to fall back."""
    q = f"GEOGRAPHIC_AREA/COUNTY_SERVED/{C.name_short}/PRIMACY_AGENCY_CODE/{C.st}/VIOLATION"
    try:
        n = int(ef(f"{q}/COUNT/JSON")[0]["TOTALQUERYRESULTS"])
        rows = []
        for a in range(0, n, PAGE):
            page = ef(f"{q}/ROWS/{a}:{min(a + PAGE, n) - 1}/JSON")
            rows.extend(page if isinstance(page, list) else [])
    except Exception as e:
        print(f"joined violation query failed ({str(e)[:160]}); looking up one system at a time", flush=True)
        return None
    if len(rows) != n:
        print(f"joined violation query returned {len(rows)} of {n} rows; looking up one system at a time", flush=True)
        return None
    seen, out = set(), []
    for r in rows:  # a system listed twice for the county would repeat its violations
        k = (r.get("pwsid"), r.get("violation_id"))
        if k not in seen:
            seen.add(k)
            out.append({c: v for c, v in r.items() if c not in GEO_ONLY})
    return out


import concurrent.futures as cf
viol_all = []
t0 = time.time()
viol_failed = 0
per_system = list(systems["pwsid"])
joined = county_violations() if len(ne) else []
if joined is not None:
    viol_all.extend(joined)
    state_ids = set(ne["pwsid"])
    per_system = [p for p in per_system if p not in state_ids]  # tribal-primacy systems only
    print(f"violation lookup (joined): {len(state_ids)} {C.st}-primacy systems, {len(joined)} rows "
          f"in {time.time() - t0:.0f} s", flush=True)
# a few requests at a time (EPA_WORKERS)
with cf.ThreadPoolExecutor(EPA_WORKERS) as ex:
    for v in ex.map(viol, per_system):
        if v is None:
            viol_failed += 1
        else:
            viol_all.extend(v)
print(f"violation lookups: {len(systems)} systems in {time.time() - t0:.0f} s "
      f"({len(per_system)} one at a time), {viol_failed} failed", flush=True)
if len(per_system) and viol_failed / len(per_system) > MAX_FAIL_SHARE:
    sys.exit(f"violation lookups failed for {viol_failed} of {len(per_system)} systems; "
             "not publishing a partial count")
vdf = pd.DataFrame(viol_all)
vdf.to_csv(OUT / f"sdwis_violations_{FIPS}.csv", index=False)
print("violations all-time:", len(vdf))
if len(vdf):
    vdf["comp_date"] = pd.to_datetime(vdf.get("compl_per_begin_date"), errors="coerce")
    recent = vdf[vdf["comp_date"] >= "2016-01-01"]
    print("violations since 2016:", len(recent), "| health-based:",
          int((recent.get("is_health_based_ind") == "Y").sum()) if "is_health_based_ind" in recent else "n/a")

meta = {"retrieved_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "source": "EPA SDWIS via Envirofacts REST (data.epa.gov/efservice)",
        "license": "public domain", "provenance": "observed",
        "method_note": (f"county_served is name-matched ('{C.name_short}' may collide with other states) "
                        f"- restricted to primacy {C.st}; "
                        f"tribal-primacy (EPA R{reg}) systems assigned by city match to county towns"
                        if has_tribal else
                        f"county_served name match restricted to primacy {C.st}; no tribal lands, "
                        "tribal-primacy query skipped"),
        "state_primacy_systems": int(ne.pwsid.nunique()),
        "tribal_primacy_systems": int(len(trib)),
        "violations_all_time": int(len(vdf))}
(OUT / "_meta.json").write_text(json.dumps(meta, indent=2))
place(C)
print("done")
