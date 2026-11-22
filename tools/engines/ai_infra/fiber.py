"""Fiber module: is fiber offered at the site, and how many providers serve the county? (D-108; inputs D-058)

Reads FCC Broadband Data Collection fixed availability, technology 50 (fiber to the premises), as
of the BDC date named in the record, aggregated by RuralSim to H3 resolution-8 hexagons and to
counties (broadband/bdc/<as_of>/). No location Fabric is used: no address, location id or
coordinate.

- The site point is mapped to its H3 res-8 hexagon (~0.7 km2). "Fiber at the site" means fiber
  is reported somewhere in that hexagon.
- Nearest fiber is the nearest hexagon with fiber_locations > 0, measured centroid to centroid:
  a hexagon-level distance, not a route or construction distance.
- Availability is what providers say they could serve within 10 days. It is not subscriptions
  and it can be challenged.
- Middle-mile and long-haul fiber (what a data center needs most) are not in the BDC and are
  not observed anywhere in RuralSim: reported as not observed.
Deterministic: no input is sampled, so one evaluation is the result.
"""
from __future__ import annotations

import math

import h3

RES = 8


def _km(a, b):
    (la1, lo1), (la2, lo2) = a, b
    p = math.pi / 180
    x = (math.sin((la2 - la1) * p / 2) ** 2
         + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2)
    return 2 * 6371 * math.asin(math.sqrt(x))


def hex_table(fiber_h3):
    """Hexagon-level totals: a hexagon split across counties has one row per county part."""
    g = fiber_h3.groupby("h3_res8_id").agg(fiber_locations=("fiber_locations", "sum"),
                                            providers=("providers", "max"),
                                            max_down_mbps=("max_down_mbps", "max"),
                                            max_up_mbps=("max_up_mbps", "max"),
                                            locations_ge_1000_mbps=("locations_ge_1000_mbps", "sum"))
    return g


def run(lat, lon, hexes, county_row, radius_km):
    site = h3.latlng_to_cell(lat, lon, RES)
    out = {"status": "computed", "site_hex": site, "hex_resolution": RES,
           "distance_basis": "hexagon centroid to hexagon centroid (H3 res 8, ~0.7 km2); not a route distance",
           "availability_basis": "provider-reported availability within 10 days; not subscriptions; challengeable",
           "middle_mile": "not observed (not in BDC or any RuralSim layer)"}
    row = hexes.loc[site] if site in hexes.index else None
    out["fiber_in_site_hex"] = bool(row is not None and row.fiber_locations > 0)
    if out["fiber_in_site_hex"]:
        out.update(site_hex_fiber_locations=int(row.fiber_locations), site_hex_providers=int(row.providers),
                   site_hex_max_down_mbps=float(row.max_down_mbps), site_hex_max_up_mbps=float(row.max_up_mbps))
        out["nearest_fiber_hex_km"] = 0.0
        out["nearest_fiber_hex"] = site
    else:
        k = int(math.ceil(radius_km / 0.9)) + 1          # res-8 centre spacing is ~0.92 km
        ring = [c for c in h3.grid_disk(site, k) if c in hexes.index]
        here = h3.cell_to_latlng(site)
        best = None
        for c in ring:
            r = hexes.loc[c]
            if r.fiber_locations <= 0:
                continue
            d = _km(here, h3.cell_to_latlng(c))
            if d <= radius_km and (best is None or d < best[0]):
                best = (d, c, r)
        if best is None:
            out["nearest_fiber_hex_km"] = None
            out["nearest_fiber_note"] = f"no fiber hexagon within {radius_km} km"
        else:
            d, c, r = best
            out.update(nearest_fiber_hex_km=d, nearest_fiber_hex=c, nearest_hex_fiber_locations=int(r.fiber_locations),
                       nearest_hex_providers=int(r.providers), nearest_hex_max_down_mbps=float(r.max_down_mbps),
                       nearest_hex_max_up_mbps=float(r.max_up_mbps))
    if county_row is not None:
        out.update(county_fiber_providers=int(county_row["fiber_providers"]),
                   county_fiber_brands=county_row["brand_names"],
                   county_fiber_locations=int(county_row["fiber_locations"]),
                   county_hexes_with_fiber=int(county_row["hexes_with_fiber"]))
    else:
        out.update(county_fiber_providers=0, county_fiber_locations=0, county_hexes_with_fiber=0)
    return out
