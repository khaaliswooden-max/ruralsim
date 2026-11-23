"""Proposal cards, the not_modelled block, fiscal_facts and D-420 masking (spec v0.2, D-111, D-114)."""
import copy
from pathlib import Path

import pytest

pytest.importorskip("pandapower", reason="engine environment (tools/engines/ai_infra/requirements.txt)")
pytest.importorskip("h3")

from tools.engines.ai_infra import fiscal, not_modelled, proposal  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "PC-2026-0000.yaml"


def card():
    c, _ = proposal.load(FIX)
    return c


def test_fixture_compiles_with_no_build_phases_and_unknown_cooling():
    e = proposal.compile_card(card(), "x")
    names = [s["name"] for s in e["scenarios"]]
    assert names[0] == "no_build" and e["scenarios"][0]["no_build"] and e["scenarios"][0]["it_load_mw"] == 0
    assert "as_filed__phase2__evaporative" in names and "phase1_dry" in names
    assert len([n for n in names if n.startswith("as_filed")]) == 6          # 2 phases x 3 cooling types
    assert e["modules"] == proposal.MODULES and e["criterion"]["rate_change_pct_max"] == 2.0
    assert e["proposal_card"]["pending_public_decision"] is True              # under a moratorium (D-400)
    assert e["publication"] == "default"


@pytest.mark.parametrize("mutate,reason", [
    (lambda c: c["options"].pop(0), "no no_build option"),
    (lambda c: c.update(options=c["options"][:1]), "fewer than two options"),
    (lambda c: c["site_default"].update(address="1 Main St"), "public geography only"),
    (lambda c: c["site_default"].update(geography_id="not-a-cell"), "not a valid H3"),
    (lambda c: c["site_default"].update(resolution="parcel"), "not supported"),
    (lambda c: c["criteria"].update(worst_off_not_worse_off=False), "cannot be turned off"),
    (lambda c: c["options"][2].update(ticked_by_submitter=False), "did not tick"),
    (lambda c: c["criteria"].update(objective="maximise votes"), "political variable"),
    (lambda c: c["submitter"].update(name="A Person"), "private intake record"),
])
def test_refusals_name_the_reason_and_never_patch(mutate, reason):
    c = copy.deepcopy(card())
    mutate(c)
    with pytest.raises(proposal.Refused) as e:
        proposal.compile_card(c, "x")
    assert any(reason in r for r in e.value.reasons)


def test_backtest_county_is_held(monkeypatch):
    monkeypatch.setattr(proposal.gate, "backtest_run_recorded", lambda f=None: False)
    assert proposal.holds("40097") == ["held_backtest_gate"]
    assert proposal.holds("20019") == []
    monkeypatch.setattr(proposal.gate, "backtest_run_recorded", lambda f=None: True)
    assert proposal.holds("40097") == []


def test_not_modelled_core_cannot_be_shortened_and_validation_refuses_records_without_it():
    core = not_modelled.core()
    assert len(core) == 14 and any("fiscal impact" in e["topic"] for e in core)
    b = not_modelled.block([not_modelled.entry("x", "blocked_this_run")])
    assert len(b) == 15
    not_modelled.validate({"not_modelled": b})
    with pytest.raises(not_modelled.Invalid):
        not_modelled.validate({"not_modelled": []})
    with pytest.raises(not_modelled.Invalid):
        not_modelled.validate({"not_modelled": b[1:]})                   # a core topic removed
    assert "## Not modelled" in not_modelled.markdown(b)


def test_fiscal_facts_ks_and_null_elsewhere(monkeypatch):
    monkeypatch.setattr(fiscal.data, "fiscal_table", lambda st, t: None)
    f, ent = fiscal.build("20019", "KS")
    assert f["state"] == "KS" and f["dollar_figures"] == "none (D-430)" and len(f["questions_to_demand"]) == 8
    assert f["taxing_units"] is None and len(ent) == 2                   # LR-14 not in R2: listed, not hidden
    assert "absence is not evidence" in f["local_agreements_found"]["label"]
    f, ent = fiscal.build("01131", "AL")
    assert f is None and "not yet built" in ent[0]["topic"]
