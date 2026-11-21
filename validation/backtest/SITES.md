# Back-test candidate sites: fact sheets

Rollout step 3 · compiled 2026-11-21 · decision D-200

One sheet per candidate in the step-3 brief. Each fact carries a source key; keys resolve in the table under each sheet. **Primary** means a utility, agency, court, company or government document, or data the agency publishes; **secondary** means press or a data-center directory. Secondary sources are used only where no primary source was found, and are marked. "Not found" means a search turned up no public record. It does not mean the thing did not happen.

RUCC codes come from `data/county_master.csv` (USDA ERS Rural-Urban Continuum Codes). Codes 1–3 are metro and 4–9 nonmetro. Utility lists come from EIA-861 2024 service territory, read from each county's published world (`layers_raw/grid/eia861_territory_<fips>.csv`). EIA-861 sales and price series for 2001–2024 are in `observed/eia861_series.csv` (built by `tools/eia861_series.py`).

**Reading the EIA-861 territory list:** it names every utility with customers somewhere in the county, not the utility that serves a given site. The site's serving utility has to come from the record. That is why `sites.yaml` cites a source for each one.

---

## Selected: scored sites

### BT-01 · Mayes County, OK (40097) · Google, Pryor · RUCC 6 (nonmetro since 1983) · world published

| Item | Fact | Source |
|---|---|---|
| Operator | Google, at MidAmerica Industrial Park (state-owned, ~9,000 acres) | OK-1, OK-4 |
| Announced | May 2007: 800 acres, $600M, ~100 jobs. No MW announced. | OK-1 |
| Timeline | 2008: Google decided it did not need the site yet, and work paused. Resumed 2010-10-21. First building opened 2011, second unveiled 2012, a four-story building opened 2016, $600M expansion 2019. Cumulative investment $4.4B by 2022. | OK-1, OK-2, OK-6, OK-7 |
| Utility | Grand River Dam Authority (state agency, EIA 7490) serves every business in the park, Google included. GRDA has no residential retail. It sells wholesale to 14 public-power towns (unnamed on its site) and others. | OK-3, OK-4, EIA-861 |
| Load (observed, EIA-861) | GRDA retail sales: 627 GWh/yr in 2004–06 → 1,040 GWh/yr in 2012–13 → 4,280 GWh in 2024. Park-wide figure, not Google alone. | EIA-861 |
| Substation / transmission | **Not found.** GRDA's Grand River Energy Center sits on the park's south edge, and a GRDA transmission crew is based at the park. | OK-3 |
| Rate case / tariff | **Not found** for the site. Oklahoma law lets public power withhold large-customer usage data. | OK-1 |
| Water | Neosho River water through the park, under the park's GRDA supply contract and an OWRB permit (park-wide: 27.375 billion gal/yr). Google used >1.1 billion gal from 2024-07-01 to 2025-06-30 (~3 Mgal/day) and discharged ~253 Mgal back to the river. It was the park's second-largest water user. From utility records obtained under the Open Records Act. | OK-5 |
| Tax | Oklahoma five-year ad valorem exemption, with the state reimbursing counties. Google's Mayes exemptions: $45.9M in 2021, about a third of the program. SB 609 (2021) closed the program to new data centers but kept Google's exemptions on new equipment at existing Mayes facilities until 2036. Separately, $113.9M in state income-tax credits since 2017. | OK-6 |
| Gaps | Serving substation and line work; which Mayes distributors buy from GRDA. Both are PENDING in `sites.yaml`. | |

