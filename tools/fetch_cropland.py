#!/usr/bin/env python3
"""USDA Cropland Data Layer for a pilot county.

Manifest layers: crops (primary) and land_cover (fallback: NLCD unreachable -
mrlc.gov blocked; CDL includes all non-crop classes, so it doubles as land
cover; DECISIONS D-011).

Sources, in order:
1. CropScape GetCDLFile (nassgeodata.gmu.edu) - manifest source, latest year.
   NOTE: the service began returning 404 for all API paths on 2026-11-11.
2. Planetary Computer usda-cdl ('cropland_*' items, 'cropland' asset = full
   CDL classes; 'cultivated_*' items are a derived mask - do not use those).
   PC coverage ends at 2021 - vintage recorded in _meta.json.

Clipped to buffered county bbox. Provenance: observed (USDA NASS CDL).
"""
import json, pathlib, urllib.request, re, datetime, sys
import numpy as np
import rasterio
from rasterio.windows import from_bounds
import pyproj

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from county_config import get
C = get(sys.argv[1] if len(sys.argv) > 1 else None)
FIPS = C.fips
W, S, E, N = C.buf_bbox
OUT = C.world / "layers" / "land_cover"
OUT.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "RuralSim-research/0.1"}

existing = list(OUT.glob(f"cdl_{FIPS}_*.tif"))
if existing:
    print(f"land_cover: {existing[0].name} already present, skipping (delete to re-fetch)")
    sys.exit(0)

CDL_NAMES = {1: "corn", 5: "soybeans", 176: "grass/pasture", 141: "deciduous forest",
             36: "alfalfa", 121: "developed/open", 122: "developed/low",
             195: "herbaceous wetlands", 190: "woody wetlands", 111: "open water",
             2: "cotton", 3: "rice", 4: "sorghum", 6: "sunflower", 22: "durum wheat",
             23: "spring wheat", 26: "dbl crop winwht/soybeans", 27: "rye", 28: "oats",
             37: "other hay", 42: "dry beans", 43: "potatoes", 52: "other crops",
             61: "fallow/idle", 131: "barren", 21: "barley", 24: "winter wheat",
             25: "other small grains",
             142: "evergreen forest", 143: "mixed forest", 152: "shrubland"}

def write_and_meta(arr, crs, transform, year, source):
    out = OUT / f"cdl_{FIPS}_{year}.tif"
    with rasterio.open(out, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1],
                       count=1, dtype="uint8", crs=crs, transform=transform,
                       nodata=0, compress="deflate") as dst:
        dst.write(arr, 1)
    vals, counts = np.unique(arr[arr > 0], return_counts=True)
    order = np.argsort(-counts)[:12]
    top = {str(int(vals[i])): CDL_NAMES.get(int(vals[i]), f"class {int(vals[i])}") for i in order}
    meta = {"retrieved_utc": datetime.datetime.now(datetime.UTC).isoformat(),
            "source": source, "license": "public domain (USDA)", "provenance": "observed",
            "also_serves": "land_cover (NLCD deferred - MRLC unreachable; CDL includes all non-crop classes; DECISIONS D-011)",
            "output": {"file": f"layers/land_cover/{out.name}", "year": year,
                       "crs": str(crs), "resolution_m": 30, "shape": list(arr.shape)},
            "top_classes": top}
    (OUT / "_meta.json").write_text(json.dumps(meta, indent=2))
    print("wrote", out.name, arr.shape, "| top classes:", top)

# --- 1. CropScape ---
to5070 = pyproj.Transformer.from_crs(4326, 5070, always_xy=True)
x1, y1 = to5070.transform(W, S); x2, y2 = to5070.transform(E, N)
bbox5070 = f"{int(min(x1,x2))},{int(min(y1,y2))},{int(max(x1,x2))},{int(max(y1,y2))}"
try:
    api = ("https://nassgeodata.gmu.edu/webservice/nass_data_cache.php?service=CDL"
           f"&request=GetCDLFile&year=2023&format=geotiff&bbox={bbox5070}")
    req = urllib.request.Request(api, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = r.read().decode()
    m = re.search(r"https?://[^\s<>\"']+\.tif", resp)
    if not m:
        raise RuntimeError(f"no tif URL in response: {resp[:200]}")
    tmp = pathlib.Path(f"/tmp/ruralsim_cache/cdl_{FIPS}_2023.tif")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(m.group(0), headers=UA)
    with urllib.request.urlopen(req, timeout=900) as r, open(tmp, "wb") as f:
        while True:
            c = r.read(1 << 20)
            if not c: break
            f.write(c)
    with rasterio.open(tmp) as src:
        arr, crs, transform = src.read(1), src.crs, src.transform
    write_and_meta(arr, crs, transform, 2023,
                   "USDA NASS Cropland Data Layer 2023 via CropScape GetCDLFile (nassgeodata.gmu.edu)")
    sys.exit(0)
except Exception as e:
    print(f"CropScape unavailable ({e}); falling back to Planetary Computer usda-cdl 2021", file=sys.stderr)

# --- 2. Planetary Computer ---
from pystac_client import Client
import planetary_computer
cat = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
items = [it for it in cat.search(collections=["usda-cdl"], bbox=[W, S, E, N]).items()
         if it.id.startswith("cropland_")]
years = sorted({int(it.id.split("_")[1]) for it in items})
year = max(years)
tiles = [it for it in items if int(it.id.split("_")[1]) == year]
print(f"PC usda-cdl: year {year}, {len(tiles)} tile(s) cover buffered bbox")

X1, Y1 = to5070.transform(W, S); X2, Y2 = to5070.transform(E, N)
win_arrays, win_transforms = [], []
for it in tiles:
    href = planetary_computer.sign(it).assets["cropland"].href
    with rasterio.open(href) as src:
        win = from_bounds(min(X1, X2), min(Y1, Y2), max(X1, X2), max(Y1, Y2), src.transform)
        win = win.round_offsets().round_lengths()
        win_arrays.append(src.read(1, window=win))
        win_transforms.append(src.window_transform(win))

res = win_transforms[0].a
x0 = min(t.c for t in win_transforms); y1m = max(t.f for t in win_transforms)
x1m = max(t.c + t.a * a.shape[1] for t, a in zip(win_transforms, win_arrays))
y0m = min(t.f + t.e * a.shape[0] for t, a in zip(win_transforms, win_arrays))
H = int(round((y1m - y0m) / abs(res))); Wd = int(round((x1m - x0) / res))
mos = np.zeros((H, Wd), dtype="uint8")
for a, t in zip(win_arrays, win_transforms):
    r0 = int(round((y1m - t.f) / abs(res))); c0 = int(round((t.c - x0) / res))
    sub = mos[r0:r0 + a.shape[0], c0:c0 + a.shape[1]]
    mos[r0:r0 + a.shape[0], c0:c0 + a.shape[1]] = np.where(sub == 0, a, sub)
transform = rasterio.Affine(res, 0, x0, 0, -abs(res), y1m)
write_and_meta(mos, "EPSG:5070", transform, year,
               f"USDA NASS Cropland Data Layer {year} via Microsoft Planetary Computer (STAC: usda-cdl, 'cropland' asset)")
