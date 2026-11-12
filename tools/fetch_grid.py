#!/usr/bin/env python3
"""Fetch EIA grid layers for Thurston County NE.

- grid_generation: EIA-860 2024 plant+generator tables -> plants located in the
  county (lat/lon included). Manifest: grid_generation. Provenance: observed.
- grid_utility_territory: EIA-861 2024 Service Territory file -> utilities
  serving Thurston county; flag cooperatives (ownership type). Manifest:
  grid_utility_territory. Provenance: observed.
Downloads go to /tmp cache; extracts to repo layers_raw/grid/.
"""
import json, pathlib, urllib.request, zipfile, datetime, io, sys
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from county_config import get
C = get(sys.argv[1] if len(sys.argv) > 1 else None)
FIPS = C.fips
REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = C.world / "layers_raw" / "grid"
OUT.mkdir(parents=True, exist_ok=True)
# No early exit on present CSVs: the portal mount serves stale exists() results
# and drops files in the gap between this check and the build's EXPECT glob
# (20019 eia860_plants twice "present" at fetch start, gone seconds later at
# EXPECT, 2026-11-12; D-019 refined). The expensive part is the zip download,
# cached in /tmp — regenerating CSVs from cache is cheap, so always regenerate
# and always run the settle-and-heal loop.
CACHE = pathlib.Path("/tmp/ruralsim_cache/eia"); CACHE.mkdir(parents=True, exist_ok=True)
STAGE = pathlib.Path("/tmp/ruralsim_staging") / FIPS / "grid"; STAGE.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "RuralSim-research/0.1"}

def get(url, dest):
    if not dest.exists():
        print(f"downloading {url} ...", flush=True)
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=900) as r, open(dest, "wb") as f:
            while True:
                c = r.read(1 << 20)
                if not c: break
                f.write(c)
    return dest

# --- EIA-860 ---
z860 = get("https://www.eia.gov/electricity/data/eia860/archive/xls/eia8602024.zip", CACHE / "eia8602024.zip")
z = zipfile.ZipFile(z860)
print("860 members:", [n for n in z.namelist() if "lant" in n.lower()][:5])
plant_file = next(n for n in z.namelist() if "2___plant" in n.lower() or "plant" in n.lower() and n.endswith(".xlsx"))
with z.open(plant_file) as fh:
    plants = pd.read_excel(fh, sheet_name="Plant", skiprows=1)
ne = plants[(plants["State"] == C.st)]
print(f"{C.st} plants:", len(ne))
cols = [c for c in ne.columns]
print(cols[:25])
thur = ne[ne["County"].str.upper().str.contains(C.name_short.upper(), na=False)]
print(f"{C.name_short} plants:", len(thur))
import shutil
def stage_write(df, fn):
    """Write CSV via /tmp staging; a zero-plant county yields a header-only
    CSV - that IS the observed answer, not a missing file."""
    staged = STAGE / fn
    df.to_csv(staged, index=False)
    shutil.copy2(staged, OUT / fn)
    if not (OUT / fn).exists():
        raise RuntimeError(f"write did not persist: {fn}")

for df, fn in ((thur, f"eia860_plants_{FIPS}.csv"), (ne, f"eia860_plants_{C.st}.csv")):
    stage_write(df, fn)

# --- EIA-861 service territory ---
z861 = get("https://www.eia.gov/electricity/data/eia861/archive/zip/f8612024.zip", CACHE / "f8612024.zip")
z = zipfile.ZipFile(z861)
cand = [n for n in z.namelist() if "territory" in n.lower()]
print("861 members:", cand)
if cand:
    with z.open(cand[0]) as fh:
        terr = pd.read_excel(fh) if cand[0].endswith(".xlsx") else pd.read_csv(fh)
    print(terr.columns.tolist())
    ccol = next((c for c in terr.columns if "county" in str(c).lower()), None)
    t = terr[terr[ccol].astype(str).str.upper().str.contains(C.name_short.upper(), na=False)] if ccol else terr.iloc[0:0]
    scol = next((c for c in terr.columns if "state" in str(c).lower()), None)
    if scol: t = t[t[scol].astype(str).str.upper().str.startswith(C.st.upper())]
    print(f"utilities serving {C.name_short}:", len(t))
    print(t.to_string())
    stage_write(t, f"eia861_territory_{FIPS}.csv")

meta = {"retrieved_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "sources": {"generation": "EIA Form 860 (2024 annual, plant level)",
                    "territory": "EIA Form 861 (2024, service territory by county)"},
        "license": "public domain (US EIA)", "provenance": "observed"}
(OUT / "_meta.json").write_text(json.dumps(meta, indent=2))

# settle-and-heal (D-019 refined): the portal's async delete lands ~8 s after a
# verified write, so a 1 s re-check proves nothing. Recopy casualties from
# /tmp staging over 12 s rounds; require TWO consecutive stable rounds before
# exiting. Copies are shielded - a mid-copy portal ENOENT defers to next round.
import time as _time
_files = [f"eia860_plants_{FIPS}.csv", f"eia860_plants_{C.st}.csv"]
if cand:
    _files.append(f"eia861_territory_{FIPS}.csv")
print("settle-and-heal: watching for portal-mount drops ...", flush=True)
stable = 0
for _round in range(1, 21):
    _time.sleep(12)
    healed = []
    for fn in _files:
        out = OUT / fn
        if out.exists():
            continue
        staged = STAGE / fn
        if not staged.exists():
            continue
        try:
            shutil.copy2(staged, out)
            healed.append(fn)
        except OSError as e:
            print(f"  round {_round}: copy of {fn} deferred ({e})", flush=True)
    if not healed:
        stable += 1
        print(f"  round {_round}: stable ({stable}/2)")
        if stable >= 2:
            break
    else:
        stable = 0
        print(f"  round {_round}: healed dropped files: {healed}", flush=True)
missing = [fn for fn in _files if not (OUT / fn).exists()]
if missing:
    raise RuntimeError(f"outputs missing after heal phase: {missing}")
print("done")
