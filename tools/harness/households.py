"""Synthetic household population for a pilot county.

GUARDRAIL: synthetic people, never real ones. Households are random points placed on
OSM building centroids (derived locations), with incomes drawn from a lognormal
calibrated only to county-level median household income and poverty rate
(calibrated, from data/county_master.csv). No address-level records are read or
written; outputs are aggregates and deciles only.
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
    idx = rng.choice(len(cent), size=min(n, len(cent)), replace=len(cent) < n)
    # jitter within a 25 m radius so households are not exactly on shared centroids
    ang = rng.uniform(0, 2 * math.pi, len(idx))
    rad = rng.uniform(0, 25, len(idx))
    xs = cent[idx, 0] + rad * np.cos(ang)
    ys = cent[idx, 1] + rad * np.sin(ang)

    row = county_row(fips)
    median = float(row["median_hh_income_2023"])
    pov = float(row["poverty_rate_2023"]) / 100.0
    med, sigma = _calibrate_lognormal(median, pov, rng)
    income = rng.lognormal(mean=math.log(med), sigma=sigma, size=len(idx))

    hh = pd.DataFrame({"hid": [f"{fips}-{i:05d}" for i in range(len(idx))],
                       "x": xs, "y": ys, "income": income})
    qs = pd.qcut(hh["income"], 5, labels=False)
    hh["income_quintile"] = qs + 1
    hh.attrs["provenance"] = {
        "location": "derived (OSM building centroids + jitter)",
        "income": "calibrated (lognormal to county median & poverty rate, ACS 2023)",
        "identity": "synthetic — no real persons, no address-level records",
    }
    return hh
