#!/usr/bin/env python3
"""Fetch OSM layers from Geofabrik state extracts, clipped locally (D-028).

    python3 tools/fetch_osm.py 31173                  # one county, all themes
    python3 tools/fetch_osm.py 31173 roads buildings  # selected themes
    python3 tools/fetch_osm.py --state NE             # every 2024-vintage county in a state,
                                                      # one pass per extract
    python3 tools/fetch_osm.py 31173 --force          # rebuild themes already present
    python3 tools/fetch_osm.py 31173 --source overpass  # legacy Overpass path (D-022)

Replaces live Overpass queries, which failed for whole days during the pilot builds
(D-018, D-022). Each U.S. state extract is downloaded once into the shared cache
($RURALSIM_CACHE, default /tmp/ruralsim_cache), verified against Geofabrik's .md5,
and every county is clipped from it on the local machine. A county whose buffered
bbox crosses a state line reads every extract that touches it, so border features
are not lost; features seen in two extracts are written once.

Output is byte-compatible in schema with the Overpass fetcher: one GeoJSON per theme
in layers_raw/osm/, EPSG:4326, properties {osm_type, osm_id, **tags}; closed ways are
Polygons only when tagged building or area=yes; relations become MultiPolygons of
their outer rings. Selection semantics match the Overpass queries (same keys, same
unanchored value regexes); see THEMES. Known difference: Overpass also returns a
relation when only a member *node* lies in the bbox; here a relation is kept when an
outer member way touches the bbox. Building and multipolygon relations, the only
relations the GeoJSON keeps, are matched the same way by both.

Provenance: observed (OpenStreetMap, ODbL 1.0). The extract URL, md5 and replication
timestamp are recorded in layers_raw/osm/_meta.json so a build can name its snapshot.
"""
from __future__ import annotations

import argparse, csv, datetime, hashlib, json, math, os, pathlib, re, subprocess, sys, time
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

GEOFABRIK_INDEX = "https://download.geofabrik.de/index-v1.json"
CACHE = pathlib.Path(os.environ.get("RURALSIM_CACHE", "/tmp/ruralsim_cache")) / "osm"
_US_STATE_PBF = re.compile(r"https://download\.geofabrik\.de/north-america/us/[a-z-]+-latest\.osm\.pbf")
UA = {"User-Agent": "RuralSim/1.0 (+https://www.ruralsim.io; county twin build)"}
INDEX_STORAGE = os.environ.get("RURALSIM_OSM_INDEX", "flex_mem")  # node-location index type

# --------------------------------------------------------------------------- themes
# Mirrors the Overpass queries in fetch_osm_overpass.py exactly:
#   key presence  -> `in tags`;  ["k"="v"] -> equality;  ["k"~"re"] -> unanchored re.search
KEYS = ["highway", "building", "amenity", "healthcare", "power", "place",
        "man_made", "waterway", "shop"]
THEMES = ["roads", "buildings", "schools", "healthcare", "power", "places",
          "water", "waterways", "food_shops", "bridges"]
_HC = re.compile("hospital|clinic|doctors")
_FOOD = re.compile("supermarket|grocery|convenience|general")


def themes_for(kind: str, tags: dict) -> list[str]:
    """kind: 'n' | 'w' | 'r'. Returns the themes this object belongs to."""
    out = []
    a = tags.get("amenity")
    if kind == "w" and "highway" in tags:
        out.append("roads")
    if kind in ("w", "r") and "building" in tags:
        out.append("buildings")
    if a in ("school", "college"):
        out.append("schools")
    if (a is not None and _HC.search(a)) or "healthcare" in tags:
        out.append("healthcare")
    if "power" in tags:
        out.append("power")
    if kind == "n" and "place" in tags:
        out.append("places")
    if tags.get("man_made") == "water_tower" or a == "drinking_water":
        out.append("water")
    if kind == "w" and "waterway" in tags:
        out.append("waterways")
    s = tags.get("shop")
    if s is not None and _FOOD.search(s):
        out.append("food_shops")
    if kind == "w" and tags.get("bridge") == "yes" and "highway" in tags:
        out.append("bridges")
    return out


