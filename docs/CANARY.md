# Canary run — 57 counties (rollout step 1, D-035)

Purpose: prove the build-and-publish pipeline on a spread of hard cases before the
national run, and replace estimates with measured runtime and storage per county.

## The list
Paste into **Actions → Build county worlds → Run workflow → FIPS codes**
(max_parallel 10, publish on):

```
01063,02013,02290,04011,05013,06003,06071,08053,09110,10001,11001,12077,12087,13265,15005,16033,17069,18115,19003,20071,21201,22023,22107,23021,24029,25019,26083,27155,28055,29227,30069,31117,32009,33007,34033,35021,36041,36061,37177,38087,39163,40025,41069,42023,44001,45005,46075,46102,47137,49009,50009,51091,51610,53023,54105,55078,56027
```

- **One county per state + DC**: the smallest-population current county in each state
  (cheapest rural builds, and the kind of place RuralSim is for). Loving TX (48301) is
  already published and is left out.
- **Deliberate hard cases**
  | FIPS | County | Why |
  |---|---|---|
  | 02290 | Yukon-Koyukuk, AK | largest area in the U.S.; Alaska terrain products differ |
  | 02013 | Aleutians East, AK | island chain, sparse OSM |
  | 06071 | San Bernardino, CA | largest county in the lower 48; biggest state extract |
  | 15005 | Kalawao, HI | smallest county (81 people); island |
  | 09110 | Capitol, CT | a planning region (2022 geography); nClimDiv falls back |
  | 51610 | Falls Church, VA | independent city |
  | 11001 | District of Columbia | no nClimDiv county; Open-Meteo fallback |
  | 46102 | Oglala Lakota, SD | tribal lands; tribal-primacy water systems |
  | 12087 | Monroe, FL | Keys: long, thin, mostly water |
  | 22023 | Cameron Parish, LA | parish naming; coastal marsh |
  | 36061 | New York, NY | dense urban stress test for buildings and roads |

## What to record when it finishes
Per county, from the bucket (`logs/<run id>/<fips>.txt`, `worlds/<dir>/latest.json`):
build minutes, published MB, validation pass / flag / fail, and the first error line for
any failure. Summarise in READINESS and decide the national batch size from the slowest
quartile, not the mean.

## Result — run 43794676050 (2026-11-16)

38 of 57 built and published; 19 failed. Built: median 13 min, 75th percentile 19 min, slowest 54 min; median 143 MB published, largest 503 MB, 6.4 GB in all. Validation across the 38: 286 pass, 29 flag, 0 fail; 14 counties with no flag. Failure causes and fixes: D-036.

| Cause | Counties |
|---|---|
| Geofabrik refused parallel downloads | 06003, 20071, 29227, 37177, 41069, 46102, 51610 |
| EPA URL with a space | 09110, 11001, 36061 |
| Empty EPA answer | 10001, 15005, 22107 |
| Terrain out of memory | 02013, 02290, 06071 |
| Multi-part boundary | 12087 |
| NHD server error, then heal loop | 22023 |
| TNM search server error | 53023 |

Re-run list (the 19): `02013,02290,06003,06071,09110,10001,11001,12087,15005,20071,22023,22107,29227,36061,37177,41069,46102,51610,53023`

## Final result — runs 43794676050, 43845007357, 43912692762, 43933790557 (2026-11-16)

56 of 57 built and published. Not built: **Yukon-Koyukuk AK (02290)** — after the D-038/D-039 fixes it got through every fetch, then the runner lost contact (resources) in the stage step; it is the largest county in the U.S. and needs either a larger runner or a split build. Build times are the last successful run per county (fix runs included); sizes from each snapshot's manifest.

