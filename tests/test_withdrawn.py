"""D-421: withdrawn cards are left out of the site build and refused by the harness (D-420)."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GONE = {"EXP-0004", "EXP-0009"}


def _build_site():
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "tools" / "build_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_registry_lists_both_thurston_cards_with_the_d421_notice():
    w = json.loads((ROOT / "experiments" / "WITHDRAWN.json").read_text())
    assert {x["card"] for x in w["withdrawn"]} == GONE
    assert w["notice"] == ("Two runs withdrawn: they ran on Omaha and Winnebago reservation land "
                           "without the nations' request.")
    for cid in GONE:
        assert (ROOT / "experiments" / "ledger" / cid / "WITHDRAWN.md").exists()
        assert any((ROOT / "experiments" / "ledger" / cid).glob("*_20seeds.json")), "ledger files stay"


def test_site_build_leaves_withdrawn_cards_out():
    bs = _build_site()
    cards = bs.build_experiments(bs.build_pilots(bs.county_dirs()))
    ids = {c["id"] for c in cards}
    assert not ids & GONE
    assert len(cards) == 8
    assert "31173" not in {c["fips"] for c in cards}


def test_harness_refuses_withdrawn_card():
    r = subprocess.run([sys.executable, "tools/harness/run_experiment.py", "EXP-0004", "--seeds", "1"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode != 0 and "D-421" in r.stderr
    assert not any((ROOT / "experiments" / "ledger" / "EXP-0004").glob("*_1seeds.json"))
