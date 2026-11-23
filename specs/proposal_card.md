# Proposal card — template v0.2

Decision **D-111** (`docs/DECISIONS.md`), spec `specs/ai_infra_engine.yaml` v0.2 (`proposal_card_intake`). Applies D-420 (tribal lands) and D-430 (fiscal scope F1). It takes effect when this PR merges. Step 2 implements the intake.

A proposal card lets a county, a resident or anyone else put **their own** proposal in front of RuralSim's screening engine. RuralSim's ten seed cards and EXP-0011 to EXP-0014 are RuralSim's questions. A proposal card is the community's question.

Downstream users of this file: the request form (it collects this card; turnaround D-410), the county brief (it prints this card's result), and step 2 (the engine compiles this card).

## Five rules a card cannot break

1. **At least two options, and one is always "no build."** No build is the county as it stands today. It is screened and reported like any other option, so it never reads as the free default.
2. **The site is public geography only.** Accepted: an H3 resolution-8 cell (about 0.74 km²), a 2020 Census block group, or a PLSS section. Never a street address, a parcel number or an owner's name. A map click becomes its cell, and the click itself is thrown away.
3. **The options are the submitter's.** RuralSim may suggest alternatives. Each one runs only if the submitter ticks it. No build is the only option added by rule.
4. **Pass bars are fixed before the run.** Accept RuralSim's defaults or set your own. Either way, the card records which bars apply and who set them, and they can't change after the run.
5. **Every result carries the "not modelled" block, in full.** It also carries both disclosure lines and the grade, SPECULATIVE.
6. **No site or modelled population on tribal land unless that nation's government asks (D-420).** In a partly tribal county, tribal land is masked from sites and from the modelled population, and the result says so.

## The card, as a person fills it in

### A. The decision (published)
| Field | Required | Notes |
|---|---|---|
| County | yes | Name and FIPS. |
| Public body deciding | yes | For example, the commissioners court, a county commission, a planning and zoning board, a city council, a state commission. |
| Kind of decision | yes | One of: rezoning or land-use permit · development or abatement agreement · moratorium study · utility or commission case · other. |
| Decision date, if known | no | Hearing or vote date. |
| Public documents | no | Links to the agenda item, application or study scope. Public documents only. |
| Stage | yes | One of: rumored · announced · application filed · under moratorium · hearing scheduled · decided. |

### B. Who is asking (role published, contact private)
| Field | Required | Notes |
|---|---|---|
| Role | yes | One of: county staff · elected official · resident · community group · school or hospital district · tribal government · utility or co-op · applicant or developer · other. The role is published. The name is not. "Tribal government" is verified against the BIA Tribal Leaders Directory and the nation's own site before intake (D-420 Rule 3). |
| Financial interest | yes | Yes or no, published: "Do you or your employer stand to gain or lose money from this decision?" A yes doesn't block the card. It is labelled. |
| Contact | yes | Kept private. Handling is set by the request-path SOP. |

A card is screened the same way whoever submits it. The engine reads the role in one case only: a card from a nation's government may place a site on that nation's land, and its results follow the nation's terms (D-420 Rule 4).

### C. Site (public geography only)
| Field | Required | Notes |
|---|---|---|
| Site geography | yes | An H3 r8 cell id, a block group GEOID or a PLSS section. One per option, and options may differ. |
| How you know the location | yes | One of: from a public document (link it in A) · approximate · unknown. "Unknown" is allowed: the submitter picks a cell they consider representative, and the record says it's representative. |

The card is refused, with the reason given, if the site falls outside the county, if an address, parcel or owner is entered, or if the site touches tribal land and the card is not from that nation's government (D-420). A request from the county, a resident, a utility or the applicant is not a nation's request, including for fee land inside a reservation. The form routes such a request to "requires the nation's request" before anything runs.

### D. Options (at least two, one is no build)
**Option 0 — No build.** Pre-filled and can't be removed. Today's grid, today's county load, today's water use, no site.

**Option 1 — The proposal as described.** For this and any further build option:

| Field | Required | Notes |
|---|---|---|
| Label | yes | For example, "As filed, 300 MW". |
| IT load (MW) | yes | Use the announced figure. If none was announced, give a range and say so. |
| Phases | no | Each phase has a year and a cumulative MW. Each phase is screened at its cumulative load. Ramp dynamics are not modelled. |
| Cooling | yes | Dry · adiabatic hybrid · evaporative · unknown. Unknown runs all three. |
| Water source | yes | Public water system (named from the county's list) · groundwater (aquifer, if known) · surface water (stream, if known) · reclaimed · none (dry) · unknown. |
| On-site generation | no | Solar MW, storage MWh, firm MW and fuel. |
| Backup generators | no | MW and fuel. Recorded and listed under "not modelled" (emissions, noise). No module reads it yet. |
| Who pays for grid upgrades | no | Direct assignment · large-load tariff · socialized · unknown. Unknown runs all three. |
| Interconnection | no | A substation or voltage, only if it's in a public document. |

**Suggested alternatives.** These are off by default, and each runs only if ticked:
- first phase only
- half the MW
- dry cooling instead
- with on-site solar and storage
- direct assignment of grid costs
- a different site (another cell)

### E. Pass bars (fixed before the run)
Tick "use RuralSim defaults", or replace any of them. The card records which applies and who set it.

| Channel | Default bar (from the card that set it) |
|---|---|
| Grid | No voltage or thermal violation in at least 90% of seeds (EXP-0011, D-101) |
| Rates, lowest-income households | p50 rate change ≤ 2% for every candidate utility under every cost allocation (EXP-0011). Above the D-102 site-share limit the result is indeterminate, never a pass. |
| Water | p50 peak-day draw ≤ 10% of the source gauge's dry-season low flow, and p50 annual draw ≤ 10% of county public supply (EXP-0012, D-106) |
| Flood | Site outside the 1% annual-chance zone, and p50 footprint share in it ≤ 10% (EXP-0013, D-107) |
| Fiber | Nearest fiber hexagon within 5 km and at least 2 county providers (EXP-0014, D-108). Shown, but this one bears on site viability more than on residents. |
| Worst-off rule | The worst-off 10% must not be made worse off. Always on; the submitter can't turn it off. |

### F. Stated by the submitter, not checked by RuralSim
These are optional. They are carried into the result under that exact label and never scored: announced investment, jobs, tax abatement or PILOT terms, construction schedule, and other claims. Under D-430 none of them becomes a modelled input. No revenue or net fiscal figure is computed.

### G. The county's own rules
These are optional and recorded. They are not modelled in v0.2 and are listed under "not modelled": setback (m), noise limit (dBA, day and night), height limit, lighting rules.

### H. What comes back
- Every option side by side. Each build option's difference from no build is computed per seed.
- Misses first, with the bar and the value. Then indeterminate and blocked results. Then passes.
- **Fiscal facts (D-430):** public facts only, labelled observed, no grade and no dollar figure. They are each taxing unit's current rate and levy; whether the state taxes business personal property (equipment); state sales-tax exemptions for data centers; and local agreements found in public registries, where absence isn't evidence there are none. Plus the fixed questions to demand (below). Texas and Kansas first. Elsewhere the block is empty and says so.
- The **not modelled** block in full: fiscal impact (revenue, incentives, service costs and school-finance offsets are not estimated), noise, emissions, setbacks, appearance, jobs and traffic, timeline, which utility serves the site, N-1, middle-mile fiber, groundwater yield, property values, ecology and cultural resources, and contract terms. Plus, where it applies, "tribal land masked (D-420)", naming the nation. Each entry says who can answer it.
- The grade, SPECULATIVE, and both disclosure lines word for word:
  - "RuralSim is a free, open-source project by Aldrich K. Wooden, Sr., founder of Get Rural America Done."
  - "Simulated, screening-grade results with assumed parameters. Decision support, not a finding."

## Fiscal questions to demand (fixed checklist, D-430)
These go on every proposal card result, unchanged. The list is built from NACo's "Counties face tax structure question on data centers" (Oct 20, 2026).
1. What share of the investment is real property (land, building), and what share is equipment? Which parts are taxable in this state, and how is each assessed?
2. What depreciation schedule applies to the equipment, and what taxable value is expected in years 1, 5 and 10? Ask for the figures in writing from the applicant and the appraisal district.
3. Which exemptions or abatements are requested or available (state sales and use tax, local property tax abatements, value limitations, PILOTs)? For each, which taxing unit gives up revenue, how much, and for how long?
4. What performance terms (jobs, investment, clawback) come with each incentive? Are they enforceable, and who checks them?
5. What does each other taxing unit gain or lose, especially school districts after any state school-finance offset?
6. What new public costs follow: roads, water and wastewater, EMS and fire, permitting and inspection staff? Who pays for them?
7. Is a PILOT, development agreement or community benefit agreement available under state law, and what would it secure?
8. How does long-term revenue compare with long-term service and infrastructure costs, using the applicant's own figures where RuralSim has none?

## Machine form (`PC-<yyyy>-<nnnn>.yaml`)

ILLUSTRATIVE. No such proposal exists. The county is a pilot, picked only so the fields resolve.

```yaml
card_id: PC-2026-0000                 # assigned at intake; immutable once run
card_version: 1
supersedes: null
run_kind: proposal_card
grade: SPECULATIVE
decision:
  county_fips5: "20019"               # Chautauqua KS (illustrative)
  public_body: "Board of County Commissioners"
  kind: moratorium_study               # rezoning_permit | development_or_abatement_agreement | moratorium_study | utility_case | other
  date: null
  public_documents: []                 # URLs of public documents only
  stage: under_moratorium
submitter:
  role: county_staff                   # published; tribal_government is verified before intake (D-420)
  financial_interest: false            # published
  contact_ref: "private:<intake id>"   # never in the card file
site_default:
  resolution: h3_r8                    # h3_r8 | blockgroup_2020 | plss_section
  geography_id: "8826d1....fffff"      # placeholder
  location_basis: approximate          # public_document | approximate | unknown
options:
  - {option_id: no_build, label: "No build", is_no_build: true}
  - option_id: as_filed
    label: "As described, 100 MW"
    it_load_mw: 100
    phases: [{phase: 1, year_offset: 0, it_load_mw_cumulative: 40}, {phase: 2, year_offset: 3, it_load_mw_cumulative: 100}]
    cooling: unknown                   # runs dry, adiabatic_hybrid, evaporative
    water_source: {kind: public_system, pwsid_or_name: null}
    onsite: {solar_mw: 0, storage_mwh: 0, firm_mw: 0, firm_fuel: null}
    backup_generation: {mw: null, fuel: null}
    cost_allocation: unknown           # runs all three
  - option_id: phase1_dry              # a suggested alternative, ticked by the submitter
    label: "First phase only, dry cooling"
    suggested_by: ruralsim
    ticked_by_submitter: true
    it_load_mw: 40
    cooling: dry
    water_source: {kind: none_dry}
    cost_allocation: unknown
criteria:
  set_by: ruralsim_defaults            # ruralsim_defaults | submitter | mixed
  grid_clean_seed_share: 0.9
  rate_change_pct_max: 2.0
  peak_day_share_of_low_flow_max: 0.10
  annual_share_of_public_supply_max: 0.10
  footprint_share_sfha_max: 0.10
  nearest_fiber_hex_km_max: 5.0
  county_fiber_providers_min: 2
  worst_off_not_worse_off: true        # fixed; cannot be set false
county_rules: {setback_m: null, noise_dba_day: null, noise_dba_night: null, height_m: null}
stated_not_checked:                    # carried verbatim, labelled, never scored
  announced_investment_usd: null
  announced_jobs: null
  tax_terms: null
seeds: 20
# Filled by the engine, not the submitter:
# fiscal_facts: {...}                  # D-430, observed, no grade, no dollar figure
# tribal_mask: null                    # D-420; non-null in partly tribal counties
```

## Related decisions
- **D-420** tribal lands. **D-430** fiscal F1. **D-400** pending public decision: a proposal card is a public-data screen, not calibrated work, but the card's decision block records whether D-400's trigger is met (`pending_public_decision`), so any later calibrated work on it is caught. **D-307:** partner calibration waits for a filed card and its published screen. **D-410:** turnaround.
- **Contact handling and publication timing:** the request-form spec and triage SOP.
