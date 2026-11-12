"""RQLI computation per specs/rqli_spec.yaml.

Hard rules baked in:
- report the DISTRIBUTION (p10/p50/p90/mean) plus worst-off decile mean — never a mean alone
- weighted geometric mean across domains (a zero in one domain cannot be bought back)
- every indicator value carries a provenance tag; the RQLI floor tag is the weakest input
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

SPEC = yaml.safe_load(open(Path(__file__).resolve().parents[2] / "specs" / "rqli_spec.yaml"))
TAG_RANK = ["observed", "derived", "calibrated", "assumed", "hypothetical"]


def score_indicator(ind: dict, x: float) -> float:
    """Linear map floor->0, target->1, clipped. Works for both directions."""
    f, t = ind["floor"], ind["target"]
    if f == t:
        return 1.0 if x == t else 0.0
    s = (x - f) / (t - f)
    return float(min(1.0, max(0.0, s)))


def domain_score(domain: dict, values: dict[str, float]) -> float | None:
    """Geometric mean of available indicator scores; None if no indicator available."""
    scores = []
    for ind in domain["indicators"]:
        v = values.get(ind["id"])
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        scores.append(max(score_indicator(ind, v), 1e-6))
    if not scores:
        return None
    return float(np.exp(np.mean(np.log(scores))))


def rqli(values: dict[str, float]) -> tuple[float, list[str], list[str]]:
    """Return (score, domains_used, domains_missing)."""
    used, missing, parts, weights = [], [], [], []
    for d in SPEC["domains"]:
        s = domain_score(d, values)
        if s is None:
            missing.append(d["id"])
        else:
            used.append(d["id"])
            parts.append(math_log := np.log(max(s, 1e-6)))
            weights.append(d["weight"])
    if not parts:
        return float("nan"), used, missing
    w = np.array(weights) / np.sum(weights)
    return float(np.exp(np.dot(w, parts))), used, missing


def distribution_report(scores: np.ndarray) -> dict:
    """The ONLY allowed way to report RQLI. Never a mean alone."""
    s = np.asarray(scores, dtype=float)
    s = s[~np.isnan(s)]
    if len(s) == 0:
        return {"n": 0}
    order = np.sort(s)
    k = max(1, len(s) // 10)
    return {
        "n": int(len(s)),
        "p10": float(np.percentile(s, 10)),
        "p50": float(np.percentile(s, 50)),
        "p90": float(np.percentile(s, 90)),
        "mean": float(np.mean(s)),
        "worst_off_decile_mean": float(np.mean(order[:k])),
    }


def weakest_tag(tags) -> str:
    """Weakest provenance among tag strings like 'derived + assumed (...)' — any tag
    vocabulary word found in the string contributes at its rank."""
    worst = None
    for t in tags:
        words = [w for w in TAG_RANK if w in str(t).lower()]
        if not words:
            words = ["assumed"]
        for w in words:
            if worst is None or TAG_RANK.index(w) > TAG_RANK.index(worst):
                worst = w
    return worst or "assumed"


def constraints() -> list[dict]:
    return SPEC["hard_constraints"]


def promotion_rule() -> dict:
    return SPEC["promotion_rule"]
