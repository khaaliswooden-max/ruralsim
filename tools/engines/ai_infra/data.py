"""Read published county layers and the national EIA tables from RuralSim's public R2.

Everything is read from immutable snapshots: a county run names its snapshot and the
manifest's sha256 for each file, so a record can be reproduced byte for byte. Files are
cached under $RURALSIM_CACHE/ai_infra (default ~/.cache/ruralsim/ai_infra).
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pyproj

BASE = os.environ.get("RURALSIM_DATA_BASE", "https://data.ruralsim.io").rstrip("/")
CACHE = Path(os.environ.get("RURALSIM_CACHE", Path.home() / ".cache" / "ruralsim")) / "ai_infra"
ROOT = Path(__file__).resolve().parents[3]

EIA_TABLES = ("eia860_generators", "eia860_plants", "eia861_utility_data",
              "eia861_sales_ult_cust", "eia861_service_territory", "eia861_short_form")


def _get(url: str, dest: Path, sha256: str | None = None) -> Path:
    if dest.exists() and (sha256 is None or _sha(dest) == sha256):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "RuralSim-engine/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    if sha256 is not None and _sha(tmp) != sha256:
        tmp.unlink()
        raise RuntimeError(f"sha256 mismatch for {url}")
    tmp.rename(dest)
    return dest


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@lru_cache(maxsize=1)
def index() -> dict:
    p = _get(f"{BASE}/worlds/index.json", CACHE / "index.json")
    return {e["fips5"]: e for e in json.loads(p.read_text())["counties"]}


class County:
    """One published county snapshot."""

    def __init__(self, fips5: str, snapshot: str | None = None):
        if not (isinstance(fips5, str) and len(fips5) == 5 and fips5.isdigit()):
            raise ValueError("fips5 must be a zero-padded 5-character string")
        e = index().get(fips5)
        if e is None:
            raise LookupError(f"{fips5} is not published (worlds/index.json)")
        self.fips5, self.dir = fips5, e["dir"]
        self.snapshot = snapshot or e["snapshot"]
        self.prefix = f"worlds/{self.dir}/snapshots/{self.snapshot}"
        self.local = CACHE / self.dir / self.snapshot
        mp = _get(f"{BASE}/{self.prefix}/manifest.json", self.local / "manifest.json")
        self.manifest_sha256 = _sha(mp)
        self.manifest = json.loads(mp.read_text())
        self._files = {f["path"]: f["sha256"] for f in self.manifest["files"]}

    def path(self, rel: str) -> Path:
        if rel not in self._files:
            raise FileNotFoundError(f"{rel} not in {self.prefix}/manifest.json")
        return _get(f"{BASE}/{self.prefix}/{rel}", self.local / rel, self._files[rel])

    def json(self, rel: str):
        return json.loads(self.path(rel).read_text())

    @property
    def enu(self):
        """(lon, lat) -> local ENU metres, the frame of viewer_data/*."""
        tm = self.json("viewer_data/terrain_meta.json")
        fwd = pyproj.Transformer.from_crs(4326, tm["utm"], always_xy=True)
        ox, oy = fwd.transform(*tm["enu_origin_deg"])

        def f(lon, lat):
            x, y = fwd.transform(lon, lat)
            return x - ox, y - oy

        inv = pyproj.Transformer.from_crs(tm["utm"], 4326, always_xy=True)

        def g(x, y):
            return inv.transform(x + ox, y + oy)

        return f, g

    def record(self) -> dict:
        return {"fips5": self.fips5, "dir": self.dir, "snapshot": self.snapshot,
                "manifest_sha256": self.manifest_sha256}


@lru_cache(maxsize=32)
def eia(table: str, year: int = 2024) -> pd.DataFrame:
    if table not in EIA_TABLES:
        raise KeyError(table)
    p = _get(f"{BASE}/eia/{year}/{table}.parquet", CACHE / "eia" / str(year) / f"{table}.parquet")
    return pd.read_parquet(p)


def eia_meta(year: int = 2024) -> dict:
    p = _get(f"{BASE}/eia/{year}/_meta.json", CACHE / "eia" / str(year) / "_meta.json")
    return json.loads(p.read_text())


def eia_available(year: int) -> bool:
    try:
        eia_meta(year)
        return True
    except Exception:
        return False


@lru_cache(maxsize=2)
def acs_income_quintiles(year: int = 2024) -> pd.DataFrame:
    """ACS 5-year B19081/B19080 per fips5 (LR-11, D-053), with margins of error."""
    p = _get(f"{BASE}/acs/{year}/income_quintiles.parquet", CACHE / "acs" / str(year) / "income_quintiles.parquet")
    return pd.read_parquet(p)


def acs_meta(year: int = 2024) -> dict:
    p = _get(f"{BASE}/acs/{year}/_meta.json", CACHE / "acs" / str(year) / "_meta.json")
    return json.loads(p.read_text())


@lru_cache(maxsize=1)
def usgs_wateruse_2015() -> pd.DataFrame:
    """USGS county water use 2015 (Dieter et al. 2018; LR-4, D-056). Mgal/d; population in thousands."""
    return pd.read_parquet(_get(f"{BASE}/water/usgs_wateruse_2015/county.parquet",
                                CACHE / "water" / "usgs_wateruse_2015.parquet"))


@lru_cache(maxsize=1)
def nwis_gauges() -> pd.DataFrame:
    """Active USGS stream gauges with day-of-year flow statistics (LR-6, D-056)."""
    return pd.read_parquet(_get(f"{BASE}/water/nwis/gauges.parquet", CACHE / "water" / "nwis_gauges.parquet"))


@lru_cache(maxsize=1)
def sdwis_systems() -> pd.DataFrame:
    """EPA SDWIS water systems, national, one column set, no contact fields (LR-5, D-054)."""
    return pd.read_parquet(_get(f"{BASE}/water/sdwis/water_systems.parquet", CACHE / "water" / "sdwis.parquet"))


@lru_cache(maxsize=8)
def power_daily(fips5: str) -> pd.DataFrame:
    """NASA POWER daily T2M, T2MDEW, T2MWET at the county centroid, 1991-2020 (LR-3, D-054)."""
    return pd.read_parquet(_get(f"{BASE}/climate/power/daily/{fips5}.parquet",
                                CACHE / "climate" / "power" / f"{fips5}.parquet"))


@lru_cache(maxsize=1)
def nfhl_status() -> pd.DataFrame:
    """FEMA NFHL map status per county (LR-8, D-057)."""
    return pd.read_parquet(_get(f"{BASE}/flood/nfhl/county_status.parquet", CACHE / "flood" / "county_status.parquet"))


@lru_cache(maxsize=8)
def nfhl_zones(fips5: str) -> pd.DataFrame:
    """FEMA NFHL hazard zones clipped to the county, WKB EPSG:4326 (LR-8, D-057). Zone X unshaded not drawn."""
    return pd.read_parquet(_get(f"{BASE}/flood/nfhl/zones/{fips5}.parquet", CACHE / "flood" / "zones" / f"{fips5}.parquet"))


def nfhl_meta() -> dict:
    return json.loads(_get(f"{BASE}/flood/nfhl/_meta.json", CACHE / "flood" / "_meta.json").read_text())


@lru_cache(maxsize=2)
def bdc_fiber(as_of: str, table: str) -> pd.DataFrame:
    """FCC BDC fiber (technology 50) aggregates: fiber_h3, fiber_county or fiber_providers (LR-7, D-058)."""
    return pd.read_parquet(_get(f"{BASE}/broadband/bdc/{as_of}/{table}.parquet",
                                CACHE / "broadband" / as_of / f"{table}.parquet"))


def bdc_meta(as_of: str) -> dict:
    m = json.loads(_get(f"{BASE}/broadband/bdc/{as_of}/_meta.json", CACHE / "broadband" / as_of / "_meta.json").read_text())
    return {k: m.get(k) for k in ("source", "api", "as_of", "written_utc", "license", "counts") if k in m} | {"files": len(m.get("files", []))}


def water_meta() -> dict:
    out = {}
    for k, rel in (("usgs_wateruse_2015", "water/usgs_wateruse_2015/_meta.json"), ("nwis", "water/nwis/_meta.json"),
                   ("sdwis", "water/sdwis/_meta.json"), ("nasa_power", "climate/power/_meta.json")):
        m = json.loads(_get(f"{BASE}/{rel}", CACHE / "meta" / rel.replace("/", "_")).read_text())
        out[k] = {x: m.get(x) for x in ("source", "doi", "year", "license", "written_utc", "note") if x in m}
    return out


def _optional(rel: str, dest: Path) -> pd.DataFrame | None:
    """A table that may not be published yet: None on HTTP 404 only; any other error raises."""
    import urllib.error
    try:
        return pd.read_parquet(_get(f"{BASE}/{rel}", dest))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


@lru_cache(maxsize=8)
def popest_vintage(vintage: int) -> pd.DataFrame | None:
    """Census county population estimates as published in one vintage (LR-12): fips5, year,
    population. A back-test reads the vintage of year T0-1, so no later revision leaks in.
    None until the table is in R2."""
    return _optional(f"census/popest/v{vintage}/county.parquet", CACHE / "census" / "popest" / f"v{vintage}.parquet")


@lru_cache(maxsize=4)
def decennial_households(year: int) -> pd.DataFrame | None:
    """Census decennial count per county (LR-12): fips5, population, households (occupied units).
    None until the table is in R2."""
    return _optional(f"census/decennial/{year}/households.parquet", CACHE / "census" / "decennial" / f"{year}_households.parquet")


@lru_cache(maxsize=1)
def aiannh_county_parts() -> pd.DataFrame | None:
    """LR-13 (a): 2020 Census population and households by county x AIANNH area, summed from blocks:
    fips5, aiannh_geoid, namelsad, classfp, population, households. None until in R2."""
    return _optional("census/aiannh/2020/county_parts.parquet", CACHE / "census" / "aiannh_2020_county_parts.parquet")


@lru_cache(maxsize=1)
def acs_income_nontribal() -> pd.DataFrame | None:
    """LR-13 (b): ACS 2020-2024 lowest-quintile mean household income for the county outside
    tribal land: fips5, mean_q1, mean_q1_moe, households, method. None until in R2."""
    return _optional("acs/2024/income_quintiles_nontribal.parquet", CACHE / "acs" / "2024" / "income_quintiles_nontribal.parquet")


@lru_cache(maxsize=8)
def fiscal_table(state: str, table: str) -> pd.DataFrame | None:
    """LR-14: fiscal/<ST>/taxing_units.parquet or local_agreements.parquet (D-430). None until in R2."""
    return _optional(f"fiscal/{state}/{table}.parquet", CACHE / "fiscal" / state / f"{table}.parquet")


@lru_cache(maxsize=1)
def tier_a() -> pd.DataFrame:
    return pd.read_csv(ROOT / "national" / "tier_a_county_stats.csv", dtype={"fips5": str})