# --------------------------------------------------------------------------- targets
class Target:
    """One county to write: buffered bbox and output directory."""

    def __init__(self, fips: str, buf_bbox: tuple, out_dir: pathlib.Path, themes: set[str]):
        self.fips = fips
        self.w, self.s, self.e, self.n = buf_bbox
        self.out = out_dir
        self.themes = themes
        from shapely.geometry import box
        self.box = box(self.w, self.s, self.e, self.n)

    @property
    def bbox_overpass(self) -> str:  # s,w,n,e — same string the Overpass fetcher recorded
        return f"{self.s},{self.w},{self.n},{self.e}"

    def contains(self, lon, lat) -> bool:
        return self.w <= lon <= self.e and self.s <= lat <= self.n

    def overlaps(self, w, s, e, n) -> bool:
        return not (e < self.w or w > self.e or n < self.s or s > self.n)


CELL = 0.5  # degrees; spatial hash cell for target lookup


def _cells(w, s, e, n):
    for ix in range(math.floor(w / CELL), math.floor(e / CELL) + 1):
        for iy in range(math.floor(s / CELL), math.floor(n / CELL) + 1):
            yield ix, iy


class TargetIndex:
    def __init__(self, targets: list[Target]):
        self.targets = targets
        self.grid: dict[tuple, list[Target]] = {}
        for t in targets:
            for c in _cells(t.w, t.s, t.e, t.n):
                self.grid.setdefault(c, []).append(t)

    def for_point(self, lon, lat):
        c = (math.floor(lon / CELL), math.floor(lat / CELL))
        return [t for t in self.grid.get(c, ()) if t.contains(lon, lat)]

    def for_line(self, coords):
        """Targets a polyline touches: any vertex inside, else a segment crossing the bbox."""
        lons = [p[0] for p in coords]; lats = [p[1] for p in coords]
        w, s, e, n = min(lons), min(lats), max(lons), max(lats)
        cells = list(_cells(w, s, e, n))
        if len(cells) > 400:
            cands = self.targets
        else:
            seen, cands = set(), []
            for c in cells:
                for t in self.grid.get(c, ()):
                    if id(t) not in seen:
                        seen.add(id(t)); cands.append(t)
        hits = []
        for t in cands:
            if not t.overlaps(w, s, e, n):
                continue
            if any(t.contains(x, y) for x, y in coords):
                hits.append(t)
            elif len(coords) >= 2:
                from shapely.geometry import LineString
                if t.box.intersects(LineString(coords)):
                    hits.append(t)
        return hits


# --------------------------------------------------------------------------- output
class Sink:
    """Buffers serialized features per (county, theme); flushes to part files so a
    whole-state pass never holds the state's buildings in memory."""

    FLUSH_LINES = 200_000

    def __init__(self):
        self.buf: dict[tuple, list[str]] = {}
        self.n = 0

    def add(self, t: Target, theme: str, key: str, feature: dict):
        if theme not in t.themes:
            return
        self.buf.setdefault((t, theme), []).append(key + "\t" + json.dumps(feature, separators=(",", ":")))
        self.n += 1
        if self.n >= self.FLUSH_LINES:
            self.flush()

    def flush(self):
        for (t, theme), lines in self.buf.items():
            parts = t.out / ".osm_parts"
            parts.mkdir(parents=True, exist_ok=True)
            with open(parts / f"{theme}.part", "a") as fh:
                fh.write("\n".join(lines) + "\n")
        self.buf.clear()
        self.n = 0

    @staticmethod
    def finish(t: Target) -> dict[str, int]:
        """Assemble each requested theme into a FeatureCollection (deduped by osm type+id)."""
        counts = {}
        parts = t.out / ".osm_parts"
        for theme in sorted(t.themes):
            pf = parts / f"{theme}.part"
            seen, feats = set(), []
            if pf.exists():
                for line in pf.read_text().splitlines():
                    if not line:
                        continue
                    key, js = line.split("\t", 1)
                    if key not in seen:
                        seen.add(key); feats.append(js)
            dst = t.out / f"{theme}.geojson"
            tmp = dst.with_suffix(".geojson.tmp")
            tmp.write_text('{"type":"FeatureCollection","features":[' + ",".join(feats) + "]}")
            os.replace(tmp, dst)
            counts[theme] = len(feats)
        if parts.exists():
            for p in parts.iterdir():
                p.unlink()
            parts.rmdir()
        return counts