| Key | Source | Type |
|---|---|---|
| OK-1 | Data Center Knowledge, "Google Resumes Work on Oklahoma Data Center," 2010-10-21 — https://www.datacenterknowledge.com/archives/2010/10/21/google-resumes-work-on-oklahoma-data-center/ | secondary (quotes Google) |
| OK-2 | Oklahoma Dept. of Commerce, "New Google Facility Opening Brings Its Oklahoma Investment to $2 Billion," 2016-10-13 — https://www.okcommerce.gov/new-google-facility-opening-brings-its-oklahoma-investment-to-2-billion/ | primary (state) |
| OK-3 | GRDA, "GRDA and MidAmerica," 2024-04-22 — https://grda.com/grda-and-midamerica/ ; GRDA electricity customers — https://grda.com/electricity/ | primary (utility) |
| OK-4 | MidAmerica Industrial Park, "MidAmerica and the Grand River Dam Authority," 2020-06-12 — https://maip.com/news/article/midamerica-and-the-grand-river-dam-authority | primary (park authority) |
| OK-5 | The Frontier, "As data centers boom in Oklahoma, so does water demand," 2026 — https://www.readfrontier.org/stories/as-data-centers-boom-in-oklahoma-so-does-water-demand/ | secondary (reports utility records) |
| OK-6 | The Frontier, "Oklahoma lawmakers tried to cut a costly incentive for data centers but gave Google a break," 2022 — https://www.readfrontier.org/stories/oklahoma-lawmakers-tried-to-cut-a-costly-incentive-for-data-centers-but-gave-google-a-break/ | secondary (reports state tax data) |
| OK-7 | Oklahoma Dept. of Commerce, "Google Investment in Pryor, Okla. Reaches $3 Billion" (the $600M expansion), 2019-06-24 — https://www.okcommerce.gov/google-investment-in-pryor-okla-reaches-3-billion/ | primary (state) |

### BT-02 · Jackson County, AL (01071) · Google, Widows Creek · RUCC 6 (nonmetro) · world published

| Item | Fact | Source |
|---|---|---|
| Operator | Google, on part of TVA's retired Widows Creek Fossil Plant | AL-1 |
| Announced | 2015-06-24. Google's first site on a former industrial site. Construction was expected to start in 2016. | AL-1 |
| Investment | $600M (first phase). In 2026 Google announced a further $1.5B for 2026–27. | AL-2, AL-4 |
| Timeline | Construction kicked off April 2018 on 360 of ~2,000 acres. "Established 2018" (AL-4); "came online 2019" (AL-5, secondary, unsourced). **Conflict**, so both years are registered. | AL-2, AL-4, AL-5 |
| Utility | Google: "our electric utility is TVA." The plant's existing transmission lines would bring in new renewable power. In the EIA-861 territory list for Jackson: North Alabama Electric Coop (13669), Sand Mountain Electric Coop, City of Scottsboro. All are TVA distributors. Whether the site is TVA direct-served or served through NAEC is **not found**. | AL-1, AL-3, EIA-861 |
| Power supply | 413 MW TVA solar PPA (two ~150 MW farms) supplying Clarksville TN and Jackson AL, reported at the Clarksville opening. 300 MW contracted for the region and Google covers its electric costs (2026). Kairos/TVA advanced-nuclear deal up to 50 MW (2025). | MT-2, AL-4 |
| Substation / transmission | Existing Widows Creek lines reused (stated at T0). New substation work **not found**. | AL-1 |
| Rate case / tariff | **Not found** for the site. TVA sets wholesale rates valley-wide. | |
| Water | On the Tennessee River. Volume and arrangement **not found**. | AL-2 |
| Tax | **Not found** for the site. The 2026 Legislature passed a bill reducing abatements for large data centers. | AL-4 |
| Gaps | Retail seller; opening year; substation; water; abatement. | |

| Key | Source | Type |
|---|---|---|
| AL-1 | Google, "A power plant for the Internet: our newest data center in Alabama," 2015-06-24 — https://blog.google/inside-google/infrastructure/a-power-plant-for-internet-our-newest/ | primary (company) |
| AL-2 | Chattanooga Times Free Press, "Google building $600 million data center," 2018-04-09 — https://www.timesfreepress.com/news/breakingnews/story/2018/apr/09/google-building-600-million-data-center/467903/ | secondary |
| AL-3 | EIA-861 2024 service territory, Jackson County AL, from the published world | primary (EIA) |
| AL-4 | Alabama Daily News, "Google invests $1.5B to expand Jackson County data center," 2026 — https://aldailynews.com/google-invests-1-5b-to-expand-jackson-county-data-center/ | secondary |
| AL-5 | Baxtel directory, Google Bridgeport — https://baxtel.com/data-center/google-bridgeport | secondary, unsourced |

### BT-03 · Wasco County, OR (41065) · Google, The Dalles · RUCC 6 (2003) / 7 (2023), nonmetro · world expected ~2026-11-23

