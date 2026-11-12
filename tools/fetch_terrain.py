#!/usr/bin/env python3
"""Fetch terrain (USGS 3DEP DEM) for a county.

Primary: TNM Access API, NED 1/3 arc-second (~10 m) GeoTIFF tiles. TNM returns
one item per vintage per tile; we keep the newest vintage of each 1x1-degree
tile covering the buffered bbox, read only the bbox window from each tile
(tiles are ~400 MB), merge, clip to the buffered county polygon, and write a
2x-downsampled float32 GeoTIFF for the repo plus a native clip in /tmp cache.

Fallback (D-021): if the TNM transfer crawls (<45 KB/s sustained, observed
2026-11-11 during a sandbox egress throttle), abort and instead window-read
USGS 3DEP 1 arc-second (~30 m) COGs from the Planetary Computer 3dep-seamless
collection — same USGS program, coarser resolution, same clip; payload stays
at native ~30 m and the filename records it (dem_<fips>_30m.tif).

Manifest layer: terrain. Provenance: observed (USGS 3DEP), public domain.
"""
import json, pathlib, re, time, urllib.request, urllib.parse, datetime, sys
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.features import geometry_mask
from shapely.geometry import mapping
import geopandas as gpd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from county_config import get
C = get(sys.argv[1] if len(sys.argv) > 1 else None)
FIPS = C.fips
W, S, E, N = C.buf_bbox  # county bbox + ~5 km buffer
REPO = pathlib.Path(__file__).resolve().parent.parent
ROOT = C.world
CACHE = pathlib.Path("/tmp/ruralsim_cache/terrain"); CACHE.mkdir(parents=True, exist_ok=True)
OUTDIR = ROOT / "layers" / "terrain"; OUTDIR.mkdir(parents=True, exist_ok=True)
if list(OUTDIR.glob(f"dem_{FIPS}_*.tif")):
    print(f"terrain: dem for {FIPS} already present, skipping (delete to re-fetch)")
    sys.exit(0)


class SlowLink(Exception):
    """Download throughput too low to be viable this session."""


def api(query):
    url = "https://tnmaccess.nationalmap.gov/api/v1/products?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={"User-Agent": "RuralSim-research/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def read_windows(paths_or_urls):
    """Windowed read of the buffered bbox from each tile; returns (arrays, transforms).

    The window MUST be intersected with the tile extent before reading:
    boundless=False silently clips an overhanging window, but window_transform()
    of the UNCLIPPED window then mis-anchors the clipped array — every
    partially-overlapping tile stamped its data at the wrong mosaic position
    and the mosaic collapsed to the last fully-inside tile (01131 DEM lost its
    southern ~26 km and eastern ~19 km, 2026-11-12; all five pilot DEMs were
    cropped wherever the buffer crosses a 1-degree tile edge)."""
    from rasterio.windows import Window
    win_arrays, win_transforms = [], []
    for p in paths_or_urls:
        with rasterio.open(p) as src:
            win = from_bounds(W, S, E, N, src.transform)
            full = Window(0, 0, src.width, src.height)
            win = win.intersection(full)
            if win is None:
                continue   # tile does not overlap the bbox at all
            win = win.round_offsets().round_lengths()
            a = src.read(1, window=win).astype("float32")
            wt = src.window_transform(win)   # transform of the CLIPPED window
            nd = src.nodata
            if nd is not None:
                a[a == nd] = np.nan
            win_arrays.append(a); win_transforms.append(wt)
    if not win_arrays:
        raise RuntimeError("no DEM tile overlapped the buffered bbox")
    return win_arrays, win_transforms


def fetch_tnm():
    """Whole-tile TNM download with a throughput probe. Returns
    (win_arrays, win_transforms, tiles_meta, source_note) or raises SlowLink."""
    res = api({"bbox": f"{W},{S},{E},{N}", "datasets": "National Elevation Dataset (NED) 1/3 arc-second",
               "prodFormats": "GeoTIFF", "max": 100, "outputFormat": "JSON"})
    items = res.get("items", [])

    # newest vintage per 1x1-degree tile
    best = {}
    for it in items:
        m = re.search(r"(n\d{2}w\d{3})", it.get("title", ""))
        if not m or not it.get("downloadURL"):
            continue
        key = m.group(1)
        if key not in best or (it.get("publicationDate") or "") > (best[key].get("publicationDate") or ""):
            best[key] = it
    print("tiles needed (newest vintage):", sorted(best))

    tiles_meta, paths = [], []
    for key in sorted(best):
        it = best[key]
        title = it.get("title", key)
        fn = CACHE / (title.replace("/", "_").replace(" ", "_") + ".tif")
        part = fn.with_suffix(".tif.part")
        if not fn.exists() or fn.stat().st_size == 0:
            print(f"  downloading {title} ...", flush=True)
            req = urllib.request.Request(it["downloadURL"], headers={"User-Agent": "RuralSim-research/0.1"})
            t0 = time.time(); got = 0
            try:
                with urllib.request.urlopen(req, timeout=1800) as r, open(part, "wb") as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk); got += len(chunk)
                        el = time.time() - t0
                        if el > 90 and got < 4_000_000:
                            raise SlowLink(f"{got/el/1024:.0f} KB/s sustained")
            except SlowLink:
                part.unlink(missing_ok=True)
                raise
            part.rename(fn)
        tiles_meta.append({"title": title, "url": it["downloadURL"],
                           "publicationDate": it.get("publicationDate"), "file": fn.name})
        paths.append(CACHE / fn.name)
        print(f"  have {fn.name} ({fn.stat().st_size/1e6:.0f} MB)")
    wa, wt = read_windows(paths)
    return wa, wt, tiles_meta, "USGS 3DEP National Elevation Dataset 1/3 arc-second (~10 m)"


