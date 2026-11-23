"""FeatureCollections written one feature per line, read one feature at a time (D-067).

fetch_osm writes every theme as

    {"type":"FeatureCollection","features":[
    {feature},
    {feature}
    ]}

which is still one valid GeoJSON document, but a reader can stream it line by line
instead of holding the whole collection in memory. Los Angeles's buffered bbox holds
millions of OSM buildings: as one json.loads it outgrew a 16 GB runner (build 47, 49).
Files in the older single-line layout are read whole, as before.
"""
from __future__ import annotations

import json, pathlib

HEAD = '{"type":"FeatureCollection","features":[\n'
TAIL = "\n]}\n"


def write(path: pathlib.Path, features_json) -> int:
    """Write already-serialized features (an iterable of JSON strings); returns the count."""
    n = 0
    with open(path, "w") as fh:
        fh.write(HEAD)
        for js in features_json:
            if n:
                fh.write(",\n")
            fh.write(js)
            n += 1
        fh.write(TAIL)
    return n


def iter_features(path: pathlib.Path):
    """Yield each feature dict, streaming the line layout; whole-file for the old one."""
    with open(path) as fh:
        first = fh.readline()
        if first == HEAD:
            for line in fh:
                line = line.rstrip("\n")
                if line.endswith(","):
                    line = line[:-1]
                if line.startswith("{"):
                    yield json.loads(line)
            return
        rest = fh.read()
    yield from json.loads(first + rest).get("features", [])
