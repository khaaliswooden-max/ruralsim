"""fiscal_facts (D-430, option F1; spec v0.2 output_schema.fiscal_facts; D-114).

Public facts only, provenance observed, no grade, no dollar figure. No revenue, incentive value,
service cost or net figure is computed: a revenue screen (F2) needs a published fiscal back-test
first, and F3 is never a free public screen.

Built for Texas and Kansas first. State-level law comes from reference/fiscal_state_facts.yaml;
per-county taxing units and local agreements come from LR-14. Elsewhere the block is null and the
run lists that under not_modelled.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from tools.engines.ai_infra import data, not_modelled

REF = Path(__file__).resolve().parent / "reference" / "fiscal_state_facts.yaml"
AGREEMENTS_LABEL = "found in public registries; absence is not evidence there is none"


@lru_cache(maxsize=1)
def reference() -> dict:
    return yaml.safe_load(REF.read_text())


def build(fips5: str, state: str) -> tuple[dict | None, list[dict]]:
    """(fiscal_facts or None, not_modelled entries to append)."""
    ref = reference()
    st = ref["states"].get(state)
    if st is None:
        return None, [not_modelled.entry(
            f"fiscal_facts not yet built for this state ({state})", "not_observed",
            why="D-430 builds public tax facts for Texas and Kansas first",
            who_can_answer="county appraisal district or assessor; state revenue department")]
    entries = []
    units = data.fiscal_table(state, "taxing_units")
    agreements = data.fiscal_table(state, "local_agreements")
    tu = None
    if units is not None:
        x = units[units.fips5 == fips5]
        tu = [{k: (None if v != v else v) for k, v in r.items() if k != "fips5"} for r in x.to_dict("records")]
    else:
        entries.append(not_modelled.entry(
            "fiscal_facts: taxing-unit rates and levies for this county", "not_observed",
            why=f"LR-14 table fiscal/{state}/taxing_units.parquet not in R2 yet",
            who_can_answer="county appraisal district or clerk; state comptroller or revenue department"))
    la = None
    if agreements is not None:
        x = agreements[agreements.fips5 == fips5]
        la = {"label": AGREEMENTS_LABEL,
              "items": [{k: (None if v != v else v) for k, v in r.items() if k != "fips5"} for r in x.to_dict("records")]}
    else:
        entries.append(not_modelled.entry(
            "fiscal_facts: local agreements (abatements, PILOTs, development agreements) for this county", "not_observed",
            why=f"LR-14 table fiscal/{state}/local_agreements.parquet not in R2 yet; registries to search are listed",
            who_can_answer="county clerk; state registries named in fiscal_facts.local_agreement_registries"))
    facts = {
        "provenance": "observed", "grade": None, "dollar_figures": "none (D-430)",
        "retrieved": ref["retrieved"], "state": state,
        "taxing_units": tu,
        "state_taxes_business_personal_property": st["state_taxes_business_personal_property"],
        "state_sales_tax_exemptions_for_data_centers": st["state_sales_tax_exemptions_for_data_centers"],
        "local_agreements_found": la if la is not None else {"label": AGREEMENTS_LABEL, "items": None},
        "local_agreement_registries": st.get("local_agreement_registries", []),
        "questions_to_demand": list(ref["questions_to_demand"]),
    }
    return facts, entries
