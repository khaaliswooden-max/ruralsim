# validation/backtest/

Back-test of the AI-infrastructure engine (rollout step 2) against rural data centers that were actually built. Rollout step 3; decisions D-200 to D-299.

| File | What it is |
|---|---|
| `PREREGISTRATION.md` | The method, fixed before any run: sites, what counts as "before", comparisons, pass bars, grading. |
| `SITES.md` | Sourced fact sheets for all eleven candidate sites, and why each was or was not selected. |
| `sites.yaml` | Machine-readable inputs (`before:`) and observations (`observed:`), kept apart. The engine reads only `before:`. |
| `tools/eia861_series.py` | Parses EIA-861 annual files 2001–2024 into a per-utility sales and residential price series. |
| `tools/derive_observed.py` | Applies the pre-registered L1 and R1 rules to EIA-861. Writes `observed/observed_values.json`. |
| `observed/` | Derived observed values, the EIA-861 series, and SHA-256 hashes of the source zips. |

Rebuild the observed values (EIA zips from https://www.eia.gov/electricity/data/eia861/, saved as `f861_<year>.zip`):

    python3 tools/eia861_series.py --zips DIR --out observed/eia861_series.csv \
      --utility 7490:OK --utility 13734:OK --utility 10599:OK --utility 15462:OK \
      --utility 13788:OR --utility 14624:WA --utility 13669:AL --utility 16629:AL \
      --utility 16829:AL --utility 18642:AL --utility 14006:OH --years 2001-2024
    python3 tools/derive_observed.py --zips DIR

No runs yet. Every RuralSim result is SPECULATIVE unless it passes this pre-registered method, and public screening runs stay SPECULATIVE.
