"""Road-network travel-time engine over the county's observed OSM layer.

Speeds by highway class are ASSUMED defaults (tagged); geometry is observed (OSM).
"""
from __future__ import annotations

import json
import math

import networkx as nx
import numpy as np
from scipy.spatial import cKDTree

# km/h, assumed defaults pending posted-speed data
SPEED_KMH = {
    "motorway": 105, "trunk": 90, "primary": 80, "secondary": 65,
    "tertiary": 55, "unclassified": 45, "residential": 40, "service": 25,
    "track": 20, "living_street": 20, "motorway_link": 60, "trunk_link": 60,
    "primary_link": 60, "secondary_link": 50, "tertiary_link": 45,
}
DEFAULT_SPEED_KMH = 40.0  # assumed


class RoadNet:
    def __init__(self, roads_json_path: str):
        self.g = nx.Graph()
        pts, kinds = [], []
        with open(roads_json_path) as f:
            roads = json.load(f)
        for r in roads:
            p = r["pts"]
            if len(p) < 2:
                continue
            kind = r.get("hwy") or "unclassified"
            v = SPEED_KMH.get(kind, DEFAULT_SPEED_KMH) / 3.6  # m/s
            for a, b in zip(p[:-1], p[1:]):
                na = (round(a[0], 1), round(a[1], 1))
                nb = (round(b[0], 1), round(b[1], 1))
                if na == nb:
                    continue
                d = math.hypot(a[0] - b[0], a[1] - b[1])
                w = d / v  # seconds
                if self.g.has_edge(na, nb):
                    if w < self.g[na][nb]["w"]:
                        self.g[na][nb]["w"] = w
                else:
                    self.g.add_edge(na, nb, w=w)
                pts.append(na)
                kinds.append(kind)
        self.nodes = np.array(list(self.g.nodes))
        self.tree = cKDTree(self.nodes)
        self.kind_by_node = {}

    def snap(self, xy):
        """Return (node tuple, walk_penalty_s) — 1.4x straight distance at 5 km/h."""
        d, i = self.tree.query(np.atleast_2d(xy))
        node = tuple(self.nodes[i[0]])
        pen = (d[0] * 1.4) / (5 / 3.6)
        return node, float(pen)

    def times_from(self, xy) -> dict:
        """Dijkstra seconds from nearest node to xy, over all nodes."""
        node, pen = self.snap(xy)
        return nx.single_source_dijkstra_path_length(self.g, node, weight="w"), pen

    def minutes_between(self, a_xy, b_xy) -> float:
        d, _ = self.times_from(a_xy)
        nb, penb = self.snap(b_xy)
        _, pena = self.snap(a_xy)
        t = d.get(nb)
        if t is None:
            return float("nan")
        return (t + pena + penb) / 60.0
