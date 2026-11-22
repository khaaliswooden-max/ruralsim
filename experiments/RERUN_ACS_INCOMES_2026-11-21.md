# Seed cards rerun on ACS incomes, 2026-11-21 (D-104)

All ten seed cards were rerun at 20 seeds after `tools/harness/households.py` switched from a SAIPE-calibrated lognormal to the county's ACS 2020–2024 income quintiles (B19081 means, B19080 limits, drawn inside their margins of error). The old records stay in the ledger. The site shows the latest 20-seed run of each card, so these replace the published ones when this change merges.

Grade: **SPECULATIVE**. Simulated, screening-grade results with assumed parameters. Decision support, not a finding.

## What changed, and what did not

- **Verdicts: unchanged.** 4 met (0002, 0003, 0006, 0008), 5 not met (0001, 0004, 0005, 0007, 0009), 1 conditional (0010).
- **Constraint results: unchanged** on every card, seed by seed. EXP-0001 still fails `no_loss_of_essential_service` in 9 seeds and `worst_off_decile_must_gain` in all 20. EXP-0007 still fails `protect_lowest_income_quintile` in all 20.
- **Primary metrics: unchanged**, seed by seed, on 9 of 10 cards. Income does not enter them.
- **One exception, EXP-0002.** Its bandwidth-excluded share by income quintile changed, because new income draws put different synthetic households in each quintile. It is still flat across quintiles: about 10% in each, before and after (mean over seeds: old 10.5 / 10.3 / 10.5 / 9.7 / 10.7%, new 10.4 / 9.7 / 10.0 / 10.8 / 10.9%).
- **RQLI distributions changed on every card**, in the direction the income error predicts:
  - Up in the four high-poverty counties, where the old model made poor households far poorer than ACS (bottom-quintile mean 0.09× ACS in McDowell, 0.17× in Wilcox).
  - Down in Teton, where it made them richer (1.23×).

| Card | County | Verdict (old → new) | Baseline RQLI p10 | Baseline p50 | Baseline worst-off decile | Intervention worst-off decile |
|---|---|---|---|---|---|---|
| EXP-0001 | McDowell WV | not met → not met | 0.0134 → 0.0213 | 0.1102 → 0.1301 | 0.0087 → 0.0124 | 0.0091 → 0.0130 |
| EXP-0002 | Wilcox AL | met → met | 0.0073 → 0.0118 | 0.0714 → 0.0985 | 0.0051 → 0.0069 | 0.0093 → 0.0123 |
| EXP-0003 | Chautauqua KS | met → met | 0.0732 → 0.0813 | 0.5313 → 0.6953 | 0.0352 → 0.0443 | 0.0352 → 0.0443 |
| EXP-0004 | Thurston NE | not met → not met | 0.0851 → 0.0975 | 0.7667 → 0.8075 | 0.0582 → 0.0740 | 0.0582 → 0.0740 |
| EXP-0005 | Chautauqua KS | not met → not met | 0.0732 → 0.0813 | 0.5313 → 0.6953 | 0.0352 → 0.0443 | 0.0352 → 0.0443 |
| EXP-0006 | McDowell WV | met → met | 0.0134 → 0.0213 | 0.1102 → 0.1301 | 0.0087 → 0.0124 | 0.0087 → 0.0124 |
| EXP-0007 | Wilcox AL | not met → not met | 0.0073 → 0.0118 | 0.0714 → 0.0985 | 0.0051 → 0.0069 | 0.0051 → 0.0069 |
| EXP-0008 | Teton ID | met → met | 0.2313 → 0.1547 | 0.8558 → 0.8536 | 0.1441 → 0.1007 | 0.1441 → 0.1007 |
| EXP-0009 | Thurston NE | not met → not met | 0.0851 → 0.0975 | 0.7667 → 0.8075 | 0.0582 → 0.0740 | 0.0582 → 0.0740 |
| EXP-0010 | Chautauqua KS | conditional → conditional | 0.0732 → 0.0813 | 0.5313 → 0.6953 | 0.0352 → 0.0443 | 0.0352 → 0.0443 |

Records:
- EXP-0001: `20261112T101201_20seeds.json` → `20261121T224309_20seeds.json`
- EXP-0002: `20261112T093121_20seeds.json` → `20261121T225001_20seeds.json`
- EXP-0003: `20261112T092029_20seeds.json` → `20261121T224400_20seeds.json`
- EXP-0004: `20261112T093312_20seeds.json` → `20261121T221040_20seeds.json`
- EXP-0005: `20261112T092039_20seeds.json` → `20261121T224404_20seeds.json`
- EXP-0006: `20261112T100404_20seeds.json` → `20261121T224321_20seeds.json`
- EXP-0007: `20261112T093124_20seeds.json` → `20261121T225005_20seeds.json`
- EXP-0008: `20261112T092718_20seeds.json` → `20261121T221228_20seeds.json`
- EXP-0009: `20261112T092738_20seeds.json` → `20261121T221047_20seeds.json`
- EXP-0010: `20261112T092049_20seeds.json` → `20261121T224409_20seeds.json`

RQLI values are means of per-seed statistics, as on the site. All new records carry `households_model: acs-quintiles-v2`. Their code commit is `40c3e10`, or for the seven runs that finished after a ledger-only commit landed mid-batch, `383f8dc`. The two commits have identical code (0 lines differ under `tools/`, `data/`, `specs/` and `tests/`).

## Published material that quotes these numbers

- **ruralsim.io experiments page:** the RQLI tables for all ten cards change on the next deploy after merge. Verdicts, intervals and constraint badges do not.
- **`experiments/BATCH_REPORT.md`:** the dated 2026-11-12 report. Its RQLI tables and EXP-0002's seed-0 quintile shares are superseded. It is left as written, with a pointer to this file.
- **`CAPTIONS_AND_SOURCES.md` and the social brand kit:** no number they quote changes. That covers the primary results, the 4 / 5 / 1 tally and the worst-off rule. The brand kit's line "In a clean-machine test, all ten experiments reran at 20 seeds each and matched the original results bit for bit" remains true of the 2026-11-12 test. A rerun today reproduces the new records, not the originals.
- **Documentary scripts and Grid & Grain Sim Lab material:** not in the repo, so not checked. Any line quoting an RQLI value or EXP-0002's quintile shares should be checked against the table above.
