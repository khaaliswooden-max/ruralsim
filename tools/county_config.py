#!/usr/bin/env python3
"""Per-county build configuration, derived from pilots/ files.

Single source of truth for everything county-specific: names, state codes,
UTM zone, EPA region, buffered bbox, world directory. Usage in tools:

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from county_config import get
    C = get(sys.argv[1] if len(sys.argv) > 1 else None)   # default 31173
"""
import csv, pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent

# state abbr -> EPA region number (tribal-primacy pwsid prefix is zero-padded region)
EPA_REGION = {
    **dict.fromkeys(["CT", "ME", "MA", "NH", "RI", "VT"], 1),
    **dict.fromkeys(["NJ", "NY"], 2),
    **dict.fromkeys(["DE", "DC", "MD", "PA", "VA", "WV"], 3),
    **dict.fromkeys(["AL", "FL", "GA", "KY", "MS", "NC", "SC", "TN"], 4),
    **dict.fromkeys(["IL", "IN", "MI", "MN", "OH", "WI"], 5),
    **dict.fromkeys(["AR", "LA", "NM", "OK", "TX"], 6),
    **dict.fromkeys(["IA", "KS", "MO", "NE"], 7),
    **dict.fromkeys(["CO", "MT", "ND", "SD", "UT", "WY"], 8),
    **dict.fromkeys(["AZ", "CA", "HI", "NV"], 9),
    **dict.fromkeys(["AK", "ID", "OR", "WA"], 10),
}

BUF_DEG = 0.062  # ~5 km buffer around county bbox, in degrees


class Cfg:
    def __init__(self, fips):
        import geopandas as gpd
        self.fips = fips
        with open(REPO / "pilots" / "pilot_counties.csv") as fh:
            pilots = {r["fips5"]: r for r in csv.DictReader(fh)}
        row = pilots[fips]
        self.county_name = row["county_name"]                      # "Teton County"
        self.name_short = self.county_name.replace(" County", "")  # "Teton"
        self.st = row["state_abbr"]                                # "ID"
        self.archetype = row.get("archetype", "")
        self.centroid = (float(row["centroid_lon"]), float(row["centroid_lat"]))  # lon, lat
        g = gpd.read_file(REPO / "pilots" / "pilot_county_boundaries.geojson")
        self.geom = g[g["fips5"] == fips].geometry.iloc[0]
        w, s, e, n = self.geom.bounds
        self.bbox = (w, s, e, n)                                   # W, S, E, N
        self.buf_bbox = (w - BUF_DEG, s - BUF_DEG, e + BUF_DEG, n + BUF_DEG)
        zone = int((self.centroid[0] + 180) // 6) + 1              # all pilots N hemisphere
        self.utm = f"EPSG:326{zone:02d}"
        self.state_fips, self.county_code = fips[:2], fips[2:]     # NBI keys
        self.epa_region = EPA_REGION[self.st]
        self.slug = f"{self.name_short.lower()}_{self.st.lower()}" # "teton_id"
        self.dir_name = f"{fips}_{self.slug}"                      # "16081_teton_id"
        self.world = REPO / "worlds" / self.dir_name

    def __repr__(self):
        return f"<Cfg {self.dir_name} {self.utm} EPA-R{self.epa_region}>"


def get(fips=None):
    return Cfg(fips or "31173")
