"""Proposal-card intake (spec v0.2 `proposal_card_intake`, specs/proposal_card.md; D-111, D-114).

A proposal card is the community's question. This module checks a card against the refusals and
holds in the spec and compiles it into the existing card format: each option (and each variant an
option implies: phases, an unknown cooling type) becomes one entry of `scenarios`, and no build
becomes a scenario with no site, on the same seed streams as every other option. No module output
is renamed and no parameter changes.

Refusals give the reason and run nothing. A card is never patched silently.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import h3
import yaml

from tools.engines.ai_infra import gate

MODULES = ["power_flow", "rate_impact", "cooling_water", "flood", "fiber"]
COOLING = ("evaporative", "adiabatic_hybrid", "dry")
ALLOCATIONS = ("direct_assignment", "large_load_tariff", "socialized")
FORBIDDEN_SITE_KEYS = {"address", "street", "street_address", "parcel", "parcel_id", "parcel_number", "apn",
                       "owner", "owner_name", "landowner", "lat", "lon", "latitude", "longitude"}
POLITICAL = re.compile(r"\b(party|partisan|vote[sd]?|voter|election|democrat\w*|republican\w*|ballot|turnout)\b", re.I)
DEFAULT_CRITERIA = {"grid_clean_seed_share": 0.9, "rate_change_pct_max": 2.0,
                    "peak_day_share_of_low_flow_max": 0.10, "annual_share_of_public_supply_max": 0.10,
                    "footprint_share_sfha_max": 0.10, "nearest_fiber_hex_km_max": 5.0,
                    "county_fiber_providers_min": 2}
ROLES = {"county_staff", "elected_official", "resident", "community_group", "school_or_hospital_district",
         "tribal_government", "utility_or_coop", "applicant_or_developer", "other"}


class Refused(Exception):
    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


class Held(Exception):
    pass


def load(path) -> tuple[dict, str]:
    raw = Path(path).read_bytes()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()


def _walk_keys(x, prefix=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield f"{prefix}{k}", k, v
            yield from _walk_keys(v, f"{prefix}{k}.")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _walk_keys(v, f"{prefix}{i}.")


def site_of(card, option) -> dict:
    s = option.get("site") or card.get("site_default") or {}
    return {"resolution": s.get("resolution"), "geography_id": s.get("geography_id"),
            "location_basis": s.get("location_basis")}


def validate(card) -> list[str]:
    """Reasons to refuse, in the spec's order. Empty means the card may compile."""
    why = []
    if not re.fullmatch(r"PC-\d{4}-\d{4}", str(card.get("card_id", ""))):
        why.append("card_id must be PC-<yyyy>-<nnnn>")
    if card.get("run_kind") != "proposal_card":
        why.append("run_kind must be proposal_card")
    opts = card.get("options") or []
    nb = [o for o in opts if o.get("is_no_build")]
    if len(opts) < 2:
        why.append("fewer than two options")
    if len(nb) != 1:
        why.append("no no_build option" if not nb else "more than one no_build option")
    ids = [o.get("option_id") for o in opts]
    if len(set(ids)) != len(ids) or any(not isinstance(i, str) or "__" in i for i in ids):
        why.append("option_id values must be unique strings without '__'")
    for o in opts:
        if o.get("suggested_by") == "ruralsim" and not o.get("ticked_by_submitter"):
            why.append(f"option {o.get('option_id')} is a suggestion the submitter did not tick")
        if not o.get("is_no_build") and not isinstance(o.get("it_load_mw"), (int, float)):
            why.append(f"option {o.get('option_id')} has no it_load_mw")
    for path, k, _ in _walk_keys({kk: vv for kk, vv in card.items() if kk not in ("stated_not_checked", "decision")}):
        if str(k).lower() in FORBIDDEN_SITE_KEYS:
            why.append(f"an address, parcel, owner or point coordinate was given ({path}); sites are public geography only")
    for o in opts:
        if o.get("is_no_build"):
            continue
        s = site_of(card, o)
        if s["resolution"] != "h3_r8":
            why.append(f"option {o.get('option_id')}: site resolution {s['resolution']!r} is not supported by engine "
                       "v0.2; give an H3 resolution-8 cell (block groups and PLSS sections need geometry layers not in R2)")
        elif not (isinstance(s["geography_id"], str) and h3.is_valid_cell(s["geography_id"])
                  and h3.get_resolution(s["geography_id"]) == 8):
            why.append(f"option {o.get('option_id')}: {s['geography_id']!r} is not a valid H3 resolution-8 cell")
    crit = card.get("criteria") or {}
    if crit.get("worst_off_not_worse_off") is not True:
        why.append("the worst-off rule cannot be turned off (worst_off_not_worse_off must be true)")
    if crit.get("set_by") not in ("ruralsim_defaults", "submitter", "mixed"):
        why.append("criteria.set_by must be ruralsim_defaults, submitter or mixed")
    for path, k, v in _walk_keys({"criteria": crit, "objective": card.get("objective")}):
        if POLITICAL.search(str(k)) or (isinstance(v, str) and POLITICAL.search(v)):
            why.append(f"political variable in an objective ({path}); denylisted (D-007)")
    sub = card.get("submitter") or {}
    if sub.get("role") not in ROLES:
        why.append("submitter.role is missing or not one of the template's roles")
    if "name" in sub or "email" in sub or "phone" in sub:
        why.append("submitter contact details belong in the private intake record, never in the card")
    return why


