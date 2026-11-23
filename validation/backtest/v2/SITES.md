# Back-test v2 sites: fact sheets

Rollout step 3 · compiled 2026-11-22 · decision D-207

Three sites, none used in v1. Each fact carries a source key; the key table is at the end of each sheet. "Primary" means the operator, utility, regulator or a government office. "Secondary" means press or a data-center directory, used only where no primary source was found. RUCC codes are from `data/county_master.csv`. Utility lists are EIA-861 2024 service territory from each county's published world. Sales and prices are EIA-861 2001–2024, computed by `tools/derive_observed_v2.py` into `observed/observed_values.json`.

## How the three were chosen

The search started from every built hyperscale site I could find in a nonmetro county, and v1's five counties were removed. A site had to pass five tests:

1. Nonmetro under the RUCC vintage in force at T0.
2. No tribal land at the site (D-420). All three counties contain none: the Morrow world's two tribal features lie outside the county, with an overlap share of 0.0.
3. A published county world.
4. A load that can be observed for the years the comparisons need (§5.3).
5. At least one public record of a grid build, a rate effect or water use.

Two candidates failed test 4:

| County | Site | Why not |
|---|---|---|
| Mecklenburg VA (51117) | Microsoft Boydton, announced 2010 | Served by Dominion Virginia Power [ME-1]. Microsoft discloses no per-site load, and Dominion's ~75 TWh of sales hide a site of tens of MW. |
| Umatilla OR (41059) | AWS Hermiston and Umatilla | Same utility as V2-03 (UEC), so its load is not separable. The county is also partly tribal. |

---

### V2-01 · Crook County, OR (41013) · Meta (Facebook), Prineville · RUCC 6 (2003), 6 (2013), 3 (2023)

| Item | Fact | Source |
|---|---|---|
| Announced | 2010-01-21: Facebook's first company-built data center. ~200 construction jobs, at least 35 permanent. No investment or MW disclosed. | CR-1 |
| Operating | 71 GWh used in 2011, so E = 2011 | CR-4 |
| Utility | Pacific Power (PacifiCorp, EIA 14354). BPA owns the Ponderosa substation south of town. | CR-3 |
| Grid build | Oct 2010: the local BPA substation "lacks the capacity" for Facebook's planned buildings, and BPA planned an upgrade for 2014. Jan 2013: BPA and Pacific Power completed the Ponderosa substation upgrade early, adding 350 MW (local grid 650 → 1,000 MW). | CR-3, CR-7 |
| Load | Site electricity, GWh: 2011 71 · 2012 153 · 2013 224 · 2014 262 · 2015 284 · 2016 327 · 2017 426 · 2018 488 · 2019 573 · 2020 686 | CR-4, CR-5 |
| Water | Withdrawal: 2014 11.0 Mgal · 2015 18.0 Mgal · 2016–2020 70,000 / 172,000 / 160,000 / 208,000 / 445,000 m³ | CR-4, CR-5 |
| Cooling | Outside air along a 300-ft wall, pushed through a wall of purified water ("a huge mister"), then filters. No air-conditioning units are mentioned. | CR-6 |
| Also on campus | Apple, about 1 km east, from 2012. Not in this site's load. | CR-7, OSM |

### V2-02 · Rutherford County, NC (37161) · Meta (Facebook), Forest City · RUCC 4 (all vintages)

| Item | Fact | Source |
|---|---|---|
| Announced | 2010-11-11: $450 M | RU-1 |
| Operating | "Came online at the end of 2011" (6 GWh used in 2011). Serving live traffic April 2012. So E = 2011 or 2012. | CR-4, RU-4, RU-2 |
| Utility | "The new Facebook site in Forest City is served by Duke Energy" (Nov 2010). In 2010 that was Duke Energy Carolinas (EIA 5416); Progress Energy joined Duke in 2012. | RU-3 |
| Grid build | A 100 kV substation on the campus, tagged `operator=Facebook` in OSM (way 460089170). Build date not documented. | RU-5 |
| Load | Site electricity, GWh: 2011 6 · 2012 98 · 2013 225 · 2014 322 · 2015 310 · 2016 339 · 2017 433 · 2018 547 · 2019 614 · 2020 595 | CR-4, CR-5 |
| Water | Withdrawal: 2014 31.0 Mgal · 2015 33.0 Mgal · 2016–2020 123,000 / 129,000 / 99,000 / 85,000 / 68,000 m³ | CR-4, CR-5 |
| Cooling | Outdoor-air cooling of the same design as Prineville (PUE 1.06–1.08) | RU-2 |

### V2-03 · Morrow County, OR (41049) · Amazon (AWS), Boardman · RUCC 6 (2003), 6 (2013), 8 (2023)

