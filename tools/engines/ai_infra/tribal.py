"""Tribal land under D-420 (spec v0.2 `rules.tribal_land`, D-111).

Tribal land is every Census TIGER AIANNH area in the snapshot's tribal layer
(`layers_raw/tribal/tribal_<fips5>.geojson`, which carries CLASSFP). D-420 lists D0, D2, D3, D5,
D8 and D6, and treats Alaska Native village areas, Hawaiian Home Lands and state reservations the
same until decided. Census class D1 ("legal federally recognized American Indian area consisting
of reservation and associated off-reservation trust land") is missing from that list although it
is exactly what D-420 describes, so every class in the layer is treated as tribal land here (D-114).

Without a request from the nation's government no run places a site on tribal land or reports a
figure for its people. In a partly tribal county:
  * sites: experiment cards move their centroid site off tribal land (site_point, unchanged);
    proposal cards and back-tests touching tribal land are refused;
  * population: tribal-land households are removed from every lowest-quintile figure. That needs
    LR-13 (2020 Census block counts by AIANNH area, and ACS lowest-quintile income for the county
    outside tribal land). Until LR-13 is in R2, a lowest-quintile income figure in a county with
    tribal land is not computed (masked), never computed with tribal households in it;
  * utility-wide results that cannot be split by location (rate change %) still run, with no
    figure for the tribal area.
"""
from __future__ import annotations

import json

from shapely.geometry import Point, shape
from shapely.ops import transform, unary_union

from tools.engines.ai_infra import data, not_modelled

MIN_AREA_M2 = 10_000.0          # 1 ha
EDGE_M = 250.0                  # overlap is tested against the county shrunk by this much, so slivers
                                # where two boundary sources disagree along a shared line (e.g. the
                                # Osage Reservation against Chautauqua KS at the state line) are not
                                # read as tribal land inside the county


def parts(county) -> list[dict]:
    """Tribal areas of the snapshot, projected into the county's ENU frame."""
    rel = f"layers_raw/tribal/tribal_{county.fips5}.geojson"
    try:
        g = json.loads(county.path(rel).read_text())
    except FileNotFoundError:
        return []
    f_enu, _ = county.enu
    out = {}
    for ft in g.get("features", []):
        p = ft.get("properties") or {}
        try:
            geom = transform(lambda x, y, z=None: f_enu(x, y), shape(ft["geometry"])).buffer(0)
        except Exception:
            continue
        key = p.get("geoid") or p.get("namelsad")
        if key in out:
            out[key]["geom"] = out[key]["geom"].union(geom)
        else:
            out[key] = {"name": (p.get("namelsad") or p.get("name") or "").strip(), "geoid": p.get("geoid"),
                        "classfp": p.get("classfp"), "geom": geom}
    return list(out.values())


def county_status(poly, tparts) -> dict | None:
    """Nations whose land lies inside the county (by area, not by a shared boundary)."""
    inside = []
    core = poly.buffer(-EDGE_M)
    for t in tparts:
        if t["geom"].intersection(core).area >= MIN_AREA_M2:
            inside.append({**t, "area_share_of_county": t["geom"].intersection(poly).area / poly.area})
    if not inside:
        return None
    u = unary_union([t["geom"] for t in inside]).intersection(poly)
    return {"nations": [t["name"] for t in inside], "geoids": [t["geoid"] for t in inside],
            "classfp": [t["classfp"] for t in inside], "share_of_county_area": u.area / poly.area,
            "geom": u, "parts": inside}


def touches(geom_or_point, status) -> list[dict]:
    """The tribal areas a site point or cell touches (empty list: none)."""
    if status is None:
        return []
    return [{"name": t["name"], "geoid": t["geoid"], "classfp": t["classfp"]}
            for t in status["parts"] if t["geom"].intersects(geom_or_point)]


def population_mask(fips5, status) -> dict:
    """tribal_mask record field and the lowest-quintile income to use (D-420, LR-13)."""
    if status is None:
        return {"tribal_mask": None, "income_row": "county", "entries": []}
    parts_t = data.aiannh_county_parts()
    hh = None
    if parts_t is not None:
        x = parts_t[(parts_t.fips5 == fips5) & parts_t.aiannh_geoid.isin(status["geoids"])]
        hh = int(x.households.sum()) if len(x) else 0
    nontribal = data.acs_income_nontribal()
    nrow = None
    if nontribal is not None:
        r = nontribal[nontribal.fips5 == fips5]
        nrow = r.iloc[0].to_dict() if len(r) else None
    if hh == 0:
        income, how = "county", "LR-13: no households on tribal land in the county; nothing to remove"
    elif nrow is not None:
        income, how = nrow, "lowest-quintile income from ACS outside tribal land (LR-13)"
    else:
        income, how = None, ("lowest-quintile income not computed: tribal-land households cannot yet be "
                             "separated from the county's ACS figures (LR-13 not in R2)")
    mask = {"nations": status["nations"], "classfp": status["classfp"],
            "share_of_county_area": round(status["share_of_county_area"], 4),
            "sites_masked": True, "population_masked": True,
            "households_removed": hh, "method": how}
    ent = [not_modelled.entry(
        f"tribal land masked (D-420): {', '.join(status['nations'])}", "not_modelled",
        why="no site, intervention or modelled population on tribal land without the nation's request; "
            "utility-wide results carry no figure for the tribal area; " + how,
        who_can_answer="the nation's government, on its own terms")]
    return {"tribal_mask": mask, "income_row": income, "entries": ent}