def fetch_pc():
    """Windowed read of USGS 3DEP 1 arc-second COGs from Planetary Computer."""
    from pystac_client import Client
    import planetary_computer
    client = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
    search = client.search(collections=["3dep-seamless"], bbox=[W, S, E, N], limit=20)
    its = [it for it in search.items() if it.id.endswith("-1")]
    if not its:
        raise RuntimeError("PC 3dep-seamless: no 1 arc-second items over bbox")
    urls, tiles_meta = [], []
    for it in sorted(its, key=lambda i: i.id):
        signed = planetary_computer.sign(it)
        href = signed.assets["data"].href
        urls.append(href)
        tiles_meta.append({"title": f"PC 3dep-seamless {it.id}", "url": href.split("?")[0],
                           "publicationDate": it.datetime.date().isoformat() if it.datetime else None})
        print(f"  window-reading {it.id}")
    wa, wt = read_windows(urls)
    return wa, wt, tiles_meta, ("USGS 3DEP via Planetary Computer 3dep-seamless, 1 arc-second (~30 m) "
                                "— fallback during TNM egress throttle (D-021); source CRS EPSG:4269 "
                                "treated as 4326 (<2 m datum shift, below the ~30 m pixel)")


try:
    win_arrays, win_transforms, tiles_meta, source_note = fetch_tnm()
    SRC = "13"
except SlowLink as ex:
    print(f"TNM transfer too slow ({ex}); switching to Planetary Computer 1 arc-second (D-021)")
    win_arrays, win_transforms, tiles_meta, source_note = fetch_pc()
    SRC = "pc1"

print("window shapes:", [a.shape for a in win_arrays])

# mosaic: paste onto a common grid anchored at the finest/common resolution
res = win_transforms[0].a
x0 = min(t.c for t in win_transforms); y1 = max(t.f for t in win_transforms)
x1 = max(t.c + t.a * a.shape[1] for t, a in zip(win_transforms, win_arrays))
y0 = min(t.f + t.e * a.shape[0] for t, a in zip(win_transforms, win_arrays))
H = int(round((y1 - y0) / abs(res))); Wd = int(round((x1 - x0) / res))
mos = np.full((H, Wd), np.nan, dtype="float32")
for a, t in zip(win_arrays, win_transforms):
    r0 = int(round((y1 - t.f) / abs(res))); c0 = int(round((t.c - x0) / res))
    sub = mos[r0:r0 + a.shape[0], c0:c0 + a.shape[1]]
    mos[r0:r0 + a.shape[0], c0:c0 + a.shape[1]] = np.where(np.isnan(sub), a, np.fmax(sub, a))
transform = rasterio.Affine(res, 0, x0, 0, -abs(res), y1)

geom = C.geom.buffer(0.062)  # pilot or any county, from county_config
m = geometry_mask([mapping(geom)], out_shape=(H, Wd), transform=transform, invert=True)
clip = np.where(m, mos, np.nan).astype("float32")

native_tif = CACHE / f"dem_{FIPS}_native_clip.tif"
with rasterio.open(native_tif, "w", driver="GTiff", height=H, width=Wd, count=1,
                   dtype="float32", crs="EPSG:4326", transform=transform,
                   nodata=np.nan, compress="deflate") as dst:
    dst.write(clip, 1)

if SRC == "13":
    # 1/3 arc-second native: 2x block-mean to the standard ~20 m payload
    h2, w2 = H // 2, Wd // 2
    c = clip[:h2*2, :w2*2].reshape(h2, 2, w2, 2)
    with np.errstate(invalid="ignore"):
        small = np.nanmean(c, axis=(1, 3)).astype("float32")
    t2 = rasterio.Affine(transform.a * 2, 0, transform.c, 0, transform.e * 2, transform.f)
    out_res_m = 20
else:
    # 1 arc-second fallback: payload stays at native ~30 m (no upsampling)
    small, t2 = clip, transform
    out_res_m = 30

out_tif = OUTDIR / f"dem_{FIPS}_{out_res_m}m.tif"
with rasterio.open(out_tif, "w", driver="GTiff", height=small.shape[0], width=small.shape[1], count=1,
                   dtype="float32", crs="EPSG:4326", transform=t2,
                   nodata=np.nan, compress="deflate") as dst:
    dst.write(small, 1)

valid = small[~np.isnan(small)]
meta = {"retrieved_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "source": source_note,
        "license": "public domain", "provenance": "observed", "tiles": tiles_meta,
        "native_clip_cache": str(native_tif),
        "output": {"file": f"layers/terrain/{out_tif.name}", "shape": list(small.shape),
                   "resolution_m": out_res_m, "crs": "EPSG:4326",
                   "elev_min_m": round(float(valid.min()), 1),
                   "elev_max_m": round(float(valid.max()), 1)}}
(OUTDIR / "_meta.json").write_text(json.dumps(meta, indent=2))
print("wrote", out_tif, f"elev {valid.min():.0f}-{valid.max():.0f} m, grid {small.shape[0]}x{small.shape[1]}")
