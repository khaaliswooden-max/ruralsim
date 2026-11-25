# AI-infrastructure screening engine

Spec: `specs/ai_infra_engine.yaml` (D-100). Implementation notes and deviations: D-101.
Modules here: `power_flow`, `rate_impact`, `cooling_water`, `flood`, `fiber`. All five spec modules exist (D-108).

Spec v0.2 (D-111, implemented in D-114):
- `run_proposal.py` runs a proposal card (`specs/proposal_card.md`): `python3 -m tools.engines.ai_infra.run_proposal <PC-yyyy-nnnn.yaml> --seeds 20`. `proposal.py` checks refusals and holds and compiles the card; every option, no build included, runs all five modules.
- Every record carries the structured `not_modelled` block (`not_modelled.py`, core list read from the spec); a record without it is not written.
- `fiscal.py` builds `fiscal_facts` (D-430) for TX and KS from `reference/fiscal_state_facts.yaml` and LR-14.
- `tribal.py` applies D-420: no site on tribal land without the nation's request; tribal-land households masked from lowest-quintile outputs (LR-13).

```
python3 -m venv .venv-ai-infra && . .venv-ai-infra/bin/activate   # its own env (D-103)
pip install -r tools/engines/ai_infra/requirements.txt
python3 -m tools.engines.ai_infra.run EXP-0011 --seeds 20      # writes experiments/ledger/EXP-0011/
python3 -m pytest -q tests/test_ai_infra.py                     # offline
```

To rerun any record made before D-066, set RURALSIM_DATA_BASE=https://data.ruralsim.io; it serves the same files. Those records name the r2.dev URL; it is the same bucket, and every file is still checked against its manifest's sha256 (D-066, docs/R2_SETUP.md).

- `data.py` reads published county snapshots and the national EIA tables from R2, sha256-checked against each manifest.
- `network.py` builds a bus-branch network from observed OSM lines and substations.
- `power_flow.py` runs an N-0 AC power flow (pandapower) per seed, with assumed ratings and impedances drawn by voltage class from the ACTIVSg synthetic grids.
- `rate_impact.py` runs every EIA-861 utility in the county, with observed sales and assumed costs.
- `gate.py` refuses back-test sites and candidates unless a run is a declared back-test, and blocks back-tests until EIA tables of year T0−1 exist.
- `params/assumed.yaml` holds every assumed range. Its sha256 is in every run record.

Every result is SPECULATIVE. Simulated, screening-grade results with assumed parameters. Decision support, not a finding.
