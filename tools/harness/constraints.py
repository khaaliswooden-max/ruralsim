"""Hard-constraint checks from specs/rqli_spec.yaml. Any violation rejects the
portfolio, whatever its mean score. Political-variable exclusion is enforced upstream
in denylist.py at every data load; here we re-verify the indicator set itself.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import denylist, rqli


def check_all(card: dict, base_vals: pd.DataFrame, int_vals: pd.DataFrame,
              base_scores: np.ndarray, int_scores: np.ndarray,
              extra: dict | None = None) -> dict:
    """Return {constraint_id: {passed, note}}. `extra` carries intervention-specific
    numbers (e.g. lowest-quintile rate change)."""
    extra = extra or {}
    res = {}

    # no_loss_of_essential_service
    domains = {d["id"]: d for d in rqli.SPEC["domains"]}
    essential = ["care_access", "power_reliability", "water"]
    worst_drop = 0.0
    for did in essential:
        d = domains[did]
        b = base_vals.apply(lambda r: rqli.domain_score(d, r.to_dict()), axis=1)
        i = int_vals.apply(lambda r: rqli.domain_score(d, r.to_dict()), axis=1)
        mask = b.notna() & i.notna()
        if mask.any():
            drop = float((b[mask] - i[mask]).max())
            worst_drop = max(worst_drop, drop)
    res["no_loss_of_essential_service"] = {
        "passed": bool(worst_drop <= 1e-9),
        "note": f"max per-household essential-domain score drop = {worst_drop:.4f}",
    }

    # protect_lowest_income_quintile
    rate = extra.get("lowest_quintile_rate_change_pct")
    res["protect_lowest_income_quintile"] = {
        "passed": True if rate is None else bool(rate <= 2.0),
        "note": "not modelled by this card" if rate is None else f"lowest-quintile rate change {rate:.2f}%",
    }

    # water_within_recharge
    res["water_within_recharge"] = {
        "passed": True,
        "note": "not modelled: no withdrawal model in this run (cards adding water load must supply one)",
    }

    # no_displacement
    housing = extra.get("max_housing_cost_share_after")
    res["no_displacement"] = {
        "passed": True if housing is None else bool(housing <= 0.30),
        "note": "no housing-cost channel in this card" if housing is None else f"max housing cost share {housing:.3f}",
    }

    # worst_off_decile_must_gain (90% confidence across seeds handled by caller)
    b10 = np.sort(base_scores)[: max(1, len(base_scores) // 10)].mean()
    i10 = np.sort(int_scores)[: max(1, len(int_scores) // 10)].mean()
    res["worst_off_decile_must_gain"] = {
        "passed": bool(i10 >= b10 - 1e-9),
        "note": f"baseline worst-decile {b10:.4f} -> {i10:.4f} (per-seed; 90% CI checked across seeds)",
    }

    # political_variables_excluded: verify no forbidden column leaked into the tables
    denylist.assert_clean_columns(base_vals.columns, context="baseline indicators")
    denylist.assert_clean_columns(int_vals.columns, context="intervention indicators")
    res["political_variables_excluded"] = {
        "passed": True,
        "note": "denylist clean on all indicator tables (files fenced at load time)",
    }
    return res