def _feature(kind: str, oid: int, tags: dict, geom: dict) -> dict:
    return {"type": "Feature", "geometry": geom,
            "properties": {"osm_type": {"n": "node", "w": "way", "r": "relation"}[kind],
                           "osm_id": oid, **tags}}


def _way_geom(coords, tags):
    closed = len(coords) > 2 and coords[0] == coords[-1]
    is_area = closed and ("building" in tags or tags.get("area") == "yes")
    return {"type": "Polygon" if is_area else "LineString",
            "coordinates": [coords] if is_area else coords}


def _r7(v):
    return round(v, 7)


# --------------------------------------------------------------------------- extraction
def extract(pbfs: list[pathlib.Path], targets: list[Target]) -> None:
    """Clip every pbf to every target. Writes nothing final; call Sink.finish per target."""
    import osmium
    import osmium.filter as of

    idx = TargetIndex(targets)
    sink = Sink()
    for pbf in pbfs:
        t0 = time.time()
        print(f"  reading {pbf.name} ...", flush=True)

        # pass 1: theme relations and their outer member ways
        rels = []                      # (id, tags, [way refs])
        need_ways: set[int] = set()
        for r in osmium.FileProcessor(str(pbf), osmium.osm.RELATION).with_filter(of.KeyFilter(*KEYS)):
            tags = {t.k: t.v for t in r.tags}
            th = themes_for("r", tags)
            if not th:
                continue
            outers = [m.ref for m in r.members if m.type == "w" and m.role == "outer"]
            if outers:
                rels.append((r.id, tags, th, outers))
                need_ways.update(outers)

        # pass 2: themed nodes and ways (location index sees every node before the filter)
        way_coords: dict[int, list] = {}
        fp = (osmium.FileProcessor(str(pbf), osmium.osm.NODE | osmium.osm.WAY)
              .with_locations(INDEX_STORAGE).with_filter(of.KeyFilter(*KEYS)))
        for o in fp:
            if o.is_node():
                tags = {t.k: t.v for t in o.tags}
                th = themes_for("n", tags)
                if not th or not o.location.valid():
                    continue
                lon, lat = _r7(o.location.lon), _r7(o.location.lat)
                hits = idx.for_point(lon, lat)
                if hits:
                    f = _feature("n", o.id, tags, {"type": "Point", "coordinates": [lon, lat]})
                    for t in hits:
                        for theme in th:
                            sink.add(t, theme, f"n{o.id}", f)
            elif o.is_way():
                coords = [[_r7(n.lon), _r7(n.lat)] for n in o.nodes if n.location.valid()]
                if o.id in need_ways:
                    way_coords[o.id] = coords
                tags = {t.k: t.v for t in o.tags}
                th = themes_for("w", tags)
                if not th or len(coords) < 2:
                    continue
                hits = idx.for_line(coords)
                if hits:
                    f = _feature("w", o.id, tags, _way_geom(coords, tags))
                    for t in hits:
                        for theme in th:
                            sink.add(t, theme, f"w{o.id}", f)

        # pass 3: untagged member ways of theme relations (building/multipolygon outers)
        missing = need_ways - way_coords.keys()
        if missing:
            fp = (osmium.FileProcessor(str(pbf), osmium.osm.NODE | osmium.osm.WAY)
                  .with_locations(INDEX_STORAGE).with_filter(of.IdFilter(missing)))
            for o in fp:
                if o.is_way() and o.id in missing:
                    way_coords[o.id] = [[_r7(n.lon), _r7(n.lat)] for n in o.nodes if n.location.valid()]

        for rid, tags, th, outers in rels:
            rings = [way_coords[w] for w in outers if len(way_coords.get(w, ())) >= 2]
            if not rings:
                continue
            hits = {id(t): t for ring in rings for t in idx.for_line(ring)}.values()
            if hits:
                f = _feature("r", rid, tags, {"type": "MultiPolygon", "coordinates": [[r] for r in rings]})
                for t in hits:
                    for theme in th:
                        sink.add(t, theme, f"r{rid}", f)
        sink.flush()
        print(f"  {pbf.name}: done in {time.time() - t0:.0f} s", flush=True)


