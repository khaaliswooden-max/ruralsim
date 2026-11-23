"""Synthetic household population for a pilot county.

GUARDRAIL: synthetic people, never real ones. Households are random points placed on
OSM building centroids (derived locations). No address-level records are read or
written; outputs are aggregates and deciles only.

Incomes (D-104): calibrated to the county's ACS 2020-2024 household income quintiles
(B19081 means, B19080 limits; data/acs_income_quintiles_2024.csv, from D-053). Each seed
draws the ten ACS figures inside their margins of error, assigns a fifth of households to
each quintile, and draws incomes within each quintile's range so its mean matches ACS.
Counties without a complete ACS row fall back to the earlier lognormal calibrated to SAIPE
median income and poverty (D-025), and the population's provenance says so. The lognormal
put the bottom quintile's mean under half of ACS in 6.6% of nonmetro counties (Wilcox AL
0.17x, McDowell WV 0.09x), which inflated every cost-share indicator for poor households.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from . import denylist

ROOT = Path(__file__).resolve().parents[2]  # ruralsim/
DATA = ROOT / "data"

RESIDENTIAL_KINDS = None  # accept all building kinds as candidate dwelling sites (derived)

MODEL = "acs-quintiles-v2"  # part of the baseline-cache key; bump when the income model changes
ACS_FILE = DATA / "acs_income_quintiles_2024.csv"
_BETA_CONCENTRATION = 4.0   # shape of the within-quintile draw (assumed); the mean is fixed by ACS


def acs_row(fips: str):
    """The county's ACS quintile row, or None if any figure the sampler needs is missing."""
    if not ACS_FILE.exists():
        return None
    df = pd.read_csv(ACS_FILE, dtype={"fips5": str})
    r = df.loc[df["fips5"] == fips]
    if r.empty:
        return None
    r = r.iloc[0]
    need = [f"mean_q{k}" for k in range(1, 6)] + [f"upper_q{k}" for k in range(1, 5)]
    if any(pd.isna(r[c]) for c in need):
        return None
    return r


def _draw_acs(r, rng):
    """One seed's draw of the ACS means and limits inside their 90% margins (sd = MOE/1.645),
    repaired so limits increase and each mean lies inside its band."""
    def draw(col):
        est, moe = float(r[col]), float(r.get(col + "_moe") or 0.0)
        return max(rng.normal(est, moe / 1.645) if moe > 0 else est, 1.0)
    u = sorted(draw(f"upper_q{k}") for k in range(1, 5))
    m = [draw(f"mean_q{k}") for k in range(1, 6)]
    lo = [0.0] + u
    for k in range(4):
        a, b = lo[k], u[k]
        m[k] = min(max(m[k], a + 0.05 * (b - a)), b - 0.05 * (b - a))
    m[4] = max(m[4], 1.05 * u[3])
    return lo, u, m


def acs_incomes(r, n, rng):
    """Incomes for n households: a fifth in each ACS quintile, each quintile's mean equal in
    expectation to the drawn ACS mean. Bounded quintiles use a scaled Beta on [lower, upper];
    the top quintile is its lower limit plus an exponential tail."""
    lo, u, m = _draw_acs(r, rng)
    q = rng.permutation(np.resize(np.arange(5), n))
    inc = np.empty(n)
    kappa = _BETA_CONCENTRATION
    for k in range(4):
        a, b = lo[k], u[k]
        idx = q == k
        al = kappa * (m[k] - a) / (b - a)
        inc[idx] = a + (b - a) * rng.beta(al, kappa - al, idx.sum())
    idx = q == 4
    inc[idx] = u[3] + rng.exponential(m[4] - u[3], idx.sum())
    return inc, {"limits": u, "means": m}


def county_row(fips: str) -> pd.Series:
    df = pd.read_csv(DATA / "county_master.csv", dtype={"fips5": str})
    # county_master carries governance-context columns (pres_margin_rd_*); strip them at
    # load so they can never enter the objective, features or targeting (D-007).
    forbidden = [c for c in df.columns if denylist._bad(c)]
    if forbidden:
        df = df.drop(columns=forbidden)
    denylist.assert_clean_columns(df.columns, context="county_master.csv (post-strip)")
    row = df.loc[df["fips5"] == fips]
    if row.empty:
        raise KeyError(f"fips {fips} not in county_master.csv")
    return row.iloc[0]


def _calibrate_lognormal(median: float, poverty_rate: float, rng: np.random.Generator):
    """Pick sigma so that P(income < poverty_line) ~= poverty_rate, given the median.

    Poverty line proxy: 0.30 * county median income (assumed proxy; real lines vary by
    household size). Tag: calibrated to median_hh_income_2023 / poverty_rate_2023,
    proxy threshold assumed.
    """
    median = max(float(median), 1.0)
    line = 0.30 * median
    # solve: Phi((ln(line)-ln(median))/sigma) = poverty_rate  ->  sigma = ln(1/0.3)/(-z)
    from scipy.stats import norm
    p = min(max(float(poverty_rate), 0.02), 0.48)
    z = norm.ppf(p)
    sigma = math.log(1.0 / 0.30) / abs(z)
    return median, sigma


