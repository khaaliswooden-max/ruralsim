"""Back-test gate and the no-tuning rule (spec rules `backtest_gate`, `no_tuning_on_backtest_sites`).

Any county in validation/backtest/sites.yaml, or on step 3's original candidate list, is
refused unless the run is a declared back-test run. A back-test run additionally needs the
pre-registration committed, and the EIA tables of year T0-1 (PREREGISTRATION.md §4.2.1);
until those exist in R2 the run is blocked, never approximated with 2024 tables.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
BT = ROOT / "validation" / "backtest"

# Step 3 brief candidate list (STEP3_BACKTEST.md), whether or not selected.
BRIEF_CANDIDATES = {
    "40097": "Mayes OK", "19155": "Pottawattamie IA", "37027": "Caldwell NC", "45015": "Berkeley SC",
    "01071": "Jackson AL", "13217": "Newton GA", "47125": "Montgomery TN", "39089": "Licking OH",
    "41013": "Crook OR", "41065": "Wasco OR", "53025": "Grant WA",
}


def backtest_sites() -> dict:
    p = BT / "sites.yaml"
    if not p.exists():
        return {}
    y = yaml.safe_load(p.read_text())
    out = {}
    for key in ("scored_sites", "contrast_sites", "not_selected"):
        for s in y.get(key) or []:
            out[str(s["fips5"])] = s
    return out


def preregistration_commit() -> str | None:
    p = BT / "PREREGISTRATION.md"
    if not p.exists():
        return None
    try:
        return subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%H", "--", str(p)],
                              capture_output=True, text=True, check=True).stdout.strip() or None
    except Exception:
        return None


class Refused(Exception):
    pass


def check(fips5: str, backtest_id: str | None, eia_available) -> dict | None:
    sites = backtest_sites()
    if backtest_id is None:
        if fips5 in sites or fips5 in BRIEF_CANDIDATES:
            raise Refused(f"{fips5} is a back-test site or candidate: engine runs there only as a declared "
                          f"back-test (--backtest SITE_ID) under validation/backtest/PREREGISTRATION.md, and no "
                          f"parameter may be tuned on it")
        return None
    s = next((v for v in sites.values() if v.get("id") == backtest_id), None)
    if s is None or s["fips5"] != fips5:
        raise Refused(f"{backtest_id} is not a registered back-test site for {fips5}")
    commit = preregistration_commit()
    if commit is None:
        raise Refused("PREREGISTRATION.md is not committed")
    year = int(s["T0"]) - 1
    if not eia_available(year):
        raise Refused(f"blocked: EIA-860/861 tables for {year} (T0-1) are not in R2 (eia/{year}/); "
                      f"PREREGISTRATION §4.2.1 forbids substituting 2024")
    return {"site_id": backtest_id, "preregistration_commit": commit, "as_of_year": year}
