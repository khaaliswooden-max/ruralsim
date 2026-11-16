#!/usr/bin/env python3
"""Regenerate data/geofabrik_us_index.json from Geofabrik's index-v1.json (D-040).

    python3 tools/refresh_geofabrik_index.py            # downloads the index
    python3 tools/refresh_geofabrik_index.py index-v1.json

Keeps the U.S. state extracts only (URL one level under /north-america/us/), buffers each
outline 0.02 deg outward and simplifies it by 0.02 deg, so state selection stays a
superset of the true outline while the file stays ~60 KB. Run on a machine that can reach
download.geofabrik.de; GitHub's runners sometimes cannot.
"""
import json, pathlib, re, sys, urllib.request

from shapely.geometry import mapping, shape

REPO = pathlib.Path(__file__).resolve().parent.parent
URL = "https://download.geofabrik.de/index-v1.json"
PAT = re.compile(r"https://download\.geofabrik\.de/north-america/us/[a-z-]+-latest\.osm\.pbf")


def _round(c):
    return [_round(x) for x in c] if isinstance(c[0], (list, tuple)) else [round(c[0], 3), round(c[1], 3)]


def main(src=None):
    if src:
        d = json.loads(pathlib.Path(src).read_text())
    else:
        req = urllib.request.Request(URL, headers={"User-Agent": "RuralSim/1.0 (+https://www.ruralsim.io)"})
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.load(r)
    out = []
    for f in d["features"]:
        u = f["properties"].get("urls", {}).get("pbf", "")
        if f.get("geometry") and PAT.fullmatch(u):
            g = mapping(shape(f["geometry"]).buffer(0.02).simplify(0.02, preserve_topology=True))
            g = json.loads(json.dumps(g))
            g["coordinates"] = _round(g["coordinates"])
            out.append({"type": "Feature", "geometry": g,
                        "properties": {"id": f["properties"]["id"], "name": f["properties"].get("name"),
                                       "urls": {"pbf": u}}})
    if len(out) < 51:
        raise SystemExit(f"only {len(out)} U.S. state extracts found; not writing")
    p = REPO / "data" / "geofabrik_us_index.json"
    p.write_text(json.dumps({"type": "FeatureCollection",
                             "note": "Geofabrik index-v1.json, U.S. states only, geometry buffered "
                                     "0.02 deg and simplified 0.02 deg (D-040)",
                             "features": out}, separators=(",", ":")))
    print(f"wrote {p} with {len(out)} extracts")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
