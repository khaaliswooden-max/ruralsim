#!/usr/bin/env python3
"""Parity check: OSM layers from Geofabrik clipping vs the committed Overpass layers (D-028).

    python3 tools/compare_osm.py 31173

Re-clips the county into a scratch directory from the Geofabrik extract and compares,
theme by theme, against worlds/<fips>_*/layers_raw/osm/ (the pilots' Overpass fetch).
Reports feature counts and the share of OSM ids in common. The two snapshots are days
apart, so small differences are OSM edits; a theme with under 95% shared ids, or one
that is empty on either side while the other is not, is a FLAG worth reading.
Exit code 1 if any theme flags.
"""
import json, pathlib, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import fetch_osm as fo  # noqa: E402
from county_config import get  # noqa: E402

THRESH = 0.95


def ids(path):
    if not path.exists():
        return None
    return {(f["properties"]["osm_type"], f["properties"]["osm_id"])
            for f in json.loads(path.read_text())["features"]}


def main():
    C = get(sys.argv[1] if len(sys.argv) > 1 else None)
    old_dir = C.world / "layers_raw" / "osm"
    with tempfile.TemporaryDirectory() as d:
        t = fo.Target(C.fips, C.buf_bbox, pathlib.Path(d), set(fo.THEMES))
        index = fo.geofabrik_index()
        regions = fo.extracts_for([(t.w, t.s, t.e, t.n)], index)
        prov = [fo.ensure_extract(r, 7.0) for r in regions]
        fo.extract([fo.CACHE / p["file"] for p in prov], [t])
        fo.Sink.finish(t)
        flags = 0
        print(f"{C.dir_name}: Geofabrik ({', '.join(p['region'] for p in prov)}) vs committed Overpass layers")
        print(f"{'theme':12s} {'overpass':>9s} {'geofabrik':>9s} {'shared':>7s}  status")
        for th in fo.THEMES:
            a, b = ids(old_dir / f"{th}.geojson"), ids(pathlib.Path(d) / f"{th}.geojson")
            if a is None:
                print(f"{th:12s} {'—':>9s} {len(b):9d} {'':>7s}  no committed layer")
                continue
            union = a | b
            shared = len(a & b) / len(union) if union else 1.0
            empty_mismatch = (len(a) == 0) != (len(b) == 0)
            status = "FLAG" if shared < THRESH or empty_mismatch else "ok"
            flags += status == "FLAG"
            print(f"{th:12s} {len(a):9d} {len(b):9d} {shared:7.1%}  {status}")
    sys.exit(1 if flags else 0)


if __name__ == "__main__":
    main()
