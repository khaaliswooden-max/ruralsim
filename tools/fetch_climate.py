#!/usr/bin/env python3
"""Climate layer for one county (fips5 argument), v0.2 (D-029).

    python3 tools/fetch_climate.py 31173              # normals + best-effort daily series
    python3 tools/fetch_climate.py 31173 --no-daily   # normals only (national runs)

Normals (required): NOAA NCEI nClimDiv county series — monthly maximum and minimum
temperature and precipitation, area-averaged over the county, 1991-2020. Three national
files cover every county in the 50 states; they are downloaded once into the shared
cache ($RURALSIM_CACHE, default /tmp/ruralsim_cache) and every county is read from them.
Public domain, observed. This replaces one Open-Meteo request per county, which the
service rate-limits per address and which a 3,144-county run cannot fit inside.

Daily series (optional): Open-Meteo archive (ERA5 reanalysis) at the county centroid,
1991-2020, written as openmeteo_daily_1991_2020.csv. Only experiment EXP-0008 reads it.
It is fetched with a short retry budget and the build continues without it on failure;
_meta.json says whether it is present.

Fallback: a county nClimDiv does not cover (Connecticut's planning regions — nClimDiv
still uses the 8 legacy counties) takes its normals from the Open-Meteo daily series,
exactly as v0.1 did, and says so in _meta.json.

Output schema is unchanged from v0.1: climate_normals_1991_2020_monthly.csv with columns
month, tmax_f, tmin_f, precip_in, snow_in, wind_max_mph. nClimDiv has no snowfall or wind,
so those two columns are blank when the normals come from nClimDiv.
"""
from __future__ import annotations

import argparse, datetime, json, os, pathlib, re, sys, time, urllib.error, urllib.parse, urllib.request

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from county_config import get  # noqa: E402

CACHE = pathlib.Path(os.environ.get("RURALSIM_CACHE", "/tmp/ruralsim_cache")) / "climdiv"
CLIMDIV_DIR = "https://www.ncei.noaa.gov/monitoring-content/data/us/climdiv/monthly/current/"
UA = {"User-Agent": "RuralSim/1.0 (+https://www.ruralsim.io; county twin build)"}
ELEMENTS = {"tmax": "27", "tmin": "28", "pcpn": "01"}
PERIOD = (1991, 2020)

# nClimDiv state codes: the 48 contiguous states alphabetically, then Hawaii (49), Alaska (50)
_CONUS = ["AL", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "ID", "IL", "IN", "IA", "KS",
          "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
          "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
          "VT", "VA", "WA", "WV", "WI", "WY"]
NCDC_STATE = {st: f"{i + 1:02d}" for i, st in enumerate(_CONUS)} | {"HI": "49", "AK": "50"}
# DC has no nClimDiv county series; it falls back to the Open-Meteo path.


def _fetch(url: str, timeout=300) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def climdiv_files() -> dict[str, pathlib.Path]:
    """Download (or reuse, up to 30 days) the current county tmax/tmin/pcpn files."""
    CACHE.mkdir(parents=True, exist_ok=True)
    have = {e: sorted(CACHE.glob(f"climdiv-{e}cy-v*")) for e in ELEMENTS}
    fresh = all(have[e] and time.time() - have[e][-1].stat().st_mtime < 30 * 86400 for e in ELEMENTS)
    if fresh:
        return {e: have[e][-1] for e in ELEMENTS}
    listing = _fetch(CLIMDIV_DIR, timeout=60).decode("utf-8", "replace")
    out = {}
    for e in ELEMENTS:
        names = sorted(set(re.findall(rf"climdiv-{e}cy-v[0-9.]+-[0-9]{{8}}", listing)))
        if not names:
            raise RuntimeError(f"no nClimDiv county file for {e} listed at {CLIMDIV_DIR}")
        dest = CACHE / names[-1]
        if not dest.exists():
            print(f"  downloading {names[-1]} ...", flush=True)
            part = dest.with_suffix(".part")
            part.write_bytes(_fetch(CLIMDIV_DIR + names[-1]))
            os.replace(part, dest)
        out[e] = dest
    return out


