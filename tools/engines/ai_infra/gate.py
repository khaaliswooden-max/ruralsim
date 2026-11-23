"""Back-test gate and the no-tuning rule (spec rules `backtest_gate`, `no_tuning_on_backtest_sites`).

Any county in a back-test site file (validation/backtest/sites.yaml for v1,
validation/backtest/v2/sites.yaml for v2, D-207), or on step 3's original candidate list, is
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


# Each back-test version: its site file and its pre-registration (D-207 adds v2).
VERSIONS = {"v1": BT, "v2": BT / "v2"}


def backtest_sites() -> dict:
    """Every registered back-test site of every version, keyed by site id (a county can appear in
    more than one version: Crook OR is v1 not_selected and V2-01). Each carries `_version`."""
    out = {}
    for ver, d in VERSIONS.items():
        p = d / "sites.yaml"
        if not p.exists():
            continue
        y = yaml.safe_load(p.read_text()) or {}
        for key in ("scored_sites", "contrast_sites", "not_selected"):
            for s in y.get(key) or []:
                s = {**s, "fips5": str(s["fips5"]), "_version": ver, "_list": key}
                out[s.get("id") or f"{ver}:{s['fips5']}"] = s
    return out


def backtest_counties() -> set:
    return {s["fips5"] for s in backtest_sites().values()}


def preregistration_commit(version: str = "v1") -> str | None:
    p = VERSIONS[version] / "PREREGISTRATION.md"
    if not p.exists():
        return None
    try:
        return subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%H", "--", str(p)],
                              capture_output=True, text=True, check=True).stdout.strip() or None
    except Exception:
        return None


def backtest_run_recorded(fips5: str | None = None) -> bool:
    """True once a back-test run is recorded (PREREGISTRATION §8 freezes it then). With fips5:
    only a run of a version that registers that county counts, so v1's run does not release a
    v2 county (D-115)."""
    import json
    sites = backtest_sites()
    vers = {t["_version"] for t in sites.values() if t["fips5"] == fips5} if fips5 else set()
    # a brief candidate in no version is released by any recorded back-test run, as before
    ids = None if not vers else {sid for sid, s in sites.items() if s["_version"] in vers}
    for p in (ROOT / "experiments" / "ledger").glob("*/*.json"):
        try:
            r = json.loads(p.read_text())
        except Exception:
            continue
        for c in r.get("counties", []):
            sid = ((c or {}).get("backtest") or {}).get("site_id")
            if sid and (ids is None or sid in ids):
                return True
    return False


DEFAULT_MASK_RADIUS_M = 2000.0   # v1 §4.2.2; v2 §4.2 also runs 0 m (owner-tagged only) per run


class Refused(Exception):
    pass


def check(fips5: str, backtest_id: str | None, eia_available) -> dict | None:
    sites = backtest_sites()
    if backtest_id is None:
        if fips5 in backtest_counties() or fips5 in BRIEF_CANDIDATES:
            raise Refused(f"{fips5} is a back-test site or candidate: engine runs there only as a declared "
                          f"back-test (--backtest SITE_ID) under its version's PREREGISTRATION.md, and no "
                          f"parameter may be tuned on it")
        return None
    s = sites.get(backtest_id)
    if s is None or s["fips5"] != fips5:
        raise Refused(f"{backtest_id} is not a registered back-test site for {fips5}")
    if s.get("refused"):
        r = s["refused"]
        raise Refused(f"{backtest_id} is refused under {r.get('by')}: {r.get('reason')}. {r.get('scoring', '')}".strip())
    commit = preregistration_commit(s["_version"])
    if commit is None:
        raise Refused(f"{s['_version']} PREREGISTRATION.md is not committed")
    year = int(s["T0"]) - 1
    if not eia_available(year):
        raise Refused(f"blocked: EIA-860/861 tables for {year} (T0-1) are not in R2 (eia/{year}/); "
                      f"PREREGISTRATION §4.2.1 forbids substituting 2024")
    # PREREGISTRATION §4.2.2: the site mask needs the site location and the names to mask by.
    # sites.yaml (step 3) must give both; without them a run would be unmasked, so it is refused.
    pt, terms = s.get("site_point"), s.get("mask_owner_terms")
    if not (isinstance(pt, (list, tuple)) and len(pt) == 2) or not terms:
        raise Refused(f"blocked: validation/backtest/sites.yaml gives {backtest_id} no site_point [lon, lat] "
                      f"and/or mask_owner_terms; the §4.2.2 site mask cannot be applied without them")
    return {"site_id": backtest_id, "version": s["_version"], "preregistration_commit": commit, "as_of_year": year,
            "site_point": [float(pt[0]), float(pt[1])], "mask_owner_terms": [str(t) for t in terms],
            "mask_radius_m": DEFAULT_MASK_RADIUS_M,
            "cooling": s.get("cooling"),          # per-site design (v2 §5.4); None means W1 is not run
            # §4.2.2: a feature stays if a dated source shows it existed before T0 (listed by step 3)
            "mask_keep_osm_ids": [str(i) for i in (s.get("mask_keep_osm_ids") or [])]}
