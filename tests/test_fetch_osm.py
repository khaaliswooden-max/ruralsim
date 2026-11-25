#!/usr/bin/env python3
"""Offline test for tools/fetch_osm.py extraction semantics (D-028).

    python3 tests/test_fetch_osm.py

Builds two tiny OSM XML "state extracts" that overlap at a shared border, clips them
to two county targets, and checks the behaviors the stage builder depends on:
theme selection identical to the Overpass queries, way geometry types, relation outer
rings (including untagged member ways and untagged way nodes), segment-crossing ways,
and de-duplication of features present in both extracts. No network.
"""
import json, pathlib, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import fetch_osm as fo  # noqa: E402

# Target A: lon -97.0..-96.0, lat 42.0..43.0     Target B: lon -96.0..-95.0, lat 42.0..43.0
NODES = {
    1: (-96.6, 42.5), 2: (-96.59, 42.5), 3: (-96.59, 42.51), 4: (-96.6, 42.51),   # building ring (A)
    5: (-96.5, 42.4), 6: (-96.4, 42.4),                                            # road (A)
    7: (-97.5, 42.2), 8: (-96.5, 42.2),                                            # road entering A from outside
    9: (-96.3, 42.3),                                                              # place (A)
    10: (-95.5, 42.5),                                                             # school (B)
    11: (-96.7, 42.7),                                                             # animal_hospital (A)
    12: (-96.8, 42.8), 13: (-96.79, 42.8), 14: (-96.79, 42.81), 15: (-96.8, 42.81),  # relation outer (A)
    16: (-98.5, 41.0), 17: (-98.4, 41.0),                                          # road outside both
    18: (-97.5, 42.9), 19: (-94.5, 42.9),                                          # crosses A and B, no vertex inside
    20: (-95.2, 42.2),                                                             # shop=general_store (B)
    21: (-96.55, 42.45), 22: (-96.54, 42.45),                                      # bridge (A)
}
WAYS = {
    100: ([1, 2, 3, 4, 1], {"building": "yes"}),
    101: ([5, 6], {"highway": "residential"}),
    102: ([7, 8], {"highway": "track"}),
    103: ([12, 13, 14, 15, 12], {}),                       # untagged outer member
    104: ([16, 17], {"highway": "primary"}),
    105: ([18, 19], {"highway": "motorway"}),
    106: ([21, 22], {"highway": "secondary", "bridge": "yes"}),
    107: ([5, 6, 9, 5], {"highway": "service"}),           # closed, not an area -> LineString
}
NODE_TAGS = {9: {"place": "village", "name": "Testville"}, 10: {"amenity": "school"},
             11: {"amenity": "animal_hospital"}, 20: {"shop": "general_store"}}
RELS = {200: ([("w", 103, "outer")], {"type": "multipolygon", "building": "barn"})}


def write_osm(path, node_ids, way_ids, rel_ids):
    def tags(d):
        return "".join(f'<tag k="{k}" v="{v}"/>' for k, v in d.items())
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6" generator="test">']
    for i in sorted(node_ids):
        lon, lat = NODES[i]
        out.append(f'<node id="{i}" version="1" lat="{lat}" lon="{lon}">{tags(NODE_TAGS.get(i, {}))}</node>')
    for i in sorted(way_ids):
        refs, t = WAYS[i]
        out.append(f'<way id="{i}" version="1">' + "".join(f'<nd ref="{r}"/>' for r in refs) + tags(t) + "</way>")
    for i in sorted(rel_ids):
        mem, t = RELS[i]
        out.append(f'<relation id="{i}" version="1">'
                   + "".join(f'<member type="{"way" if ty == "w" else "node"}" ref="{r}" role="{ro}"/>' for ty, r, ro in mem)
                   + tags(t) + "</relation>")
    out.append("</osm>")
    path.write_text("\n".join(out))


def load(t, theme):
    return json.loads((t.out / f"{theme}.geojson").read_text())["features"]


def ids(feats):
    return sorted((f["properties"]["osm_type"][0], f["properties"]["osm_id"]) for f in feats)


def main():
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        # "state 1" carries everything; "state 2" overlaps it with the cross-border way 105
        write_osm(d / "s1.osm", NODES.keys(), WAYS.keys(), RELS.keys())
        write_osm(d / "s2.osm", [10, 18, 19, 20], [105], [])
        A = fo.Target("00001", (-97.0, 42.0, -96.0, 43.0), d / "A", set(fo.THEMES))
        B = fo.Target("00002", (-96.0, 42.0, -95.0, 43.0), d / "B", set(fo.THEMES))
        for t in (A, B):
            t.out.mkdir()
        fo.extract([d / "s1.osm", d / "s2.osm"], [A, B])
        ca, cb = fo.Sink.finish(A), fo.Sink.finish(B)
        # one feature per line (D-067), so the stage can stream the buildings layer
        assert (A.out / "buildings.geojson").read_text().startswith('{"type":"FeatureCollection","features":[\n{')

        # roads: in-bbox way, vertex-entering way, segment-only crossing way, bridge, closed service way
        assert ids(load(A, "roads")) == [("w", 101), ("w", 102), ("w", 105), ("w", 106), ("w", 107)], ids(load(A, "roads"))
        assert ids(load(B, "roads")) == [("w", 105)], ids(load(B, "roads"))       # deduped across extracts
        assert ca["roads"] == 5 and cb["roads"] == 1

        # buildings: closed way -> Polygon; relation -> MultiPolygon from an untagged member way
        b = {f["properties"]["osm_id"]: f for f in load(A, "buildings")}
        assert set(b) == {100, 200}, set(b)
        assert b[100]["geometry"]["type"] == "Polygon"
        assert len(b[100]["geometry"]["coordinates"][0]) == 5          # untagged nodes located
        assert b[200]["geometry"]["type"] == "MultiPolygon"
        assert len(b[200]["geometry"]["coordinates"][0][0]) == 5
        assert b[200]["properties"]["osm_type"] == "relation"

        # closed highway way without area=yes stays a LineString (Overpass-fetcher parity)
        r107 = [f for f in load(A, "roads") if f["properties"]["osm_id"] == 107][0]
        assert r107["geometry"]["type"] == "LineString"

        # node themes and unanchored regexes (Overpass `~` semantics)
        assert ids(load(A, "places")) == [("n", 9)]
        assert ids(load(A, "healthcare")) == [("n", 11)]                    # animal_hospital matches
        assert ids(load(B, "schools")) == [("n", 10)]
        assert ids(load(B, "food_shops")) == [("n", 20)]                    # general_store matches
        assert ids(load(A, "bridges")) == [("w", 106)]
        assert load(A, "power") == [] and load(B, "buildings") == []

        # properties schema
        p = load(A, "places")[0]["properties"]
        assert p == {"osm_type": "node", "osm_id": 9, "place": "village", "name": "Testville"}, p
        assert not (A.out / ".osm_parts").exists()

    print("test_fetch_osm: all checks passed")


if __name__ == "__main__":
    main()