# --------------------------------------------------------------------------- downloads
def _download(url: str, dest: pathlib.Path, timeout=3600):
    part = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r, open(part, "wb") as fh:
        while chunk := r.read(1 << 20):
            fh.write(chunk)
    os.replace(part, dest)


def _md5(path: pathlib.Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 22):
            h.update(chunk)
    return h.hexdigest()


def geofabrik_index() -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / "index-v1.json"
    if not p.exists() or time.time() - p.stat().st_mtime > 30 * 86400:
        _download(GEOFABRIK_INDEX, p, timeout=300)
    feats = json.loads(p.read_text())["features"]
    # A state is any region whose extract sits exactly one level under
    # /north-america/us/ (California's norcal/socal sub-extracts sit deeper and are
    # skipped, so California downloads once). Matching on the URL, not `parent`,
    # because the index's parent field did not identify the states (2026-11-15).
    states = [f for f in feats if f.get("geometry")
              and _US_STATE_PBF.fullmatch(f["properties"].get("urls", {}).get("pbf", ""))]
    if len(states) < 50:
        raise RuntimeError(f"Geofabrik index lists only {len(states)} U.S. state extracts "
                           f"(expected 50 + DC); delete {p} and rerun, or check the index format")
    return states


def extracts_for(bboxes: list[tuple], index: list[dict]) -> list[dict]:
    """Geofabrik U.S. regions whose outline touches any of the bboxes."""
    from shapely.geometry import box, shape
    boxes = [box(*b) for b in bboxes]
    out = []
    for f in index:
        g = shape(f["geometry"])
        if any(g.intersects(b) for b in boxes):
            out.append(f["properties"])
    if not out:
        raise RuntimeError("no Geofabrik U.S. extract covers this area")
    return out


def _covering(t: "Target", prov: list[dict], index: list[dict]) -> list[dict]:
    """The subset of downloaded extracts whose outline touches this target."""
    from shapely.geometry import shape
    geoms = {f["properties"]["id"]: shape(f["geometry"]) for f in index}
    return [p for p in prov if p["region"] in geoms and geoms[p["region"]].intersects(t.box)]


# R2 mirror of the state extracts (D-036). In the canary run (43794676050) ten county jobs
# downloading from Geofabrik at once were refused ("Network is unreachable") for 7 of 57
# counties. The plan job now copies each needed extract to R2 once, serially
# (tools/mirror_osm.py), and county jobs read it from there; Geofabrik is the fallback.
# Read through the S3 API when R2 credentials are present (no rate limit; r2.dev public
# URLs are throttled), else over HTTP from RURALSIM_OSM_MIRROR if set.
OSM_MIRROR = os.environ.get("RURALSIM_OSM_MIRROR", "").rstrip("/")
OSM_MIRROR_PREFIX = "osm/"