def climdiv_normals(st: str, fips: str, files: dict[str, pathlib.Path]):
    """Monthly 1991-2020 means for one county, or None if nClimDiv has no series for it."""
    code = NCDC_STATE.get(st)
    if code is None:
        return None
    cols = {}
    for e, path in files.items():
        prefix = f"{code}{fips[2:]}{ELEMENTS[e]}"
        rows = []
        with open(path) as fh:
            for line in fh:
                if line.startswith(prefix):
                    year = int(line[7:11])
                    if PERIOD[0] <= year <= PERIOD[1]:
                        vals = [float(v) for v in line[11:].split()]
                        rows.append(vals)
        if len(rows) != PERIOD[1] - PERIOD[0] + 1:
            return None  # county absent (or incomplete) in nClimDiv
        df = pd.DataFrame(rows, columns=range(1, 13))
        df = df.mask(df <= -9.99)  # missing-value sentinels: -99.90 (temp), -9.99 (precip)
        if df.isna().any().any():
            return None
        cols[e] = df.mean()
    normals = pd.DataFrame({"tmax_f": cols["tmax"], "tmin_f": cols["tmin"],
                            "precip_in": cols["pcpn"], "snow_in": float("nan"),
                            "wind_max_mph": float("nan")})
    normals.index.name = "month"
    return normals.round(2)


# the longest Retry-After worth waiting for; longer means the daily quota is spent (D-050)
MAX_RETRY_WAIT = 600


def openmeteo_daily(lat, lon, attempts: int):
    params = {
        "latitude": lat, "longitude": lon,
        "start_date": "1991-01-01", "end_date": "2020-12-31",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum,wind_speed_10m_max",
        "temperature_unit": "fahrenheit", "precipitation_unit": "inch", "wind_speed_unit": "mph",
        # continental zones unchanged from v0.1 (pilot results depend on them)
        "timezone": {-5: "America/New_York", -6: "America/Chicago",
                     -7: "America/Denver", -8: "America/Los_Angeles"}.get(round(lon / 15), "auto"),
    }
    url = "https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(params)
    for attempt in range(attempts):
        try:
            d = json.loads(_fetch(url, timeout=600))
            df = pd.DataFrame(d["daily"])
            df["date"] = pd.to_datetime(df["time"])
            return df
        except urllib.error.HTTPError as e:
            if e.code not in (429, 502, 503, 504) or attempt == attempts - 1:
                raise
            ra = (e.headers.get("Retry-After") if e.headers else None) or ""
            wait = int(ra) if ra.isdigit() else min(30 * 2 ** attempt, 600)
            if wait > MAX_RETRY_WAIT:
                # Open-Meteo's daily quota is spent: it asks for the wait until the reset
                # (66,812 s for Clayton IA in run #38, which then hit the 6-hour job limit)
                raise RuntimeError(f"Open-Meteo HTTP {e.code} asks to retry in {wait} s "
                                   f"(over {MAX_RETRY_WAIT} s: daily quota spent); not waiting") from e
            print(f"  Open-Meteo HTTP {e.code}; retrying in {wait}s ({attempt + 1}/{attempts})", flush=True)
            time.sleep(wait)


POWER = ("https://power.larc.nasa.gov/api/temporal/daily/point?parameters=T2M_MAX,T2M_MIN,PRECTOTCORR,WS10M_MAX"
         "&community=AG&longitude={lon:.4f}&latitude={lat:.4f}&start=19910101&end=20201231&format=JSON")


def power_normals(lat, lon, attempts: int = 5):
    """Third source (D-059): NASA POWER daily (MERRA-2), county centroid, 1991-2020.

    Used only when nClimDiv lacks the county and Open-Meteo refuses (its daily quota was
    spent during build #47: Lake and Peninsula AK, 02164). Public, no key, no daily quota.
    POWER has no snowfall, so snow_in stays blank, as it does for nClimDiv."""
    url = POWER.format(lat=lat, lon=lon)
    for attempt in range(attempts):
        try:
            p = json.loads(_fetch(url, timeout=300))["properties"]["parameter"]
            break
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(min(15 * 2 ** attempt, 240))
    df = pd.DataFrame({k: pd.Series(v) for k, v in p.items()}).replace(-999.0, float("nan"))
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    m = df.groupby(df.index.month)
    n = pd.DataFrame({"tmax_f": m["T2M_MAX"].mean() * 9 / 5 + 32, "tmin_f": m["T2M_MIN"].mean() * 9 / 5 + 32,
                      "precip_in": m["PRECTOTCORR"].sum() / 25.4 / 30, "snow_in": float("nan"),
                      "wind_max_mph": m["WS10M_MAX"].mean() * 2.23694})
    n.index.name = "month"
    return n.round(2)


