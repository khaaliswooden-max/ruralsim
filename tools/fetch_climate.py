#!/usr/bin/env python3
"""Climate layer for Thurston County NE, v0.1.

Source: Open-Meteo historical archive (ERA5 reanalysis), county centroid point.
NOAA NCEI 1991-2020 station normals were the manifest source; NCEI per-station
PDFs need station-id wrangling that is deferred (DECISIONS D-010). This layer is
tagged "observed (modelled reanalysis)" per the manifest's solar_wind_resource
precedent. Daily 1991-2020 -> climate normals; 2015-2025 retained for extremes.
"""
import json, pathlib, urllib.request, urllib.parse, datetime, sys
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from county_config import get
C = get(sys.argv[1] if len(sys.argv) > 1 else None)
FIPS = C.fips
LON, LAT = C.centroid   # county centroid from pilot_counties.csv
REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = C.world / "layers_raw" / "climate"
OUT.mkdir(parents=True, exist_ok=True)
if (OUT / "climate_normals_1991_2020_monthly.csv").exists():
    print(f"climate: normals for {FIPS} already present, skipping (delete to re-fetch)")
    sys.exit(0)

params = {
    "latitude": LAT, "longitude": LON,
    "start_date": "1991-01-01", "end_date": "2020-12-31",
    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum,wind_speed_10m_max",
    "temperature_unit": "fahrenheit", "precipitation_unit": "inch", "wind_speed_unit": "mph",
    "timezone": {-5: "America/New_York", -6: "America/Chicago",
                 -7: "America/Denver", -8: "America/Los_Angeles"}[round(LON / 15)],
}
url = "https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(params)
req = urllib.request.Request(url, headers={"User-Agent": "RuralSim-research/0.1"})
with urllib.request.urlopen(req, timeout=600) as r:
    d = json.load(r)

df = pd.DataFrame(d["daily"])
df["date"] = pd.to_datetime(df["time"])
df.to_csv(OUT / "openmeteo_daily_1991_2020.csv", index=False)

df["month"] = df.date.dt.month
normals = df.groupby("month").agg(
    tmax_f=("temperature_2m_max", "mean"), tmin_f=("temperature_2m_min", "mean"),
    precip_in=("precipitation_sum", "sum"), snow_in=("snowfall_sum", "sum"),
    wind_max_mph=("wind_speed_10m_max", "mean"))
normals[["precip_in", "snow_in"]] = normals[["precip_in", "snow_in"]] / 30  # mean annual cycle per month
normals = normals.round(2)
normals.to_csv(OUT / "climate_normals_1991_2020_monthly.csv")

extremes = {
    "tmax_abs_f": round(float(df.temperature_2m_max.max()), 1),
    "tmin_abs_f": round(float(df.temperature_2m_min.min()), 1),
    "max_daily_precip_in": round(float(df.precipitation_sum.max()), 2),
    "max_wind_mph": round(float(df.wind_speed_10m_max.max()), 1),
}
meta = {"retrieved_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "source": "Open-Meteo archive API (ERA5 reanalysis), point at county centroid",
        "license": "CC BY 4.0 (Open-Meteo), ERA5 Copernicus",
        "provenance": "observed (modelled reanalysis)",
        "note": "NOAA NCEI 1991-2020 station normals deferred (DECISIONS D-010); point reanalysis used for v0.1",
        "lat": LAT, "lon": LON, "period": "1991-2020",
        "annual": {"tmax_mean_f": round(float(df.temperature_2m_max.mean()), 1),
                   "tmin_mean_f": round(float(df.temperature_2m_min.mean()), 1),
                   "precip_in_per_year": round(float(df.precipitation_sum.sum()) / 30, 1),
                   "snow_in_per_year": round(float(df.snowfall_sum.sum()) / 30, 1)},
        "extremes_1991_2020": extremes}
(OUT / "_meta.json").write_text(json.dumps(meta, indent=2))
print(json.dumps(meta["annual"], indent=1)); print(json.dumps(extremes, indent=1)); print("done")
