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