def _r2_ready() -> bool:
    return all(os.environ.get(k) for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID",
                                           "R2_SECRET_ACCESS_KEY", "R2_BUCKET"))


def _mirror_get(name: str, dest: pathlib.Path) -> bool:
    """Fetch one mirrored file (extract or its .md5); False if the mirror lacks it."""
    if _r2_ready():
        from publish_world import bucket, client
        part = dest.with_suffix(dest.suffix + ".part")
        for attempt in range(3):
            try:
                client().download_file(bucket(), OSM_MIRROR_PREFIX + name, str(part))
                os.replace(part, dest)
                return True
            except Exception as e:
                if "404" in str(e) or "Not Found" in str(e):
                    return False  # not mirrored: go straight to Geofabrik
                print(f"    R2 mirror attempt {attempt + 1} for {name} failed: {e}", file=sys.stderr)
                time.sleep(15 * (attempt + 1))
        return False
    if OSM_MIRROR:
        return _fetch_with_retry(f"{OSM_MIRROR}/{name}", dest, 3, 20)
    return False


def _fetch_with_retry(url: str, dest: pathlib.Path, tries: int, wait: int, timeout=3600) -> bool:
    for attempt in range(tries):
        try:
            _download(url, dest, timeout=timeout)
            return True
        except Exception as e:
            print(f"    attempt {attempt + 1} of {tries} for {url} failed: {e}", file=sys.stderr)
            if attempt + 1 < tries:
                time.sleep(wait * (attempt + 1))
    return False


def ensure_extract(props: dict, max_age_days: float) -> dict:
    """Download (or reuse) one state extract; verify md5; return its provenance."""
    url = props["urls"]["pbf"]
    dest = CACHE / pathlib.Path(url).name
    md5_path = dest.with_name(dest.name + ".md5")
    fresh = dest.exists() and time.time() - dest.stat().st_mtime < max_age_days * 86400
    source = url
    if not fresh and (OSM_MIRROR or _r2_ready()):
        print(f"  downloading {dest.name} from the R2 mirror ...", flush=True)
        if _mirror_get(dest.name + ".md5", md5_path) and _mirror_get(dest.name, dest):
            fresh, source = True, f"r2:{OSM_MIRROR_PREFIX}{dest.name}"
        else:
            print("    mirror unavailable; falling back to Geofabrik", file=sys.stderr)
            md5_path.unlink(missing_ok=True)
    if not fresh:
        print(f"  downloading {url} ...", flush=True)
        if not _fetch_with_retry(url, dest, 5, 60):
            raise RuntimeError(f"could not download {url}")
    if source == url and (not fresh or not md5_path.exists()):
        if not _fetch_with_retry(url + ".md5", md5_path, 5, 30, timeout=120):
            raise RuntimeError(f"could not download {url}.md5")
    want = md5_path.read_text().split()[0]
    got = _md5(dest)
    if got != want:
        dest.unlink()
        raise RuntimeError(f"md5 mismatch for {dest.name} (got {got}, want {want}); deleted, rerun")
    return {"region": props["id"], "url": url, "file": dest.name, "md5": got,
            **({"fetched_from": source} if source != url else {}),
            "replication_timestamp": _replication_ts(dest)}


def _replication_ts(path: pathlib.Path):
    try:
        import osmium
        r = osmium.io.Reader(str(path), osmium.osm.osm_entity_bits.NOTHING)
        ts = r.header().get("osmosis_replication_timestamp")
        r.close()
        return ts or None
    except Exception:
        return None


# --------------------------------------------------------------------------- driver
def _state_counties(st: str) -> list[str]:
    with open(REPO / "data" / "county_master.csv", newline="") as fh:
        return [r["fips5"] for r in csv.DictReader(fh)
                if r.get("geography_vintage") == "2024" and r.get("state_abbr") == st.upper()]