| Item | Fact | Source |
|---|---|---|
| Announced | 2008-11-07: Port of Morrow, the first of three buildings (116,000 sq ft) under way. $100 M. A 10 MW substation being built next to the site. | MO-1 |
| Operating | UEC's first data center started construction in 2008, stalled about a year later, and resumed in 2012. AWS has been in Eastern Oregon "a dozen years" as of 2023. EIA-861 shows UEC's sales rising from 2013. So E = 2011 or 2013. | MO-2, MO-3 |
| Utility | Umatilla Electric Cooperative (EIA 19325). Data centers are now ~80–85% of its load. Large loads take Schedule 6 (Large Industrial Rate, >10 MW), which passes through wholesale and transmission cost. UEC expanded substations and used mobile substations for new campuses. | MO-2, MO-3 |
| Grid build | The 10 MW substation by the site (2008). Substation expansions for later campuses. | MO-1, MO-2 |
| Load | UEC delivered energy (EIA-861) rose from 839 GWh/yr (2005–07) to 8,432 GWh (2024). This covers every AWS campus UEC serves, in Morrow and Umatilla counties. | EIA-861 |
| Water | AWS 2024: Port of Morrow 136 Mgal (4% of the Port's production). Total Oregon 284 Mgal; WUE 0.16 L/kWh. Context only: no load exists for that campus group alone. | MO-4 |

---

## Source keys

| Key | Source | Type |
|---|---|---|
| CR-1 | Data Center Knowledge, "It's Official: Facebook is Oregon's Company X," 2010-01-21 — https://www.datacenterknowledge.com/hyperscalers/it-s-official-facebook-is-oregon-s-company-x | secondary |
| CR-3 | U.S. Sen. Ron Wyden, "Wyden calls on BPA, PacifiCorp to aid Facebook expansion…," 2010-10-14 — https://www.wyden.senate.gov/news/press-releases/wyden-calls-on-bpa-pacificorp-to-aid-facebook-expansion-and-economic-development-in-central-oregon | primary (government) |
| CR-4 | Meta, 2015 Sustainability Data Disclosure (per-site electricity 2011–2015, water 2014–2015) — https://sustainability.atmeta.com/asset/2015-sustainability-data-disclosure | primary (operator) |
| CR-5 | Facebook, 2020 Sustainability Data (per-site electricity and water withdrawal 2016–2020) — https://sustainability.fb.com/wp-content/uploads/2021/07/2020_FB_Sustainability-Data.pdf | primary (operator) |
| CR-6 | eWeek, "Why Facebook's New-Gen Data Center Leads by Example" — https://www.eweek.com/networking/why-facebook-s-new-gen-data-center-leads-by-example/ | secondary |
| CR-7 | Data Center Knowledge, "Substation Unleashes More Power in Prineville," 2013-01-14 — https://www.datacenterknowledge.com/archives/2013/01/14/substation-unleashes-more-power-in-prineville | secondary |
| RU-1 | Area Development, "Facebook Selects Forest City, North Carolina, for $450M Data Center," 2010-11-11 — https://www.areadevelopment.com/newsitems/11-11-2010/facebook-forest-city-north-carolina11112.shtml | secondary |
| RU-2 | Data Center Knowledge, "Facebook's North Carolina Data Center Goes Live," 2012-04-20 — https://datacenterknowledge.com/hyperscalers/facebook-s-north-carolina-data-center-goes-live | secondary |
| RU-3 | Data Center Knowledge, "With NC Site, Facebook Rebuffs Greenpeace," 2010-11-15 — https://www.datacenterknowledge.com/hyperscalers/with-nc-site-facebook-rebuffs-greenpeace | secondary |
| RU-4 | Data Center Knowledge, "Facebook's Shifting Power Footprint," 2013-07-22 (citing Facebook's 2012 report) — https://www.datacenterknowledge.com/archives/2013/07/22/facebooks-shifting-power-footprint | secondary |
| RU-5 | OpenStreetMap way 460089170 (`power=substation`, `voltage=100000`, `operator=Facebook`), in world 37161_rutherford_nc snapshot 20261119T173843Z-d287c5c | observed (OSM, ODbL) |
| MO-1 | Data Center Knowledge, "Amazon Building Large Data Center in Oregon," 2008-11-07 — https://www.datacenterknowledge.com/archives/2008/11/07/amazon-building-large-data-center-in-oregon/ | secondary |
| MO-2 | CoBank, "A Guide for Serving Large Loads — case study: Umatilla Electric Association" — https://www.cobank.com/web/cobank/knowledge-exchange/power-energy-and-water/a-guide-for-serving-large-loads/case-study/umatilla-electric-association | secondary (lender; utility-described) |
| MO-3 | La Grande Observer, "Amazon strikes power deal for data centers," 2023 — https://lagrandeobserver.com/?p=154421 | secondary |
| MO-4 | Amazon presentation to the Oregon Data Center Advisory Committee, 2026-03-27 — https://www.oregon.gov/energy/Get-Involved/Documents/2026-03-27-Schilz-Amazon.pdf | primary (operator, to the state) |
| ME-1 | Virginia Economic Development Partnership, "Mecklenburg County: Microsoft to locate major data center," 2010-08 — https://vedp.org/press-release/2010-08/mecklenburg-county-microsoft-locate-major-data-center | primary (state) |
| OSM-H | ohsome API (HeiGIT), OSM history: `power=substation` counts in each county's bounding box at two-year steps 2008–2026 — https://api.ohsome.org/v1/elements/count | observed (OSM history) |

Conversions: 1 Mgal = 3,785.41 m³. 2014–2015 water was reported in gallons and is converted in `sites.yaml`.
