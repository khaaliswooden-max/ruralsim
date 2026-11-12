"""Political-variable fence (hard constraint `political_variables_excluded`, DECISIONS.md D-007).

Election/party tables are read-only governance context. This module is the code-level
denylist: any attempt to load them as model input, or any dataframe/dict containing a
forbidden column, raises HarnessConstraintError. Convention is not enough; this runs on
every harness input load.
"""
from __future__ import annotations

FORBIDDEN_FILES = {
    "county_election.csv",
    "state_decade_power.csv",
    "national_power_summary.csv",
}
FORBIDDEN_PREFIXES = ("pres_margin_rd_",)
FORBIDDEN_EXACT = {
    "county_election", "state_decade_power", "national_power_summary",
    "party", "votes_dem", "votes_rep", "votes_gop", "margin_rd",
}


class HarnessConstraintError(RuntimeError):
    """Raised when a hard constraint is violated at the input or output boundary."""


def _bad(col: str) -> bool:
    c = str(col).strip().lower()
    if c in FORBIDDEN_EXACT:
        return True
    return any(c.startswith(p) for p in FORBIDDEN_PREFIXES)


def assert_clean_columns(columns, context: str = "") -> None:
    hits = [c for c in columns if _bad(c)]
    if hits:
        raise HarnessConstraintError(
            f"political_variables_excluded violated: forbidden column(s) {hits} in {context or 'input'}"
        )


def assert_clean_file(path: str, context: str = "") -> None:
    import os
    base = os.path.basename(str(path))
    if base in FORBIDDEN_FILES:
        raise HarnessConstraintError(
            f"political_variables_excluded violated: {base} may not be loaded as model input "
            f"({context or 'unspecified context'}). It is read-only governance context."
        )