def make_households(fips: str, n: int = 2000, seed: int = 0) -> pd.DataFrame:
    """Return synthetic households: id, x, y (ENU m), income (USD/yr), quintile."""
    rng = np.random.default_rng((int(fips), seed))
    world = ROOT / "worlds"
    cdir = next(world.glob(f"{fips}_*/viewer_data"), None)
    if cdir is None:
        raise FileNotFoundError(f"no viewer_data for fips {fips}")
    b = json.load(open(cdir / "buildings.json"))
    if not b:
        raise RuntimeError(f"no buildings for fips {fips}")
    cent = np.array([[bb["c"][0], bb["c"][1]] for bb in b])
    tland, nations = tribal_mask(fips)
    if tland is not None:   # D-420: no modelled population on tribal land without the nation's request
        from shapely import contains_xy
        keep = ~contains_xy(tland, cent[:, 0], cent[:, 1])
        cent = cent[keep]
        if not len(cent):
            raise RuntimeError(f"{fips}: every building lies on tribal land; no synthetic population (D-420)")
    idx = rng.choice(len(cent), size=min(n, len(cent)), replace=len(cent) < n)
    # jitter within a 25 m radius so households are not exactly on shared centroids
    ang = rng.uniform(0, 2 * math.pi, len(idx))
    rad = rng.uniform(0, 25, len(idx))
    xs = cent[idx, 0] + rad * np.cos(ang)
    ys = cent[idx, 1] + rad * np.sin(ang)

    ar = acs_row(fips)
    if ar is not None:
        income, _ = acs_incomes(ar, len(idx), rng)
        income_tag = ("calibrated (ACS 2020-2024 B19081 quintile means and B19080 limits, "
                      "drawn within MOE; D-104)")
    else:
        row = county_row(fips)
        median = float(row["median_hh_income_2023"])
        pov = float(row["poverty_rate_2023"]) / 100.0
        med, sigma = _calibrate_lognormal(median, pov, rng)
        income = rng.lognormal(mean=math.log(med), sigma=sigma, size=len(idx))
        income_tag = ("calibrated (FALLBACK: lognormal to SAIPE median & poverty; ACS quintiles "
                      "missing for this county; D-104)")

    hh = pd.DataFrame({"hid": [f"{fips}-{i:05d}" for i in range(len(idx))],
                       "x": xs, "y": ys, "income": income})
    qs = pd.qcut(hh["income"], 5, labels=False)
    hh["income_quintile"] = qs + 1
    hh.attrs["provenance"] = {
        "location": "derived (OSM building centroids + jitter)",
        "income": income_tag,
        "income_model": MODEL if ar is not None else "saipe-lognormal-v1 (fallback)",
        "identity": "synthetic — no real persons, no address-level records",
        "tribal_mask": ({"nations": nations, "buildings_removed": "all on tribal land",
                         "income": "county ACS still includes tribal-land households (LR-13 pending): "
                                   "worst-off and lowest-quintile outputs are indeterminate"}
                        if tland is not None else None),
    }
    return hh


# --- D-420: tribal land masked from the synthetic population (D-114) -----------------------
TRIBAL_EDGE_M = 250.0   # same edge rule as tools/engines/ai_infra/tribal.py: shared-line slivers are not tribal land


def _polys(rings):
    from shapely.geometry import Polygon
    out = []
    if rings and isinstance(rings[0][0], (int, float)):
        rings = [rings]
    for r in rings:
        try:
            out.append(Polygon(r).buffer(0))
        except Exception:
            continue
    return out


def tribal_mask(fips: str):
    """(union of tribal land inside the county, nations) in the world's ENU frame, or (None, [])."""
    from shapely.ops import unary_union
    cdir = next((ROOT / "worlds").glob(f"{fips}_*/viewer_data"), None)
    if cdir is None or not (cdir / "boundaries.json").exists():
        return None, []
    b = json.load(open(cdir / "boundaries.json"))
    county = unary_union(_polys(b.get("county_parts") or b.get("county") or []))
    if county.is_empty:
        return None, []
    core = county.buffer(-TRIBAL_EDGE_M)
    inside, nations = [], []
    for t in b.get("tribal") or []:
        u = unary_union(_polys(t.get("rings") if isinstance(t, dict) else t))
        if u.intersection(core).area >= 10_000.0:
            inside.append(u)
            nations.append(t.get("name") if isinstance(t, dict) else "tribal land")
    if not inside:
        return None, []
    return unary_union(inside).intersection(county), nations
