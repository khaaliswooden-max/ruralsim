"""The worst-off constraint is emitted under its new id with unchanged logic (D-105)."""
import numpy as np
import pandas as pd
import yaml

from tools.harness import constraints


def _check(base, after):
    vals = pd.DataFrame({"minutes_to_emergency_care": np.ones(len(base))})
    return constraints.check_all({"id": "EXP-TEST"}, vals, vals.copy(), np.array(base), np.array(after))


def test_new_id_only_and_logic_unchanged():
    base = np.linspace(0.1, 1.0, 50)
    same = _check(base, base)
    assert "worst_off_decile_not_worse_off" in same and "worst_off_decile_must_gain" not in same
    assert same["worst_off_decile_not_worse_off"]["passed"]          # unchanged counts as not worse off
    worse = base.copy()
    worse[np.argsort(base)[:5]] -= 0.05                               # lower the bottom tenth
    assert not _check(base, worse)["worst_off_decile_not_worse_off"]["passed"]


def test_spec_records_former_id():
    spec = yaml.safe_load(open("specs/rqli_spec.yaml"))
    c = next(c for c in spec["hard_constraints"] if c["id"] == "worst_off_decile_not_worse_off")
    assert c["former_ids"] == ["worst_off_decile_must_gain"]
