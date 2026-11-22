"""Flood module: is the site in a mapped flood hazard area? (D-107; inputs D-057, which supersedes D-013)

Screening-grade. Reads FEMA NFHL hazard zones clipped to the county (flood/nfhl/zones/<fips5>.parquet)
and the county's map status (flood/nfhl/county_status.parquet).

- The site point is joined to the zones by point-in-polygon.
- The screening metric is the share of a site footprint inside the 1% annual-chance flood zone
  (SFHA, sfha_tf == "T"). The footprint is a square around the site point whose area is assumed
  and drawn per seed. The 0.2% zone (X shaded) and zone D are reported, not scored.
- Map status rules (D-057):
  - status "none" means no digital FIRM, never "no flood risk": the module is indeterminate.
  - status "partial": a site outside every drawn zone could be unmapped, so it is indeterminate
    unless the site point falls inside a drawn zone.
  - status "effective": land outside every drawn zone is zone X unshaded (minimal hazard), which the
    layer does not draw.
  - prelim or pending coverage above 0 flags that the effective map is about to change.
  - zone A without a base flood elevation is flagged as an approximate study.
"""
from __future__ import annotations

import math

import numpy as np
import shapely
from shapely import wkb
from shapely.geometry import Point, box
from shapely.ops import unary_union

from .power_flow import u


def county_status(status_df, fips5):
    r = status_df[status_df.fips5 == fips5]
    if r.empty:
        return None
    r = r.iloc[0]
    out = {k: (None if (isinstance(v, float) and math.isnan(v)) else v) for k, v in r.to_dict().items()}
    for k in ("county_km2", "effective_coverage", "prelim_coverage", "pending_coverage", "sfha_km2", "sfha_share"):
        if out.get(k) is not None:
            out[k] = float(out[k])
    return out


def prepare(zones_df, f_enu, site_xy, search_m):
    """Project zone polygons near the site into the county's ENU metres. Returns lists of
    (geometry, attrs) for SFHA, X shaded and D, plus all drawn zones."""
    sx, sy = site_xy
    window = box(sx - search_m, sy - search_m, sx + search_m, sy + search_m)

    def proj(coords):
        xs, ys = zip(*[f_enu(a, b) for a, b in coords])
        return np.column_stack([xs, ys])

    out = []
    for _, z in zones_df.iterrows():
        g = wkb.loads(z.geometry) if isinstance(z.geometry, (bytes, bytearray, memoryview)) else z.geometry
        if g is None or g.is_empty:
            continue
        gp = shapely.transform(g, proj)
        if not gp.intersects(window):
            continue
        out.append((gp.buffer(0), {"fld_zone": z.fld_zone, "zone_subty": z.zone_subty, "sfha_tf": z.sfha_tf,
                                   "static_bfe": None if z.static_bfe is None or (isinstance(z.static_bfe, float) and math.isnan(z.static_bfe)) or z.static_bfe in (-9999, -9999.0) else float(z.static_bfe),
                                   "dfirm_id": z.dfirm_id}))
    return out


def run(status, zones_near, site_xy, cfg, rng):
    c = cfg["flood"]
    out = {"status": "computed", "map_status": None, "flags": []}
    if status is None:
        return {"status": "indeterminate", "reason": "county not in flood/nfhl/county_status.parquet"}
    out["map_status"] = status["status"]
    out["effective_dates"] = [status.get("eff_date_min"), status.get("eff_date_max")]
    if (status.get("prelim_coverage") or 0) > 0 or (status.get("pending_coverage") or 0) > 0:
        out["flags"].append(f"effective map about to change: preliminary maps cover {status.get('prelim_coverage') or 0:.1%} "
                            f"(issued {status.get('prelim_issue_date_max')}), pending {status.get('pending_coverage') or 0:.1%}")
    if status["status"] == "none":
        return {**out, "status": "indeterminate",
                "reason": "no digital FIRM for this county (FEMA NFHL); this is not 'no flood risk'"}

    area_ha = u(rng, c["footprint_area_ha"])
    side = math.sqrt(area_ha * 1e4)
    sx, sy = site_xy
    fp = box(sx - side / 2, sy - side / 2, sx + side / 2, sy + side / 2)
    pt = Point(sx, sy)
    out["footprint_area_ha"] = area_ha

    hit = [a for g, a in zones_near if g.contains(pt)]
    if status["status"] == "partial" and not hit:
        return {**out, "status": "indeterminate",
                "reason": "county only partly mapped and the site lies outside every drawn zone: it may be unmapped"}
    if hit:
        a = sorted(hit, key=lambda a: a["sfha_tf"] != "T")[0]
        out["site_point_zone"] = a["fld_zone"] + (f" ({a['zone_subty']})" if a.get("zone_subty") else "")
        out["site_point_in_sfha"] = a["sfha_tf"] == "T"
    else:
        out["site_point_zone"] = "X unshaded (minimal hazard; not drawn)"
        out["site_point_in_sfha"] = False

    def share(pred):
        gs = [g for g, a in zones_near if pred(a)]
        return unary_union(gs).intersection(fp).area / fp.area if gs else 0.0

    out["footprint_share_sfha"] = share(lambda a: a["sfha_tf"] == "T")
    out["footprint_share_x_shaded"] = share(lambda a: a["fld_zone"] == "X" and a["sfha_tf"] != "T")
    out["footprint_share_zone_d"] = share(lambda a: a["fld_zone"] == "D")
    sfha = [g for g, a in zones_near if a["sfha_tf"] == "T"]
    out["distance_to_sfha_m"] = (min(g.distance(pt) for g in sfha) if sfha else None)
    approx = any(a["sfha_tf"] == "T" and a["fld_zone"] == "A" and a.get("static_bfe") is None
                 for g, a in zones_near if g.intersects(fp))
    if approx:
        out["flags"].append("zone A without base flood elevation (approximate study) intersects the footprint")
    if status["status"] == "partial":
        out["flags"].append("county only partly mapped; unmapped land inside the footprint counts as not in a zone")
    return out