| Item | Fact | Source |
|---|---|---|
| Operator | Google, through Design LLC ("Project O2") | OR-2, OR-5 |
| Announced | 2005-02-18: the Port of The Dalles approved selling 30 acres for $1.87M, conditional on tax incentives and power supply. 50–100 jobs. Construction reported as "$5–20M over time." No MW. | OR-1 |
| Timeline | First data center 2006. Expansion announced 2013, opened 2015-04-10 (~$600M, 164,000 sq ft). Two more announced 2021; buildings completed 2025 and 2026. | OR-3, OR-4, OR-6 |
| Utility | Northern Wasco County PUD (EIA 13788), a people's utility district buying from BPA. Formula rate based on cost of service. Data centers are in separate customer classes. The PUD states residential customers do not cross-subsidize them. Loads above 5 MW need an electric service agreement. | OR-2, OR-5 |
| Load (observed, EIA-861) | NWCPUD retail sales: 256 GWh/yr in 2002–04 → 552 GWh/yr in 2007–08 → 1,531 GWh in 2024. A 2008 estimate put the first building at ~30 MW (Google does not disclose). | EIA-861, OR-2 |
| Substation / transmission | "Transmission, substations and switchyards built by the District and BPA for data centers"; metered 115 kV and 230 kV circuits. Campus-wide, not dated to the first building. | OR-5 |
| Rate case / tariff | Separate data-center classes under a formula rate (OR-5). A 2008 advocacy estimate put Google's price at ~$219k/MW-yr against ≥$500k market (OR-2, estimate only). | OR-2, OR-5 |
| Water | City supply (Dog River ~85%, plus groundwater). Google used 104.3 Mgal (2012) → 355.1 Mgal (2021), from records released after the city dropped its 2022 suit to keep them private. About a third of city water by 2024. Google holds groundwater rights of up to 3.88 Mgal/day and transferred part of them to the city in 2021. | OR-6, OR-7 |
| Tax | 15-year property-tax exemption on improvements (Oregon enterprise zone), with a pay requirement of 150% of the county average wage. 2013 deal: $1.2M up front, then $800k/yr from 2016. 2021 SIP agreement for the new buildings. Tax year 2025: Design LLC billed $3.01M on $2.30B assessed value. | OR-2, OR-4, OR-5, OR-8 |

| Key | Source | Type |
|---|---|---|
| OR-1 | AP via SecurityInfoWatch, "Google to build technology facility in Wasco County, Ore.," 2005-02-18 — https://www.securityinfowatch.com/home/news/10610126/google-to-build-technology-facility-in-wasco-county-ore | secondary (wire, contemporaneous) |
| OR-2 | Willamette Week, "Welcome to Googleville," 2008-06-03 — https://www.wweek.com/portland/article-9089-welcome-to-googleville.html | secondary |
| OR-3 | GovTech, "Google Opens $600 Million Oregon Data Center," 2015-04-10 — https://www.govtech.com/dc/Google-Opens-600-Million-Oregon-Data-Center-.html | secondary |
| OR-4 | DatacenterDynamics, "We now know how much water Google's Oregon data centers use…," 2022-12 — https://www.datacenterdynamics.com/en/news/we-now-know-how-much-water-googles-oregon-data-centers-use-after-city-drops-lawsuit-against-journalists/ | secondary (reports city records) |
| OR-5 | Northern Wasco County PUD presentation to the Oregon Data Center Advisory Committee, 2026-05-29 — https://www.oregon.gov/energy/get-involved/Documents/07-Humaira-Falkenberg-NWCPUD-DCAC-05-29-2026.pdf | primary (utility) |
| OR-6 | OPB, "As Google's water demands grow, The Dalles aims to pull more from Mount Hood forest," 2026-01-15 — https://opb.org/article/2026/01/15/as-googles-water-demands-grow-the-dalles-aims-to-pull-more-from-mount-hood-forest | secondary |
| OR-7 | Same records as OR-4. Annual gallons 2012–2021, table in `sites.yaml`. | secondary (reports city records) |
| OR-8 | 2021 Strategic Investment Program agreement, Wasco County / City of The Dalles / Google Design LLC (PDF hosted by OPB) — https://www.opb.org/pdf/AGR%202021%20Wasco%20County%20City%20of%20The%20Dalles%20SIP%20for%20Google%20Design%20LLC_1769200135514.pdf | primary (agreement) |

