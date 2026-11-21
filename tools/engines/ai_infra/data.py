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

BASE = os.environ.get("RURALSIM_DATA_BASE", "https://pub-b414cd9251804d11871e4bec734e096e.r2.dev").rstrip("/")
CACHE = Path(os.environ.get("RURALSIM_CACHE", Path.home() / ".cache" / "ruralsim")) / "ai_infra"
ROOT = Path(__file__).resolve().parents[3]

EIA_TABLES = ("eia860_generators", "eia860_plants", "eia861_utility_data",
              "eia861_sales_ult_cust", "eia861_service_territory")


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


@lru_cache(maxsize=8)
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


@lru_cache(maxsize=1)
def tier_a() -> pd.DataFrame:
    return pd.read_csv(ROOT / "national" / "tier_a_county_stats.csv", dtype={"fips5": str})