def write_meta(t: Target, counts: dict, extracts: list[dict], empty: list[str]):
    metaf = t.out / "_meta.json"
    old = json.loads(metaf.read_text()) if metaf.exists() else {}
    themes = old.get("themes", {}) if old.get("source", "").startswith("OpenStreetMap via Geofabrik") else {}
    themes.update({k: {"features": v, "file": f"{k}.geojson"} for k, v in counts.items()})
    meta = {
        "retrieved_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": "OpenStreetMap via Geofabrik state extract(s), clipped locally (pyosmium)",
        "license": "ODbL 1.0", "provenance": "observed",
        "bbox_buffered": t.bbox_overpass,
        "extracts": extracts,
        "selection": "same keys and value regexes as the Overpass queries (fetch_osm_overpass.py); D-028",
        "themes": themes,
    }
    if empty:
        meta["suspect_empty"] = empty
    tmp = metaf.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, indent=2))
    os.replace(tmp, metaf)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("args", nargs="*", help="fips5 and/or theme names")
    ap.add_argument("--state", help="process every 2024-vintage county in this state (e.g. NE)")
    ap.add_argument("--force", action="store_true", help="rebuild themes that already exist")
    ap.add_argument("--max-age-days", type=float, default=7.0,
                    help="reuse a cached extract younger than this (default 7)")
    ap.add_argument("--source", choices=["geofabrik", "overpass"], default="geofabrik")
    a = ap.parse_args(argv)

    fips_args = [x for x in a.args if x.isdigit()]
    only = {x for x in a.args if not x.isdigit()}
    bad = only - set(THEMES)
    if bad:
        ap.error(f"unknown theme(s): {sorted(bad)}; known: {THEMES}")

    if a.source == "overpass":
        if a.state:
            ap.error("--source overpass works one county at a time")
        cmd = [sys.executable, str(REPO / "tools" / "fetch_osm_overpass.py"), *a.args]
        sys.exit(subprocess.call(cmd))

    from county_config import get
    fipses = _state_counties(a.state) if a.state else (fips_args or [None])
    if a.state and not fipses:
        ap.error(f"no 2024-vintage counties found for state {a.state}")

    targets = []
    for f in fipses:
        C = get(f)
        out = C.world / "layers_raw" / "osm"
        out.mkdir(parents=True, exist_ok=True)
        want = set(only or THEMES)
        if not a.force:
            present = {th for th in want if (out / f"{th}.geojson").exists()}
            for th in sorted(present):
                print(f"  {C.fips} {th}: already present, skipping")
            want -= present
        if want:
            # stale parts from an interrupted run would duplicate nothing (dedupe) but
            # could carry features from an older extract; start clean
            parts = out / ".osm_parts"
            if parts.exists():
                for p in parts.iterdir():
                    p.unlink()
            targets.append(Target(C.fips, C.buf_bbox, out, want))
    if not targets:
        print("nothing to do.")
        return

    index = geofabrik_index()
    regions = extracts_for([(t.w, t.s, t.e, t.n) for t in targets], index)
    print(f"{len(targets)} county target(s); extract(s): {', '.join(r['id'] for r in regions)}")
    prov = [ensure_extract(r, a.max_age_days) for r in regions]
    extract([CACHE / p["file"] for p in prov], targets)

    failed = []
    for t in targets:
        counts = Sink.finish(t)
        empty = sorted(th for th, n in counts.items() if n == 0)
        # D-018: an unexpectedly empty layer is suspect, not ground truth. Every county
        # has mapped roads; zero means the clip or the extract is wrong.
        write_meta(t, counts, _covering(t, prov, index) or prov, empty)
        print(f"  {t.fips}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
        if counts.get("roads", 1) == 0:
            failed.append(t.fips)
    if failed:
        raise SystemExit(f"FAILED: zero roads clipped for {', '.join(failed)} — suspect extract or bbox (D-018)")
    print("done.")


if __name__ == "__main__":
    main()
