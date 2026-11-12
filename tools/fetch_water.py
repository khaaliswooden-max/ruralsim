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
import json, pathlib, urllib.request, datetime, time, sys
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from county_config import get
C = get(sys.argv[1] if len(sys.argv) > 1 else None)
FIPS = C.fips
REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = C.world / "layers_raw" / "water_systems"
OUT.mkdir(parents=True, exist_ok=True)
if (OUT / f"sdwis_systems_{FIPS}.csv").exists():
    print(f"water: sdwis_systems_{FIPS}.csv already present, skipping (delete to re-fetch)")
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
    req = urllib.request.Request(f"{BASE}/{path}", headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r:
        raw = r.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(raw)
        return [{c.tag: (c.text or "") for c in child} for child in root]

geo = ef(f"GEOGRAPHIC_AREA/COUNTY_SERVED/{C.name_short}/JSON")
g = pd.DataFrame(geo)
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
    trib = wa[(wa["primacy_agency_code"] == reg) & (wa[citycol].str.upper().isin(TOWNS))]
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

viol_all = []
for pid in systems["pwsid"]:
    try:
        v = ef(f"VIOLATION/PWSID/{pid}/JSON")
        if isinstance(v, list):
            viol_all.extend(v)
    except Exception as e:
        print("viol fail", pid, e)
    time.sleep(0.3)
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
print("done")