def normals_from_daily(df):
    df = df.assign(month=df.date.dt.month)
    n = df.groupby("month").agg(
        tmax_f=("temperature_2m_max", "mean"), tmin_f=("temperature_2m_min", "mean"),
        precip_in=("precipitation_sum", "sum"), snow_in=("snowfall_sum", "sum"),
        wind_max_mph=("wind_speed_10m_max", "mean"))
    n[["precip_in", "snow_in"]] = n[["precip_in", "snow_in"]] / 30  # mean per month
    return n.round(2)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("fips", nargs="?")
    ap.add_argument("--no-daily", action="store_true", help="skip the optional Open-Meteo daily series")
    a = ap.parse_args(argv)

    C = get(a.fips)
    out = C.world / "layers_raw" / "climate"
    out.mkdir(parents=True, exist_ok=True)
    norm_p = out / "climate_normals_1991_2020_monthly.csv"
    if norm_p.exists():
        print(f"climate: normals for {C.fips} already present, skipping (delete to re-fetch)")
        return
    lon, lat = C.centroid

    normals, normals_src = None, None
    try:
        files = climdiv_files()
        normals = climdiv_normals(C.st, C.fips, files)
        if normals is not None:
            normals_src = {"source": "NOAA NCEI nClimDiv county monthly series (area average), 1991-2020",
                           "files": [p.name for p in files.values()],
                           "license": "public domain (NOAA)", "provenance": "observed"}
        else:
            print(f"  nClimDiv has no complete 1991-2020 series for {C.fips}; using Open-Meteo normals")
    except Exception as e:
        print(f"  nClimDiv unavailable ({e}); using Open-Meteo normals", file=sys.stderr)

    daily, daily_note = None, "not requested (--no-daily)"
    need_daily = normals is None or not a.no_daily
    if need_daily:
        try:
            # a long retry budget only when the normals depend on it
            daily = openmeteo_daily(lat, lon, attempts=7 if normals is None else 3)
            daily.to_csv(out / "openmeteo_daily_1991_2020.csv", index=False)
            daily_note = "present"
        except Exception as e:
            daily_note = f"unavailable ({e}); EXP-0008 cannot run on this county until refetched"
            print(f"  Open-Meteo daily series skipped: {e}", file=sys.stderr)
            if normals is None:
                try:
                    normals = power_normals(lat, lon)
                    normals_src = {"source": "NASA POWER daily API (MERRA-2 reanalysis), point at county centroid",
                                   "license": "public (NASA); credit the NASA Langley Research Center POWER Project",
                                   "provenance": "observed (modelled reanalysis)",
                                   "note": f"fallback (D-059): nClimDiv lacks the county and Open-Meteo failed ({e})"}
                    print(f"  normals from NASA POWER (Open-Meteo failed: {e})")
                except Exception as e2:
                    raise SystemExit(f"FAILED: no normals for {C.fips} — nClimDiv lacks the county, "
                                     f"Open-Meteo failed ({e}) and NASA POWER failed ({e2})")

    if normals is None:
        normals = normals_from_daily(daily)
        normals_src = {"source": "Open-Meteo archive API (ERA5 reanalysis), point at county centroid",
                       "license": "CC BY 4.0 (Open-Meteo), ERA5 Copernicus",
                       "provenance": "observed (modelled reanalysis)",
                       "note": "fallback: county not covered by nClimDiv (D-029)"}
    normals.to_csv(norm_p)

    meta = {"retrieved_utc": datetime.datetime.now(datetime.UTC).isoformat(),
            **normals_src, "lat": lat, "lon": lon, "period": "1991-2020",
            "normals_columns_blank": [c for c in ("snow_in", "wind_max_mph") if normals[c].isna().all()],
            "daily_series": {"file": "openmeteo_daily_1991_2020.csv", "status": daily_note,
                             "source": "Open-Meteo archive API (ERA5 reanalysis), county centroid",
                             "license": "CC BY 4.0 (Open-Meteo), ERA5 Copernicus"},
            "annual": {"tmax_mean_f": round(float(normals.tmax_f.mean()), 1),
                       "tmin_mean_f": round(float(normals.tmin_f.mean()), 1),
                       "precip_in_per_year": round(float(normals.precip_in.sum()), 1)}}
    if daily is not None:
        meta["extremes_1991_2020"] = {
            "tmax_abs_f": round(float(daily.temperature_2m_max.max()), 1),
            "tmin_abs_f": round(float(daily.temperature_2m_min.min()), 1),
            "max_daily_precip_in": round(float(daily.precipitation_sum.max()), 2),
            "max_wind_mph": round(float(daily.wind_speed_10m_max.max()), 1)}
    (out / "_meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta["annual"], indent=1)); print("done")


if __name__ == "__main__":
    main()
