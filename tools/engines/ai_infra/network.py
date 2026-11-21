"""Build a bus-branch network from observed OpenStreetMap power features.

Topology is observed (OSM lines and substations with their voltage tags); nothing here is
sampled. Electrical parameters are attached later, per seed, in power_flow.py.

Rules, each recorded in the network summary so a reader can see what the graph is made of:
- a substation is a power=substation feature; its voltages come from its voltage tag, else
  from the lines that end at it;
- a line endpoint attaches to a substation when it lies inside the substation polygon
  (buffered) or within snap distance of a point substation; otherwise it becomes a junction,
  merged with other endpoints within merge distance;
- a junction that lies on the interior of another line of the same voltage taps that line,
  which is split there;
- a multi-voltage line ("345000;138000") is one circuit per listed voltage;
- one bus per (node, kV); a substation with several voltages gets transformers from its
  highest voltage to each lower one;
- connected components with no bus outside the county and no source are kept but flagged
  unsupplied (they are usually OSM gaps, not real islands).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
import numpy as np
from shapely.geometry import LineString, MultiLineString, Point, Polygon, shape
from shapely.ops import substring, unary_union
from shapely.strtree import STRtree

LINE_KINDS = ("line", "minor_line", "cable")


def parse_kv(tag) -> list[float]:
    if tag is None:
        return []
    out = []
    for t in str(tag).replace(",", ";").split(";"):
        t = t.strip()
        try:
            v = float(t) / 1000.0
        except ValueError:
            continue
        if v >= 1.0 and v not in out:
            out.append(v)
    return out


@dataclass
class Network:
    buses: list = field(default_factory=list)        # dicts: id, kv, x, y, node, kind, in_county, ...
    lines: list = field(default_factory=list)        # dicts: f, t, kv, km, osm_id
    trafos: list = field(default_factory=list)       # dicts: hv, lv, kv_hv, kv_lv, node
    substations: list = field(default_factory=list)  # dicts: node, x, y, kvs, osm_id, operator, name, in_county
    summary: dict = field(default_factory=dict)
    masked: list = field(default_factory=list)

    def bus_index(self):
        return {(b["node"], b["kv"]): b["id"] for b in self.buses}


def _project(geom, f):
    def tx(coords):
        xs, ys = zip(*[f(c[0], c[1]) for c in coords])
        return list(zip(xs, ys))
    t = geom["type"]
    c = geom["coordinates"]
    if t == "Point":
        return Point(*f(c[0], c[1]))
    if t == "LineString":
        return LineString(tx(c))
    if t == "MultiLineString":
        return MultiLineString([tx(p) for p in c])
    if t == "Polygon":
        return Polygon(tx(c[0]))
    if t == "MultiPolygon":
        return unary_union([Polygon(tx(p[0])) for p in c])
    return None


def apply_mask(features, f_enu, site_xy=None, radius_m=2000.0, owner_terms=()):
    """Back-test site mask (PREREGISTRATION §4.2.2): drop substations within radius of the
    site and any substation whose operator or name names the owner; then drop lines ending
    at a dropped substation (done after snapping, in build(), by passing the masked ids as
    masked_sub_ids). Returns (features unchanged, masked substations)."""
    terms = [t.lower() for t in owner_terms if t]
    masked = []
    for ft in features:
        p = ft["properties"]
        if p.get("power") == "substation":
            g = _project(ft["geometry"], f_enu)
            near = site_xy is not None and g is not None and g.distance(Point(site_xy)) <= radius_m
            text = f"{p.get('operator', '')} {p.get('name', '')}".lower()
            owned = any(t in text for t in terms)
            if near or owned:
                masked.append({"osm_id": p.get("osm_id"), "reason": "within radius" if near else "owner tag",
                               "operator": p.get("operator"), "name": p.get("name")})
    return features, masked


def build(features, f_enu, county_poly, cfg: dict, masked_sub_ids=()) -> Network:
    net = Network()
    subs, lines = [], []
    for ft in features:
        p = ft["properties"]
        kind = p.get("power")
        if kind not in ("substation",) + LINE_KINDS:
            continue
        g = _project(ft["geometry"], f_enu)
        if g is None or g.is_empty:
            continue
        if kind == "substation":
            if g.geom_type == "LineString" and g.is_closed and len(g.coords) >= 4:
                g = Polygon(g.coords)
            subs.append({"geom": g, "kvs": parse_kv(p.get("voltage")), "osm_id": p.get("osm_id"),
                         "operator": p.get("operator"), "name": p.get("name")})
        else:
            parts = list(g.geoms) if g.geom_type == "MultiLineString" else [g]
            for part in parts:
                if part.length > 1.0:
                    lines.append({"geom": part, "kvs": parse_kv(p.get("voltage")), "osm_id": p.get("osm_id"),
                                  "kind": kind})

    snap = cfg["snap_substation_m"]
    pbuf = cfg["snap_substation_polygon_buffer_m"]
    merge = cfg["merge_endpoint_m"]
    tapd = cfg["tap_m"]

    # substation nodes
    nodes = []  # dicts: x, y, kind, sub (index) / None
    for i, s in enumerate(subs):
        c = s["geom"].centroid if s["geom"].geom_type != "Point" else s["geom"]
        s["node"] = len(nodes)
        s["match"] = s["geom"].buffer(pbuf) if s["geom"].geom_type == "Polygon" else c.buffer(snap)
        nodes.append({"x": c.x, "y": c.y, "kind": "substation", "sub": i})
    sub_tree = STRtree([s["match"] for s in subs]) if subs else None

    # attach endpoints
    junction_pts = []  # (x, y) of junction endpoints, for merging
    ends = []  # per line: [node_a, node_b]
    for ln in lines:
        e = []
        for pt in (Point(ln["geom"].coords[0]), Point(ln["geom"].coords[-1])):
            hit = None
            if sub_tree is not None:
                cand = [j for j in sub_tree.query(pt) if subs[j]["match"].contains(pt)]
                if cand:
                    hit = min(cand, key=lambda j: subs[j]["geom"].distance(pt))
            if hit is not None:
                e.append(("S", hit))
            else:
                e.append(("J", len(junction_pts)))
                junction_pts.append((pt.x, pt.y))
        ends.append(e)

    # merge junction endpoints within `merge` metres
    jn = np.array(junction_pts) if junction_pts else np.zeros((0, 2))
    parent = list(range(len(jn)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    if len(jn):
        tree = STRtree([Point(p) for p in jn])
        for i, p in enumerate(jn):
            for j in tree.query(Point(p).buffer(merge)):
                if j != i and np.hypot(*(jn[j] - p)) <= merge:
                    parent[find(i)] = find(j)
    jnode = {}
    for i in range(len(jn)):
        r = find(i)
        if r not in jnode:
            jnode[r] = len(nodes)
            nodes.append({"x": float(jn[r][0]), "y": float(jn[r][1]), "kind": "junction", "sub": None})

    def node_of(e):
        return subs[e[1]]["node"] if e[0] == "S" else jnode[find(e[1])]

    # T-taps: a junction lying on another line's interior splits that line
    line_tree = STRtree([ln["geom"] for ln in lines]) if lines else None
    taps = {i: [] for i in range(len(lines))}  # line index -> [(distance_along, node)]
    deg = {}
    for li, e in enumerate(ends):
        for side in e:
            n = node_of(side)
            deg[n] = deg.get(n, 0) + 1
    n_taps = 0
    for li, e in enumerate(ends):
        for side in e:
            if side[0] != "J":
                continue
            n = node_of(side)
            if deg.get(n, 0) > 1:
                continue  # already joined to another line end
            pt = Point(nodes[n]["x"], nodes[n]["y"])
            kv = set(lines[li]["kvs"])
            for k in line_tree.query(pt.buffer(tapd)):
                if k == li:
                    continue
                other = lines[k]
                if kv and other["kvs"] and not (kv & set(other["kvs"])):
                    continue
                d = other["geom"].project(pt)
                if tapd < d < other["geom"].length - tapd and other["geom"].distance(pt) <= tapd:
                    taps[k].append((d, n))
                    n_taps += 1
                    break

    # segments
    segs = []
    for li, ln in enumerate(lines):
        a, b = node_of(ends[li][0]), node_of(ends[li][1])
        cuts = sorted(taps[li])
        seq = [(0.0, a)] + cuts + [(ln["geom"].length, b)]
        for (d0, n0), (d1, n1) in zip(seq, seq[1:]):
            if n0 == n1 or d1 - d0 < 1.0:
                continue
            segs.append({"a": n0, "b": n1, "km": (d1 - d0) / 1000.0, "kvs": ln["kvs"], "osm_id": ln["osm_id"],
                         "geom": substring(ln["geom"], d0, d1)})

    # infer substation voltages from incident lines where untagged; junction voltages likewise
    incident = {}
    for s in segs:
        for n in (s["a"], s["b"]):
            incident.setdefault(n, set()).update(s["kvs"])
    for s in subs:
        lines_kv = incident.get(s["node"], set())
        if not s["kvs"]:
            s["kvs"] = sorted(lines_kv, reverse=True)
            s["kv_source"] = "inferred from lines"
        else:
            extra = lines_kv - set(s["kvs"])
            s["kv_source"] = "voltage tag" + (" + incident lines" if extra else "")
            s["kvs"] = sorted(set(s["kvs"]) | lines_kv, reverse=True)

    # lines with no voltage: take the voltage of an endpoint substation, else drop
    untagged_km = 0.0
    for s in segs:
        if not s["kvs"]:
            cand = []
            for n in (s["a"], s["b"]):
                if nodes[n]["kind"] == "substation":
                    cand += subs[nodes[n]["sub"]]["kvs"]
            if cand:
                s["kvs"] = [min(cand)]
                s["kv_source"] = "inferred from substation"
            else:
                untagged_km += s["km"]

    # masked substations drop their lines too (§4.2.2)
    masked_nodes = {subs[i]["node"] for i, s in enumerate(subs) if s["osm_id"] in set(masked_sub_ids)}

    # buses
    def in_county(x, y):
        return county_poly.contains(Point(x, y))

    bus_of = {}

    def bus(n, kv):
        key = (n, kv)
        if key not in bus_of:
            nd = nodes[n]
            s = subs[nd["sub"]] if nd["sub"] is not None else None
            bus_of[key] = len(net.buses)
            net.buses.append({"id": len(net.buses), "node": n, "kv": kv, "x": nd["x"], "y": nd["y"],
                              "kind": nd["kind"], "in_county": in_county(nd["x"], nd["y"]),
                              "sub_osm_id": s["osm_id"] if s else None})
        return bus_of[key]

    line_km_by_kv = {}
    for s in segs:
        if not s["kvs"] or s["a"] in masked_nodes or s["b"] in masked_nodes:
            continue
        for kv in s["kvs"]:
            net.lines.append({"f": bus(s["a"], kv), "t": bus(s["b"], kv), "kv": kv, "km": s["km"],
                              "osm_id": s["osm_id"],
                              "in_county_km": s["geom"].intersection(county_poly).length / 1000.0})
            line_km_by_kv[kv] = line_km_by_kv.get(kv, 0.0) + net.lines[-1]["in_county_km"]

    for i, s in enumerate(subs):
        if s["node"] in masked_nodes:
            continue
        kvs = sorted(set(s["kvs"]), reverse=True)
        for kv in kvs:
            bus(s["node"], kv)
        for lo in kvs[1:]:
            net.trafos.append({"hv": bus(s["node"], kvs[0]), "lv": bus(s["node"], lo), "kv_hv": kvs[0], "kv_lv": lo,
                               "node": s["node"]})
        c = nodes[s["node"]]
        net.substations.append({"node": s["node"], "x": c["x"], "y": c["y"], "kvs": kvs, "osm_id": s["osm_id"],
                                "operator": s["operator"], "name": s["name"], "kv_source": s["kv_source"],
                                "in_county": in_county(c["x"], c["y"])})

    # supply check per connected component
    g = nx.Graph()
    g.add_nodes_from(range(len(net.buses)))
    g.add_edges_from((l["f"], l["t"]) for l in net.lines)
    g.add_edges_from((t["hv"], t["lv"]) for t in net.trafos)
    comp_supplied = {}
    for ci, comp in enumerate(nx.connected_components(g)):
        sup = any(not net.buses[b]["in_county"] for b in comp)
        for b in comp:
            net.buses[b]["component"] = ci
            net.buses[b]["supplied"] = sup
        comp_supplied[ci] = sup
    unsup_km = sum(l["in_county_km"] for l in net.lines if not net.buses[l["f"]]["supplied"])
    net.summary = {
        "substations": len(net.substations),
        "substations_in_county": sum(s["in_county"] for s in net.substations),
        "substations_kv_inferred": sum(s["kv_source"] == "inferred from lines" for s in net.substations),
        "substations_in_county_supplied": sum(s["in_county"] and any(b["supplied"] for b in net.buses if b["node"] == s["node"]) for s in net.substations),
        "buses": len(net.buses), "lines": len(net.lines), "transformers": len(net.trafos),
        "t_taps": n_taps,
        "in_county_line_km_by_kv": {str(k): round(v, 1) for k, v in sorted(line_km_by_kv.items())},
        "line_km_dropped_no_voltage": round(untagged_km, 1),
        "components": len(comp_supplied), "components_unsupplied": sum(not v for v in comp_supplied.values()),
        "in_county_line_km_unsupplied": round(unsup_km, 1),
    }
    return net