| FIPS | County | Minutes | MB | Pass | Flag | Fail |
|---|---|---:|---:|---:|---:|---:|
| 01063 | Greene County, AL | 11 | 187 | 9 | 0 | 0 |
| 02013 | Aleutians East Borough, AK | 20 | 1230 | 5 | 1 | 0 |
| 04011 | Greenlee County, AZ | 23 | 296 | 7 | 1 | 0 |
| 05013 | Calhoun County, AR | 7 | 102 | 8 | 0 | 0 |
| 06003 | Alpine County, CA | 34 | 248 | 7 | 1 | 0 |
| 06071 | San Bernardino County, CA | 92 | 1987 | 8 | 2 | 0 |
| 08053 | Hinsdale County, CO | 21 | 198 | 7 | 1 | 0 |
| 09110 | Capitol Planning Region, CT | 51 | 659 | 6 | 2 | 0 |
| 10001 | Kent County, DE | 35 | 421 | 8 | 1 | 0 |
| 11001 | District of Columbia, DC | 48 | 588 | 6 | 3 | 0 |
| 12077 | Liberty County, FL | 13 | 146 | 7 | 1 | 0 |
| 12087 | Monroe County, FL | 60 | 623 | 6 | 5 | 0 |
| 13265 | Taliaferro County, GA | 12 | 61 | 7 | 1 | 0 |
| 15005 | Kalawao County, HI | 3 | 32 | 5 | 1 | 0 |
| 16033 | Clark County, ID | 13 | 228 | 6 | 2 | 0 |
| 17069 | Hardin County, IL | 14 | 49 | 8 | 1 | 0 |
| 18115 | Ohio County, IN | 11 | 133 | 8 | 0 | 0 |
| 19003 | Adams County, IA | 7 | 86 | 9 | 0 | 0 |
| 20071 | Greeley County, KS | 6 | 49 | 9 | 0 | 0 |
| 21201 | Robertson County, KY | 6 | 36 | 7 | 1 | 0 |
| 22023 | Cameron Parish, LA | 23 | 428 | 7 | 0 | 0 |
| 22107 | Tensas Parish, LA | 11 | 188 | 6 | 1 | 0 |
| 23021 | Piscataquis County, ME | 30 | 481 | 8 | 1 | 0 |
| 24029 | Kent County, MD | 26 | 168 | 8 | 1 | 0 |
| 25019 | Nantucket County, MA | 10 | 44 | 9 | 0 | 0 |
| 26083 | Keweenaw County, MI | 19 | 208 | 6 | 2 | 0 |
| 27155 | Traverse County, MN | 15 | 70 | 8 | 1 | 0 |
| 28055 | Issaquena County, MS | 14 | 203 | 6 | 2 | 0 |
| 29227 | Worth County, MO | 7 | 61 | 7 | 1 | 0 |
| 30069 | Petroleum County, MT | 9 | 227 | 8 | 0 | 0 |
| 31117 | McPherson County, NE | 5 | 58 | 7 | 0 | 0 |
| 32009 | Esmeralda County, NV | 53 | 503 | 7 | 1 | 0 |
| 33007 | Coos County, NH | 28 | 322 | 8 | 1 | 0 |
| 34033 | Salem County, NJ | 54 | 431 | 8 | 1 | 0 |
| 35021 | Harding County, NM | 10 | 197 | 8 | 0 | 0 |
| 36041 | Hamilton County, NY | 25 | 278 | 8 | 0 | 0 |
| 36061 | New York County, NY | 20 | 557 | 7 | 1 | 0 |
| 37177 | Tyrrell County, NC | 9 | 75 | 7 | 1 | 0 |
| 38087 | Slope County, ND | 10 | 167 | 8 | 0 | 0 |
| 39163 | Vinton County, OH | 15 | 110 | 7 | 1 | 0 |
| 40025 | Cimarron County, OK | 29 | 159 | 9 | 0 | 0 |
| 41069 | Wheeler County, OR | 45 | 557 | 8 | 0 | 0 |
| 42023 | Cameron County, PA | 13 | 61 | 6 | 2 | 0 |
| 44001 | Bristol County, RI | 18 | 140 | 8 | 0 | 0 |
| 45005 | Allendale County, SC | 18 | 95 | 8 | 1 | 0 |
| 46075 | Jones County, SD | 6 | 126 | 7 | 1 | 0 |
| 46102 | Oglala Lakota County, SD | 12 | 213 | 8 | 1 | 0 |
| 47137 | Pickett County, TN | 12 | 71 | 7 | 1 | 0 |
| 49009 | Daggett County, UT | 18 | 111 | 6 | 2 | 0 |
| 50009 | Essex County, VT | 15 | 193 | 7 | 1 | 0 |
| 51091 | Highland County, VA | 13 | 98 | 8 | 0 | 0 |
| 51610 | Falls Church city, VA | 15 | 153 | 6 | 1 | 0 |
| 53023 | Garfield County, WA | 23 | 138 | 7 | 2 | 0 |
| 54105 | Wirt County, WV | 8 | 62 | 8 | 0 | 0 |
| 55078 | Menominee County, WI | 9 | 61 | 8 | 0 | 0 |
| 56027 | Niobrara County, WY | 13 | 277 | 8 | 1 | 0 |

Flags by check: water systems placed 22, buildings vs housing units 20, source unavailable at build (NHD outages) 6, terrain coverage 4. Counties built before D-037 have no Overture buildings yet; rebuilding them is one run.
