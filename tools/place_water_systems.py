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
KEEP_WS_FIELDS = ("pws_name", "city_name", "zip_code")  # never contact fields
UA = {"User-Agent": "RuralSim/1.0 (+https://www.ruralsim.io; county twin build)"}
_SUFFIX = re.compile(r"\s+(city|town|village|borough|CDP|municipality|city and borough|"
                     r"consolidated government|unified government|metro government|"
                     r"urban county|plantation)(\s+\(balance\))?$", re.I)


def norm(name: str) -> str:
    s = re.sub(r"\(.*?\)", "", str(name)).strip()
    s = _SUFFIX.sub("", s)
    s = s.upper().replace("SAINT ", "ST ").replace("ST. ", "ST ").replace("MOUNT ", "MT ")
    return re.sub(r"[^A-Z0-9 ]", "", s).strip()


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
    g = _gaz("place")
    g["key"] = g["NAME"].map(norm)
    return g[["USPS", "NAME", "key", "lon", "lat"]]


def zctas() -> pd.DataFrame:
    g = _gaz("zcta")
    return g[["GEOID", "lon", "lat"]]


def ws_lookup(pwsids: list[str], cache_path: pathlib.Path) -> dict:
    """city/ZIP/name from EPA WATER_SYSTEM for systems whose county record has no town."""
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    for pid in pwsids:
        if pid in cache:
            continue
        try:
            req = urllib.request.Request(f"{EF_BASE}/WATER_SYSTEM/PWSID/{pid}/JSON", headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                recs = json.load(r)
            rec = recs[0] if isinstance(recs, list) and recs else {}
            cache[pid] = {k: rec.get(k) for k in KEEP_WS_FIELDS}
        except Exception as e:
            print(f"  WATER_SYSTEM lookup failed for {pid}: {e}", file=sys.stderr)
        time.sleep(0.3)
    cache_path.write_text(json.dumps(cache, indent=1))
    return cache


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

    # systems whose county record names no town: one WATER_SYSTEM lookup each (cached)
    no_town = [_s(r.get("pwsid")) for _, r in wsy.iterrows() if not served_towns(r)]
    ws = ws_lookup(no_town, raw / "water_systems" / "_water_system_lookup.json") if no_town else {}
    zc = None

    rows = []
    for _, r in wsy.iterrows():
        pid = _s(r.get("pwsid"))
        extra = ws.get(pid, {})
        rec = {"pwsid": pid, "pws_name": _s(r.get("pws_name")) or _s(extra.get("pws_name")),
               "lon": "", "lat": "", "method": "unplaced", "matched_town": ""}
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
