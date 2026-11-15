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
  osm_place     — the served town matches an OSM place node in the county's buffered bbox
  census_place  — it matches a Census Gazetteer place (2024) in the same state whose
                  internal point lies inside the buffered bbox (so a same-named town
                  elsewhere in the state cannot capture it)
  unplaced      — no served town given, or none matched; lon/lat blank

Positions are town points, not intake or plant sites: provenance "derived (served-town
point)". A system serving several towns is placed at the first that matches.
The Census Gazetteer file is downloaded once into $RURALSIM_CACHE (public domain).
"""
from __future__ import annotations

import io, json, os, pathlib, re, sys, urllib.request, zipfile

import pandas as pd

REPO = pathlib.Path(__file__).resolve().parent.parent
CACHE = pathlib.Path(os.environ.get("RURALSIM_CACHE", "/tmp/ruralsim_cache")) / "census"
GAZ_URL = ("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
           "2024_Gazetteer/2024_Gaz_place_national.zip")
UA = {"User-Agent": "RuralSim/1.0 (+https://www.ruralsim.io; county twin build)"}
_SUFFIX = re.compile(r"\s+(city|town|village|borough|CDP|municipality|city and borough|"
                     r"consolidated government|unified government|metro government|"
                     r"urban county|plantation)(\s+\(balance\))?$", re.I)


def norm(name: str) -> str:
    s = _SUFFIX.sub("", str(name).strip())
    s = s.upper().replace("SAINT ", "ST ").replace("ST. ", "ST ").replace("MOUNT ", "MT ")
    return re.sub(r"[^A-Z0-9 ]", "", s).strip()


def _s(v) -> str:
    s = "" if v is None else str(v)
    return "" if s.lower() == "nan" else s.strip()


def gazetteer() -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / "2024_Gaz_place_national.zip"
    if not p.exists():
        print("  downloading Census Gazetteer places ...", flush=True)
        req = urllib.request.Request(GAZ_URL, headers=UA)
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
    g["key"] = g["NAME"].map(norm)
    return g[["USPS", "NAME", "key", "lon", "lat"]]


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

    rows = []
    for _, r in wsy.iterrows():
        rec = {"pwsid": _s(r.get("pwsid")), "pws_name": _s(r.get("pws_name")),
               "lon": "", "lat": "", "method": "unplaced", "matched_town": ""}
        for town in served_towns(r):
            k = norm(town)
            for method, table in (("osm_place", osm), ("census_place", census)):
                if k in table:
                    (lon, lat), name = table[k]
                    rec.update(lon=round(float(lon), 6), lat=round(float(lat), 6),
                               method=method, matched_town=name)
                    break
            if rec["method"] != "unplaced":
                break
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
