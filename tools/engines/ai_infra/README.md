# AI-infrastructure screening engine

Spec: `specs/ai_infra_engine.yaml` (D-100). Implementation notes and deviations: D-101.
Modules here: `power_flow` and `rate_impact`. Cooling water, fiber and flood are later PRs.

```
python3 -m venv .venv-ai-infra && . .venv-ai-infra/bin/activate   # its own env (D-103)
pip install -r tools/engines/ai_infra/requirements.txt
python3 -m tools.engines.ai_infra.run EXP-0011 --seeds 20      # writes experiments/ledger/EXP-0011/
python3 -m pytest -q tests/test_ai_infra.py                     # offline
```

- `data.py` reads published county snapshots and the national EIA tables from R2, sha256-checked against each manifest.
- `network.py` builds a bus-branch network from observed OSM lines and substations.
- `power_flow.py` runs an N-0 AC power flow (pandapower) per seed, with assumed ratings and impedances drawn by voltage class from the ACTIVSg synthetic grids.
- `rate_impact.py` runs every EIA-861 utility in the county, with observed sales and assumed costs.
- `gate.py` refuses back-test sites and candidates unless a run is a declared back-test, and blocks back-tests until EIA tables of year T0−1 exist.
- `params/assumed.yaml` holds every assumed range. Its sha256 is in every run record.

Every result is SPECULATIVE. Simulated, screening-grade results with assumed parameters. Decision support, not a finding.
