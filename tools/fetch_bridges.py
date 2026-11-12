#!/usr/bin/env python3
"""Fetch FHWA National Bridge Inventory (2024 delimited, all states) and extract
bridges in/near Thurston County NE (NBI state 31, county 173).

Manifest layer: bridges. Provenance: observed (FHWA NBI 2024), public domain.
NBI lat/long are DDMMSS.FF (hemisphere implied N/W); converted to decimal degrees.
"""
import csv, io, json, pathlib, urllib.request, zipfile, datetime, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from county_config import get
C = get(sys.argv[1] if len(sys.argv) > 1 else None)
FIPS = C.fips
REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = C.world / "layers_raw" / "bridges"
OUT.mkdir(parents=True, exist_ok=True)
if (OUT / f"nbi_{FIPS}.geojson").exists():
    print(f"bridges: nbi_{FIPS}.geojson already present, skipping (delete to re-fetch)")
    sys.exit(0)
# bounds sanity filter: county bbox +- 0.75 deg
BW, BS, BE, BN = C.bbox
LAT_LO, LAT_HI, LON_LO, LON_HI = BS - 0.75, BN + 0.75, -BE - 0.75, -BW + 0.75  # lon stored west-positive below
URL = "https://www.fhwa.dot.gov/bridge/nbi/2024del.zip"
zp = pathlib.Path("/tmp/ruralsim_cache/nbi2024.zip"); zp.parent.mkdir(parents=True, exist_ok=True)

if not zp.exists():
    print("downloading NBI 2024 (~53 MB) ...", flush=True)
    req = urllib.request.Request(URL, headers={"User-Agent": "RuralSim-research/0.1"})
    with urllib.request.urlopen(req, timeout=900) as r, open(zp, "wb") as f:
        while True:
            c = r.read(1 << 20)
            if not c:
                break
            f.write(c)
print("zip size MB:", zp.stat().st_size / 1e6)

zf = zipfile.ZipFile(zp)
name = next(n for n in zf.namelist() if n.upper().startswith(C.st.upper() + "24"))
print("member:", name)

def dms_to_dd(v):
    """NBI format: lat = DDMMSSss (8 digits), lon = DDDMMSSss (9 digits)."""
    v = (v or "").strip()
    if not v or set(v) == {"0"}:
        return None
    if not v.isdigit() or len(v) not in (7, 8, 9):
        return None
    if len(v) == 9:      # DDDMMSSss
        d, m, s = int(v[:3]), int(v[3:5]), int(v[5:]) / 100
    elif len(v) == 8:    # DDMMSSss
        d, m, s = int(v[:2]), int(v[2:4]), int(v[4:]) / 100
    else:                # DMMSSss, rare
        d, m, s = int(v[:1]), int(v[1:3]), int(v[3:]) / 100
    if m >= 60 or s >= 60 or d > 180:
        return None
    return d + m / 60 + s / 3600

rows = []
with zf.open(name) as fh:
    rdr = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"))
    cols = rdr.fieldnames
    for r in rdr:
        if r.get("STATE_CODE_001") in (C.state_fips, C.state_fips.zfill(3)) \
                and r.get("COUNTY_CODE_003") == C.county_code:
            rows.append(r)
print(f"bridges in {C.county_name}:", len(rows))

feats = []
for r in rows:
    lat, lon = dms_to_dd(r.get("LAT_016")), dms_to_dd(r.get("LONG_017"))
    if lat is None or lon is None or not (LAT_LO <= lat <= LAT_HI and LON_LO <= lon <= LON_HI):
        continue
    feats.append({"type": "Feature",
                  "geometry": {"type": "Point", "coordinates": [-lon, lat]},
                  "properties": {
                      "structure_number": r.get("STRUCTURE_NUMBER_008"),
                      "year_built": r.get("YEAR_BUILT_027"),
                      "deck_cond": r.get("DECK_COND_058"),
                      "superstructure_cond": r.get("SUPERSTRUCTURE_COND_059"),
                      "substructure_cond": r.get("SUBSTRUCTURE_COND_060"),
                      "culvert_cond": r.get("CULVERT_COND_062"),
                      "structural_eval": r.get("STRUCTURAL_EVAL_067"),
                      "operating_rating_tons": r.get("OPERATING_RATING_064"),
                      "bridge_condition": r.get("BRIDGE_CONDITION"),
                      "open_closed_posted": r.get("OPEN_CLOSED_POSTED_041"),
                      "scour_critical": r.get("SCOUR_CRITICAL_113"),
                      "adt": r.get("ADT_029"),
                      "carries": r.get("FEATURES_DESC_006A"),
                      "crosses": r.get("FACILITY_CARRIED_007")}})
gj = {"type": "FeatureCollection", "features": feats}
(OUT / f"nbi_{FIPS}.geojson").write_text(json.dumps(gj))
meta = {"retrieved_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "source": "FHWA National Bridge Inventory 2024 (delimited, all states)",
        "license": "public domain", "provenance": "observed",
        "url": URL, "county_records": len(rows), "geocoded": len(feats)}
(OUT / "_meta.json").write_text(json.dumps(meta, indent=2))
print("wrote", len(feats), "geocoded bridge points")