### BT-04 · Grant County, WA (53025) · Microsoft (+ Yahoo), Quincy · RUCC 4 (2003) / 5 (2023), nonmetro · world expected ~2026-11-23

| Item | Fact | Source |
|---|---|---|
| Operators | Microsoft bought ~75 acres in 2006, ribbon cutting 2007-04-16 (270-acre campus later). Yahoo's first phase built 2007. Then Intuit, Sabey, Dell, Vantage. 8 data-center operators by 2025. | WA-1, WA-2, WA-3, WA-4 |
| Utility | PUD No. 2 of Grant County (EIA 14624). Owns rights to 63.31% of Priest Rapids and Wanapum dams' output (>2,100 MW capacity). | WA-3 |
| Load (observed) | EIA-861 Grant PUD retail sales: 2,901 GWh/yr in 2003–05 → 3,623 GWh/yr in 2008–09. From reporting on PUD records: Microsoft substation capacity 48 MW in 2007; Microsoft + Yahoo together averaged 41.8 MW around 2011, against 9.5 MW for all residential and small commercial. Data centers ~280 aMW of 757 aMW system load in 2025 (37%), and ~800 MW of large-load requests queued. | EIA-861, WA-1, WA-3 |
| Substation / transmission | Substation built for Microsoft's 48 MW (Microsoft complained in 2007 that it was slow). 2010 substation work led Microsoft to run its generators. | WA-1 |
| Rate case / tariff | Microsoft was offered 2.5–3.8 ¢/kWh for its first five years. Rate Schedule 99 followed bad large-load forecasts and penalizes forecast misses. In 2012 the PUD board waived most of Microsoft's $210k penalty after Microsoft burned power deliberately. Policy: residential, small-business and agricultural customers get first claim on low-cost hydro, and large loads pay for their own generation, transmission and distribution. Residential all-in rate 4.12 ¢ (2006) → 6.4 ¢ (2026). Proposed for 2027: new Rates 20/21 (high-density compute), +12.5% for Tier 2 against +3.5% for core customers. | WA-1, WA-3, WA-5 |
| Water | Quincy groundwater (Columbia Plateau basalt). Data centers used ~10% of the city's ~2.1 billion gal/yr. Microsoft paid the whole $31M for a reuse utility (operating 2021-06-30), saving ~138 Mgal/yr of potable water. | WA-4 |
| Tax | Site-specific exemptions **not found** (Washington's rural data-center sales/use-tax exemption is unverified here; see the note below the table). Quincy tax revenue $0.7M (2005) → $4.3M (2007), credited to data-center construction. | WA-2 |

| Key | Source | Type |
|---|---|---|
| WA-1 | NBC News / New York Times, "In farm town, data barns gobble power," 2012-09 — https://www.nbcnews.com/id/wbna49147152 | secondary (reports PUD records) |
| WA-2 | Data Center Knowledge, "The Evolution of Quincy and the Data Center," 2013-05-20 — https://www.datacenterknowledge.com/archives/2013/05/20/the-evolution-of-quincy-and-the-data-center | secondary |
| WA-3 | Grant PUD, "Data center FAQs," 2026-08-28 — https://www.grantpud.org/blog/data-center-faqs | primary (utility) |
| WA-4 | U.S. EPA, "Water Reuse Case Study: Quincy, Washington" (archived 2025-01-19) — https://19january2025snapshot.epa.gov/waterreuse/water-reuse-case-study-quincy-washington | primary (federal) |
| WA-5 | APPA Public Power Daily, "Grant PUD commissioners considering proposal to create new electric rate classes for data centers," 2026-09-25 — https://www.publicpower.org/periodical/article/grant-pud-commissioners-considering-proposal-create-new-electric-rate-classes-data-centers ; Grant PUD 2026 Rate Schedule 17 — https://www.grantpud.org/images/2026/2026-Rates/2026-Rate-Schedule-17.pdf | secondary (trade) / primary (tariff) |

The Washington rural data-center sales-tax exemption (RCW 82.08.986, 2010) is cited from general knowledge. It needs a primary link before anything relies on it. Nothing in the pre-registration does.

---

## Selected: contrast site (metro, never counted)

### BT-C1 · Licking County, OH (39089) · New Albany cluster (Google, Meta, AWS, Microsoft) · RUCC 1 · world published

| Item | Fact | Source |
|---|---|---|
| Utility | Ohio Power Co (AEP Ohio, EIA 14006), plus six co-ops and municipals in the county. Ohio has retail choice, so bundled Part A sales understate AEP's delivery load. | EIA-861 |
| Rate case / tariff | PUCO case 24-0508-EL-ATA. Data Center Tariff adopted 2025-07-09, effective 2025-07-23. Applies at ≥25 MW. Minimum billing demand is 85% of contract capacity (in steps). Up to a 4-year ramp, then an 8-year term. Exit fee of 36 months of minimum charges. | OH-1, OH-2 |
| Why kept | The best-documented regulatory response to data-center load among the candidates. It shows whether the engine's rate module behaves differently on an IOU in a metro county. | |
| Gaps | Which New Albany project, with its T0 and E, is PENDING. | |

| Key | Source | Type |
|---|---|---|
| OH-1 | AEP Ohio, Data Center Tariff page — https://www.aepohio.com/company/about/rates/data-center-tariff | primary (utility tariff) |
| OH-2 | PUCO, "PUCO orders AEP Ohio to create data center specific tariff" — https://content.govdelivery.com/accounts/OHPUC/bulletins/3e8bb79 | primary (regulator) |

---

## Not selected

| County (FIPS) | Site | RUCC 2023 | What the record shows | Why not |
|---|---|---|---|---|
| Pottawattamie IA (19155) | Google Council Bluffs (2007) | 2, metro (Omaha) | MidAmerican Energy (IOU). Not researched further. | Metro |
| Caldwell NC (37027) | Google Lenoir (2007) | 2, metro (Hickory) | Duke Energy. Not researched further. | Metro (was 6 in 1983) |
| Berkeley SC (45015) | Google Moncks Corner (2007) | 2, metro (Charleston) | Santee Cooper / Berkeley Electric Coop. Utility of record not confirmed. | Metro |
| Newton GA (13217) | Meta Stanton Springs (announced 2018-03-07) | 1, metro (Atlanta) | Walton EMC (co-op, EIA 20065) supplies 100% solar via new co-op solar, with Morgan Stanley as energy partner. 970,000 sq ft. [NG-1] | Metro. Strongest alternate contrast: co-op served. |
| Montgomery TN (47125) | Google Clarksville (announced 2015-12-22, construction 2018-02) | 2, metro (Clarksville) | TVA (100% renewable arrangement), on the 1,300-acre former Hemlock Semiconductor site. 413 MW TVA solar PPA shared with Jackson AL. [MT-1, MT-2] | Metro |
| Crook OR (41013) | Meta Prineville (2010–11), Apple | 3 in 2023 (metro), 6 in 2013 | Pacific Power (IOU). Enterprise zone. Not researched further. | Changed class in 2023. Hold for a later round with the vintage rule settled. |

| Key | Source | Type |
|---|---|---|
| NG-1 | Walton EMC, "Facebook Likes Walton EMC," 2018-03-07 — https://www.waltonemc.com/facebook-likes-walton-emc | primary (co-op) |
| MT-1 | Tennessee ECD, "Governor Haslam, Commissioner Boyd Announce Google to Locate New Data Center in Clarksville," 2015-12-22 — https://www.tn.gov/ecd/news/2015/12/22/governor-haslam-commissioner-boyd-announce-google-to-locate-new-data-center.html | primary (state) |
| MT-2 | DatacenterDynamics, "Google opens $600m Tennessee data center" — https://www.datacenterdynamics.com/en/news/google-opens-600m-tennessee-data-center/ | secondary |

## EIA-861 files used

EIA Form 861 annual files 2001–2024, from https://www.eia.gov/electricity/data/eia861/, downloaded 2026-11-21. Public domain. The zips are not committed (~75 MB). `tools/eia861_series.py` and `tools/derive_observed.py` re-derive everything from them. SHA-256 of each zip is in `observed/eia861_zips.sha256`.