def holds(fips5) -> list[str]:
    """held_backtest_gate until step 3's first back-test run is recorded (PREREGISTRATION §8)."""
    if (fips5 in gate.backtest_counties() or fips5 in gate.BRIEF_CANDIDATES) and not gate.backtest_run_recorded(fips5):
        return ["held_backtest_gate"]
    return []


def pending_public_decision(decision) -> bool:
    """D-400's trigger, read from the card's decision block: a proposal filed with or on the agenda
    of a public body that will act on it (application filed, hearing scheduled), or a moratorium
    adopted or under study. An explicit pending_public_decision in the block wins."""
    if "pending_public_decision" in decision:
        return bool(decision["pending_public_decision"])
    return (decision.get("stage") in ("application_filed", "hearing_scheduled", "under_moratorium")
            or decision.get("kind") == "moratorium_study")


def compile_card(card, sha256) -> dict:
    """The engine card. Refuses (raises Refused) rather than patch anything."""
    why = validate(card)
    if why:
        raise Refused(why)
    fips5 = str(card["decision"]["county_fips5"])
    crit = {**DEFAULT_CRITERIA, **{k: v for k, v in (card.get("criteria") or {}).items()
                                   if k in DEFAULT_CRITERIA}}
    scenarios, options = [], []
    for o in card["options"]:
        oid = o["option_id"]
        if o.get("is_no_build"):
            scenarios.append({"name": "no_build", "option_id": oid, "no_build": True, "it_load_mw": 0.0})
            options.append({"option_id": oid, "label": o.get("label", "No build"), "is_no_build": True,
                            "scenario_name": ["no_build"]})
            continue
        site = site_of(card, o)
        loads = ([(f"phase{p['phase']}", p["it_load_mw_cumulative"]) for p in o["phases"]] if o.get("phases")
                 else [(None, o["it_load_mw"])])
        cool = o.get("cooling") or "unknown"
        cools = list(COOLING) if cool == "unknown" else [cool]
        alloc = o.get("cost_allocation") or "unknown"
        names = []
        for ph, mw in loads:
            for c in cools:
                parts = [oid] + ([ph] if ph else []) + ([c] if len(cools) > 1 else [])
                name = "__".join(parts)
                names.append(name)
                scenarios.append({"name": name, "option_id": oid, "it_load_mw": float(mw), "cooling": c,
                                  "onsite": {k: v for k, v in (o.get("onsite") or {}).items()
                                             if k in ("solar_mw", "storage_mwh", "firm_mw") and v},
                                  "allocations": list(ALLOCATIONS) if alloc == "unknown" else [alloc],
                                  "site": site, "phase": ph,
                                  "water_source": o.get("water_source"), "backup_generation": o.get("backup_generation")})
        options.append({"option_id": oid, "label": o.get("label"), "is_no_build": False, "scenario_name": names,
                        "suggested_by": o.get("suggested_by"), "site": site})
    sub = card.get("submitter") or {}
    return {
        "id": card["card_id"], "run_kind": "proposal_card", "modules": MODULES, "counties": [fips5],
        "seeds": int(card.get("seeds", 20)), "criterion": crit, "scenarios": scenarios, "options": options,
        "proposal_card": {"card_id": card["card_id"], "card_version": card.get("card_version", 1),
                          "card_sha256": sha256, "submitter_role": sub.get("role"),
                          "financial_interest": sub.get("financial_interest"),
                          "bars_set_by": (card.get("criteria") or {}).get("set_by"),
                          "pending_public_decision": pending_public_decision(card.get("decision") or {})},
        "publication": "nation_terms" if sub.get("role") == "tribal_government" else "default",
        "submitter_nation_geoids": sub.get("nation_geoids") or [],
        "submitter_verified": bool(sub.get("verified")),
        "decision": card.get("decision"), "county_rules": card.get("county_rules"),
        "stated_not_checked": card.get("stated_not_checked"),
    }
