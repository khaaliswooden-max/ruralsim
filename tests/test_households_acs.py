"""Household incomes calibrated to ACS quintiles (D-104). Offline: uses the committed ACS copy."""
import numpy as np
import pandas as pd

from tools.harness import households as H


def _row(**kw):
    base = {"mean_q1": 8000, "mean_q2": 20000, "mean_q3": 40000, "mean_q4": 65000, "mean_q5": 150000,
            "upper_q1": 13000, "upper_q2": 30000, "upper_q3": 52000, "upper_q4": 85000}
    base.update(kw)
    return pd.Series({**base, **{k + "_moe": 0.0 for k in base}})


def test_quintile_means_and_bands_match_acs_without_moe():
    inc, d = H.acs_incomes(_row(), 50000, np.random.default_rng(0))
    q = np.sort(inc)
    fifths = np.array_split(q, 5)
    for k, part in enumerate(fifths):
        assert abs(part.mean() / [8000, 20000, 40000, 65000, 150000][k] - 1) < 0.03
    assert q[len(q) // 5 - 1] <= 13000 + 1 and q.min() >= 0


def test_moe_draws_are_repaired_to_valid_bands():
    r = _row(mean_q1=12900)              # mean almost at its upper limit
    r["upper_q1_moe"] = 5000.0           # limits may cross when drawn
    for s in range(50):
        lo, u, m = H._draw_acs(r, np.random.default_rng(s))
        assert u == sorted(u)
        assert all(lo[k] < m[k] < u[k] for k in range(4)) and m[4] > u[3]


def test_pilot_uses_acs_and_missing_county_falls_back():
    hh = H.make_households("01131", n=500, seed=0)
    assert hh.attrs["provenance"]["income_model"] == H.MODEL
    assert H.acs_row("99999") is None
