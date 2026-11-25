# validation/backtest/v2/

Back-test v2 (D-207). It uses three held-out rural sites and fixes the three rules that left v1's comparisons unscored. v1 (`../`) is frozen; its results are in `../RESULTS_2026-11-22.md`.

| File | What it is |
|---|---|
| `PREREGISTRATION.md` | The v2 method, fixed before any run. Sites, inputs, the bounded site mask, load sources, bars, grading, and what can reach PLAUSIBLE. |
| `SITES.md` | Sourced fact sheets for V2-01 Crook OR, V2-02 Rutherford NC and V2-03 Morrow OR, and the candidates that failed. |
| `sites.yaml` | Inputs (`before:`, site point, mask terms, load, cooling) and observations (`observed:`). |
| `tools/derive_observed_v2.py` | Observed loads and R1 values from EIA-861 and the operator disclosures. State-filtered, Parts A+B, with the detectability test. |
| `observed/observed_values.json` | Its output. |
| `RESULTS_2026-11-24.md` / `.json` | Results (D-211), misses first. Read §5 before citing G1. |
| `tools/write_results_md_v2.py` | Renders the results file from the JSON. |
| `runs/<run id>/` | Each run's log and commit context from the GitHub runner. |
| `tools/score_run_v2.py` | The scorer (D-210), committed before any run. It refuses to score a run whose data host is not `https://data.ruralsim.io` or whose engine differs from the frozen one. |

    python3 tools/derive_observed_v2.py --zips DIR    # DIR holds f861_<year>.zip, 2001-2024 (hashes in ../observed/)

Run 2026-11-24 on the GitHub "Back-test run" workflow (D-209), under the run plan D-210. v2 is frozen. W1 and R1 are SPECULATIVE. G1 is PLAUSIBLE by the registered rule, but that grade carries no evidence (D-211). Every result is SPECULATIVE unless it passes this method. Public screening runs stay SPECULATIVE.
