"""The structured "not modelled" block every record carries (spec v0.2, D-111).

The core list is fixed: it comes from `specs/ai_infra_engine.yaml` (output_schema.not_modelled_core)
and is read from there, so a card, a client or a layout cannot shorten it. Runs append entries
(blocked inputs, validity limits, tribal-land masking, a missing fiscal_facts block); they never
remove one. A record whose block is missing, empty or short of a core topic fails `validate()`
and is not written to the ledger.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

SPEC = Path(__file__).resolve().parents[3] / "specs" / "ai_infra_engine.yaml"
STATUSES = ("not_modelled", "not_observed", "indeterminate_every_run", "blocked_this_run")


class Invalid(Exception):
    pass


@lru_cache(maxsize=1)
def core() -> tuple:
    spec = yaml.safe_load(SPEC.read_text())
    out = []
    for e in spec["output_schema"]["not_modelled_core"]:
        out.append({"topic": e["topic"], "status": e["status"], "why": e.get("why") or e.get("note"),
                    "who_can_answer": e.get("who_can_answer"), "applies_to": "all options"})
    if not out:
        raise Invalid("spec has an empty not_modelled_core")
    return tuple(out)


def entry(topic, status, why=None, who_can_answer=None, applies_to="all options"):
    if status not in STATUSES:
        raise ValueError(status)
    return {"topic": topic, "status": status, "why": why, "who_can_answer": who_can_answer, "applies_to": applies_to}


def block(extra=()) -> list[dict]:
    """Core list in spec order, then the run's own entries (deduplicated by topic)."""
    out = [dict(e) for e in core()]
    seen = {e["topic"] for e in out}
    for e in extra:
        if e["topic"] not in seen:
            out.append(e)
            seen.add(e["topic"])
    return out


def validate(record: dict) -> None:
    nm = record.get("not_modelled")
    if not isinstance(nm, list) or not nm:
        raise Invalid("record has no not_modelled block (D-111): not written")
    topics = {e.get("topic") for e in nm if isinstance(e, dict)}
    missing = [e["topic"] for e in core() if e["topic"] not in topics]
    if missing:
        raise Invalid(f"not_modelled block is missing core topics (D-111): {missing}")
    for e in nm:
        if e.get("status") not in STATUSES:
            raise Invalid(f"not_modelled entry has an unknown status: {e}")


def markdown(nm: list[dict]) -> str:
    """The block as a summary section, in full."""
    lines = ["## Not modelled", ""]
    for e in nm:
        s = f"- **{e['topic']}** ({e['status'].replace('_', ' ')})"
        if e.get("why"):
            s += f". {e['why']}"
        if e.get("who_can_answer"):
            s += f". Who can answer: {e['who_can_answer']}"
        if e.get("applies_to") and e["applies_to"] != "all options":
            s += f". Applies to: {', '.join(e['applies_to'])}"
        lines.append(s + ".")
    return "\n".join(lines) + "\n"
