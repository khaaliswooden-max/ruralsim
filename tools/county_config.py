#!/usr/bin/env python3
"""Per-county build configuration: single source of truth for everything county-specific
(names, state codes, UTM zone, EPA region, boundary, buffered bbox, world directory).

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from county_config import get
    C = get(sys.argv[1] if len(sys.argv) > 1 else None)   # default 31173

Any current U.S. county (2024 geography) can be built:
  * The five pilot counties read pilots/pilot_counties.csv and
    pilots/pilot_county_boundaries.geojson (Census 2023 cartographic boundary, 1:500k),
    exactly as before.
  * Every other county reads its name, state and centroid from data/county_master.csv
    and its polygon from counties/<fips5>.geojson. If that file is missing, it is fetched
    once from Census TIGERweb (current TIGER/Line geometry, observed) and committed-ready
    with a provenance note, so later builds are offline and reproducible.
"""
import csv, json, pathlib, re, urllib.parse, urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
COUNTIES = REPO / "counties"

# state abbr -> EPA region number (tribal-primacy pwsid prefix is zero-padded region)
EPA_REGION = {
    **dict.fromkeys(["CT", "ME", "MA", "NH", "RI", "VT"], 1),
    **dict.fromkeys(["NJ", "NY", "PR", "VI"], 2),
    **dict.fromkeys(["DE", "DC", "MD", "PA", "VA", "WV"], 3),
    **dict.fromkeys(["AL", "FL", "GA", "KY", "MS", "NC", "SC", "TN"], 4),
    **dict.fromkeys(["IL", "IN", "MI", "MN", "OH", "WI"], 5),
    **dict.fromkeys(["AR", "LA", "NM", "OK", "TX"], 6),
    **dict.fromkeys(["IA", "KS", "MO", "NE"], 7),
    **dict.fromkeys(["CO", "MT", "ND", "SD", "UT", "WY"], 8),
    **dict.fromkeys(["AZ", "CA", "HI", "NV", "AS", "GU", "MP"], 9),
    **dict.fromkeys(["AK", "ID", "OR", "WA"], 10),
}

BUF_DEG = 0.062  # ~5 km buffer around county bbox, in degrees
TIGERWEB = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
            "State_County/MapServer/1/query")


def _pilots():
    with open(REPO / "pilots" / "pilot_counties.csv") as fh:
        return {r["fips5"]: r for r in csv.DictReader(fh)}


def _master_row(fips):
    with open(REPO / "data" / "county_master.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["fips5"] == fips and r.get("geography_vintage") == "2024":
                return r
    raise KeyError(f"{fips} is not a current (2024-vintage) county in data/county_master.csv")


def fetch_boundary(fips):
    """Return the county polygon as a GeoJSON geometry, caching it in counties/."""
    path = COUNTIES / f"{fips}.geojson"
    if path.exists():
        return json.loads(path.read_text())["features"][0]["geometry"]
    q = urllib.parse.urlencode({"where": f"GEOID='{fips}'", "outFields": "GEOID,NAME,BASENAME",
                                "outSR": "4326", "f": "geojson"})
    req = urllib.request.Request(f"{TIGERWEB}?{q}", headers={"User-Agent": "ruralsim/1.0 (+https://www.ruralsim.io)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        fc = json.load(r)
    if not fc.get("features"):
        raise KeyError(f"TIGERweb returned no county polygon for {fips}")
    feat = fc["features"][0]
    feat["properties"] = {"fips5": fips, "name": feat["properties"].get("NAME", ""),
                          "source": "Census TIGERweb State_County layer 1 (current TIGER/Line), EPSG:4326",
                          "provenance": "observed"}
    COUNTIES.mkdir(exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [feat]}))
    return feat["geometry"]


def slugify(s):
    s = s.lower().replace("ñ", "n")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


class Cfg:
    def __init__(self, fips):
        from shapely.geometry import shape
        import geopandas as gpd
        self.fips = fips = str(fips).zfill(5)
        pilots = _pilots()
        self.is_pilot = fips in pilots
        if self.is_pilot:
            row = pilots[fips]
            self.archetype = row.get("archetype", "")
            g = gpd.read_file(REPO / "pilots" / "pilot_county_boundaries.geojson")
            self.geom = g[g["fips5"] == fips].geometry.iloc[0]
            self.boundary_source = "Census 2023 cartographic boundary 1:500k (pilots/)"
        else:
            row = _master_row(fips)
            self.archetype = ""
            self.geom = shape(fetch_boundary(fips))
            self.boundary_source = "Census TIGERweb current TIGER/Line (counties/)"
        self.county_name = row["county_name"]                      # "Teton County"
        self.name_short = re.sub(r" (County|Parish|Borough|Census Area|Municipality|city|City and Borough)$",
                                 "", self.county_name)             # "Teton"
        self.st = row["state_abbr"]                                # "ID"
        self.centroid = (float(row["centroid_lon"]), float(row["centroid_lat"]))  # lon, lat
        w, s, e, n = self.geom.bounds
        self.bbox = (w, s, e, n)                                   # W, S, E, N
        self.buf_bbox = (w - BUF_DEG, s - BUF_DEG, e + BUF_DEG, n + BUF_DEG)
        zone = int((self.centroid[0] + 180) // 6) + 1              # all U.S. counties are N hemisphere
        self.utm = f"EPSG:326{zone:02d}"
        self.state_fips, self.county_code = fips[:2], fips[2:]     # NBI keys
        self.epa_region = EPA_REGION[self.st]
        # pilot slugs are unchanged ("teton_id"); others are made filesystem-safe
        self.slug = f"{slugify(self.name_short)}_{self.st.lower()}"
        self.dir_name = f"{fips}_{self.slug}"                      # "16081_teton_id"
        self.world = REPO / "worlds" / self.dir_name

    def __repr__(self):
        kind = "pilot" if self.is_pilot else "county"
        return f"<Cfg {kind} {self.dir_name} {self.utm} EPA-R{self.epa_region}>"


def get(fips=None):
    return Cfg(fips or "31173")
