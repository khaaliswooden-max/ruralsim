# Dry run PC-2026-0001: Hill County, TX (D-410 launch gate e)

Run 2026-11-23 (UTC). Engine `5ee71c5` (main `f9bcd01` plus the card), spec v0.2. Every result is **SPECULATIVE**.

## Verdict, misses first

| Gate e requirement | Result |
|---|---|
| Uses only facts public on or before 2026-05-12 | **Met for proposal facts.** Partly: the data vintages (EIA-861 2024, the Nov 2026 county snapshot) are later. The snapshot shows no building on the site, so nothing needed masking. Disclosed in the brief. |
| Meets 20 business days | **Met for the steps RuralSim controls.** About 30 minutes from start to draft brief. The calendar steps a real request needs are listed below. None is close to 20 business days, except the Spanish review, which has no reviewer seated. |
| **Measured hours** | **Not met.** Claude did the work, so the founder's hours on this run are zero. D-410 counts founder hours, and one step is still unmeasured: Khaalis's review of the brief. Time that review and log it here. That closes gate e. |
| **The May 12 vote could have been served under D-410** | **No.** A complete request was needed by **2026-04-07** (20 + 5 business days before the vote). In the public record we found nothing at county level before that date. The court's item surfaced with its 72-hour agenda notice. A request triggered by that agenda would have been **declined for time**. Only an earlier signal would have caught it in time. The Hillsboro EDC's land contract with Provident (Sept 2024) and the city's conditional consent to a Municipal Management District (Mar 4, 2025) were both public a year ahead. This confirms the agenda watch's design (early signals, not agendas). |

## Timing log (UTC, container clock)

| Step (TRIAGE_SOP) | Start → end | Elapsed | Who in a real request |
|---|---|---|---|
| 0. Confirm gates on main (D-410, D-111, D-114 merged; engine accepts a card) | 02:35 → 02:43 | ~8 min | one-time |
| 2. Eligibility (tribal: no AIANNH land in Hill; public decision; public record; TX; no money; no conflict) | inside step 4 | <5 min | founder |
| 4. Public-record research and card (facts ≤ 2026-05-12) | 02:43 → 02:53 | ~10 min | founder plus submitter |
| 4. Card validated (2-seed `--no-write`) | 02:54:06 → 02:54:31 | 25 s | engine |
| 5. Pre-register: card and default bars committed and pushed (`5ee71c5`) | 02:54:37 | — | founder |
| 6. Run, 20 seeds, 7 scenarios | 02:54:41 → 02:56:42 | **2 min 01 s** | engine |
| 7. Analysis and brief (text edition) | 02:56 → 02:58 | ~5 min | founder |
| **Total to draft brief** | **02:35 → 02:58** | **~24 min** | |

**Steps not exercised, because a dry run has no requester or recipients:**
- Requester confirms the options (up to 3 business days).
- Khaalis reviews and QAs the brief (unmeasured: **time it**).
- PDF on the Design-canvas template: there is no generator, so assembly is manual (template open item).
- Spanish resident view: D-402 is not adopted and no reviewer is seated.
- Delivery notice under OUTREACH_RULE.

## What the dry run found in the system (not in Hill County)

1. **In Texas retail-choice areas the bill test always comes back "can't tell".** Oncor and TNMP are delivery-only utilities with no residential sales in EIA-861. Much of rural ERCOT is like this, and Texas is a first state. Proposed fix: a layer request for TDU delivery tariffs plus a retail-choice bill method. Until then, every brief in those areas says so.
2. **The worst-off rule can't be judged for almost any real rural data center.** A 100 MW site is 1.4–2.2 times the annual sales of each nearby co-op. The rate model's validity limit is 0.25 (D-102). So the bill test and the worst-off rule return CAN'T TELL. That's honest, but it means RuralSim's central guardrail is silent exactly where it matters. This is the biggest open item for "decides them together". It needs a large-load-contract method, or co-op data under D-307.
3. **Jurisdiction check missing from triage.** The one named project sits in the city, and the decision was the county's. Add to TRIAGE_SOP §2: "Which body has authority over this site?"
4. **The grid result isn't monotonic, and it shouldn't read that way.** At 300 MW the site connects at 345 kV, 16.8 km away, and passes. At 100 MW it connects at 138 kV, 3.5 km away, and fails. The new 345 kV line and its cost aren't modelled. The brief explains this. A generator must always print the point of interconnection and its voltage beside the grid row.
5. **Assumptions dominate.** No MW, cooling or water source was public. Cooling moves the water result from 0% to 99% of public supply. This is the normal case, so the brief's first question to the applicant (MW and cooling) carries most of the value.
6. **Brief assembly is manual.** At about 5 minutes for a text brief it's fine. The PDF on the canvas will take longer, so measure that too.

## Status of the launch gate (D-410)
- **(a) Spec patch merged and the engine accepts a card: met.** D-111, D-114, PR #88.
- **(b) County-brief template adopted: not met.** It's in the project, not in a D-entry, and has no generator. **Decision for Khaalis.**
- **(c) D-400, D-401 and D-420 adopted: met.** PR #82.
- **(d) Standing pass-bar set published: met.** `specs/proposal_card.md` §E is on main.
- **(e) Dry run met 20 business days with measured hours: open.** Waiting on Khaalis's timed review.

The request path stays closed until (b) is decided and (e) is closed.

Files: `proposals/PC-2026-0001.yaml` (card, pre-registered at `5ee71c5`), `experiments/ledger/PC-2026-0001/20261123T025443_run.json`, `proposals/PC-2026-0001_BRIEF.md`.

Sources for the public facts used: [Texas Tribune, 2026-05-12](https://www.texastribune.org/2026/05/12/texas-hill-county-approves-data-center-construction-pause-ai/); [City of Hillsboro, Provident project page](https://hillsborotx.org/data_center.php) (EDC contract Sept 2024; MMD consent Mar 4, 2025); [Texas Tribune, rescission, 2026-06-05](https://www.texastribune.org/2026/06/05/texas-hill-county-moratorium-rescinded-data-centers/) (used only for context after the cutoff, not as an input).
