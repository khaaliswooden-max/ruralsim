"""Tier A — national statistical twin (3,144 counties, no 3D).

Assembles a per-county statistical profile from the observed national bundle
(data/county_master.csv, county_profile.csv, county_year.csv, county_decade.csv).
No fetching, no geometry. Every output column carries a provenance tag in
national/tier_a_provenance.json. Political/election columns are stripped at load
(denylist, D-007) and never written to Tier A outputs.

Run: python3 tools/build_national.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.harness import denylist

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "national"
OUT.mkdir(exist_ok=True)

TARGET_COUNTIES = 3144  # 2024-vintage county-equivalent universe the twin aims at

SOURCES = {
    "county_master.csv": "Census TIGER 2024 geography + Census pop estimates 2024 + SAIPE 2023 + USDA ERS RUCC 2023/typology 2025 + AHRQ hospital counts (assembled in DATA_PROFILE)",
    "county_profile.csv": "USDA ERS county typology profile (ACS 2016-2020 vintage fields)",
    "county_year.csv": "Census population estimates components of change, annual",
    "county_decade.csv": "Census decennial populations 1900-2020",
}


def load(name: str, **kw) -> pd.DataFrame:
    denylist.assert_clean_file(name, context="tier A national build")
    df = pd.read_csv(DATA / name, dtype={"fips5": str}, **kw)
    forbidden = [c for c in df.columns if denylist._bad(c)]
    if forbidden:
        df = df.drop(columns=forbidden)
    return df


def main() -> None:
    master = load("county_master.csv")
    profile = load("county_profile.csv")
    year = load("county_year.csv")
    decade = load("county_decade.csv")

    prov: dict[str, dict] = {}

    def tag(col, tag_, src, note=""):
        prov[col] = {"tag": tag_, "source": SOURCES.get(src, src), "note": note}

    m = master.set_index("fips5")
    p = profile.set_index("fips5")

    out = pd.DataFrame(index=m.index)
    out["county_name"] = m["county_name"]
    out["state_abbr"] = m["state_abbr"]
    out["rucc_2023"] = m["rucc_2023"]
    out["nonmetro_2023"] = m["nonmetro_2023"]
    for c in ["county_name", "state_abbr", "rucc_2023", "nonmetro_2023"]:
        tag(c, "observed", "county_master.csv")

    out["pop_2024_estimate"] = m["pop_2024_estimate"]
    out["pop_change_2020_2024_pct"] = m["pop_change_2020_2024_pct"]
    out["pop_2020_pct_of_peak"] = m["pop_2020_pct_of_peak"]
    out["peak_pop_decade"] = m["peak_pop_decade"]
    for c in ["pop_2024_estimate", "pop_change_2020_2024_pct", "pop_2020_pct_of_peak", "peak_pop_decade"]:
        tag(c, "observed", "county_master.csv")

    # --- economic security proxies (RQLI domain inputs at Tier A fidelity)
    out["median_hh_income_2023"] = m["median_hh_income_2023"]
    out["poverty_rate_2023"] = m["poverty_rate_2023"]
    tag("median_hh_income_2023", "observed", "county_master.csv")
    tag("poverty_rate_2023", "observed", "county_master.csv")
    out["income_after_essentials_est"] = m["median_hh_income_2023"] * 0.38
    tag("income_after_essentials_est", "calibrated", "county_master.csv",
        "median income minus assumed 62% essentials share (same calibration as harness)")

    # --- care access proxies
    for c in ["n_hospitals", "n_critical_access_hospitals", "n_rural_emergency_hospitals"]:
        out[c] = m[c]
        tag(c, "observed", "county_master.csv")
    out["hospitals_per_10k_pop"] = m["n_hospitals"] / m["pop_2024_estimate"] * 1e4
    tag("hospitals_per_10k_pop", "derived", "county_master.csv", "hospital count over 2024 population")

    # --- demographics & labor (USDA ERS profile)
    prof_cols = {
        "Age65AndOlderPct2020": "pct_65_plus_2020",
        "Ed4AssocDegreePct": "pct_assoc_degree",
        "Ed5CollegePlusPct": "pct_college_plus",
        "UnempRate2021": "unemp_rate_2021",
        "Poverty_Rate_ACS": "poverty_rate_acs",
        "PerCapitaInc": "per_capita_income_acs",
        "OwnHomePct": "pct_owner_occupied",
        "NonEnglishHHPct": "pct_non_english_hh",
        "AvgHHSize": "avg_hh_size",
    }
    for src_c, dst_c in prof_cols.items():
        if src_c in p.columns:
            out[dst_c] = p[src_c]
            tag(dst_c, "observed", "county_profile.csv", f"ERS field {src_c}")

    # --- typology flags (observed classifications); -1/99/NaN are missing-data
    # sentinels in the source, NOT flags — recode to 0 and count them honestly
    typ = [c for c in m.columns if c.startswith("typ_")]
    sentinel_counts = {}
    for c in typ:
        v = m[c]
        sent = int(((v < 0) | (v > 1) | v.isna()).sum())
        if sent:
            sentinel_counts[c] = sent
        out[c] = v.where((v == 0) | (v == 1), 0).fillna(0).astype(int)
        tag(c, "observed", "county_master.csv",
            f"USDA ERS typology; {sent} rows had missing-data sentinels recoded to 0" if sent else
            "USDA ERS typology")

    # --- recent dynamics from annual estimates
    y = year[year["year"] == year["year"].max()].set_index("fips5")
    for c in ["births", "deaths", "net_migration", "natural_change"]:
        if c in y.columns:
            out[f"{c}_latest"] = y[c]
            tag(f"{c}_latest", "observed", "county_year.csv", f"vintage year {int(year['year'].max())}")

    # --- long-run trajectory
    dec = decade.pivot_table(index="fips5", columns="year", values="population", aggfunc="first")
    dec.columns = [f"pop_{int(c)}" for c in dec.columns]
    out = out.join(dec)
    for c in dec.columns:
        tag(c, "observed", "county_decade.csv")

    out = out.reset_index().rename(columns={"index": "fips5"})
    denylist.assert_clean_columns(out.columns, context="tier A output")

    # ---------- validation ----------
    checks = []
    def check(name, value, thresh, op=">="):
        ok = bool(value >= thresh) if op == ">=" else bool(value <= thresh)
        checks.append({"check": name, "value": float(value), "threshold": float(thresh),
                       "op": op, "status": "PASS" if ok else "FLAG"})
    check("county rows vs 3144 target", len(out), TARGET_COUNTIES, ">=")
    check("median_hh_income_2023 completeness (%)", 100 * out["median_hh_income_2023"].notna().mean(), 99.0)
    check("poverty_rate_2023 completeness (%)", 100 * out["poverty_rate_2023"].notna().mean(), 99.0)
    check("pop_2024_estimate completeness (%)", 100 * out["pop_2024_estimate"].notna().mean(), 99.0)
    check("profile join completeness (%)", 100 * out["pct_65_plus_2020"].notna().mean(), 95.0)
    rucc_nonmetro = float((out.loc[out["rucc_2023"] >= 4, "nonmetro_2023"] == 1).mean() * 100)
    check("RUCC>=4 coded nonmetro (%)", rucc_nonmetro, 99.0)
    dupes = int(out["fips5"].duplicated().sum())
    check("duplicate fips5 rows", dupes, 0, "<=")
    pilots = ["31173", "16081", "54047", "20019", "01131"]
    missing_pilots = [f for f in pilots if f not in set(out["fips5"])]
    check("pilot counties present", len(missing_pilots), 0, "<=")

    # ---------- write (stage to /tmp then copy; portal mount can drop fresh files)
    import shutil, tempfile
    stage = Path(tempfile.mkdtemp(prefix="tierA_"))
    csv_p, prov_p, val_p, sum_p = (OUT / n for n in
        ("tier_a_county_stats.csv", "tier_a_provenance.json",
         "tier_a_validation.json", "tier_a_summary.md"))
    s_csv, s_prov, s_val, s_sum = (stage / n for n in
        ("tier_a_county_stats.csv", "tier_a_provenance.json",
         "tier_a_validation.json", "tier_a_summary.md"))
    out.to_csv(s_csv, index=False)
    s_prov.write_text(json.dumps({"columns": prov, "guardrails": {
        "political_variables_excluded": "election/power columns stripped at load, absent from output",
        "no_real_persons": True, "tier": "A_statistical (no 3D, no household simulation)",
    }}, indent=1))
    s_val.write_text(json.dumps({"checks": checks,
        "n_flags": sum(1 for c in checks if c["status"] == "FLAG")}, indent=1))

    nm = out[out["nonmetro_2023"] == 1]
    lines = [
        "# Tier A national statistical twin — summary",
        "",
        f"- counties: **{len(out)}** (target {TARGET_COUNTIES}; difference = county-equivalents not in the 2024 vintage or merged planning regions)",
        f"- nonmetro counties (RUCC-based): **{len(nm)}**",
        f"- persistent-poverty counties (ERS 2017-21): **{int(out['typ_persistent_poverty_1721'].sum())}**"
        + (f" (+{sentinel_counts.get('typ_persistent_poverty_1721', 0)} counties with missing-data sentinels)" if sentinel_counts.get('typ_persistent_poverty_1721') else ""),
        f"- counties at <=80% of historical peak population: **{int((out['pop_2020_pct_of_peak'] <= 80).sum())}**",
        f"- counties with zero hospitals: **{int((out['n_hospitals'] == 0).sum())}** (nonmetro: {int((nm['n_hospitals'] == 0).sum())})",
        f"- validation flags: **{sum(1 for c in checks if c['status']=='FLAG')} / {len(checks)} checks**",
        "",
        "Political/election columns were stripped at load and are absent from all Tier A outputs (D-007).",
        "Tier A is statistical only: no geometry, no households, no simulation. Inter-county comparisons",
        "are descriptive, not causal.",
    ]
    s_sum.write_text("\n".join(lines) + "\n")

    for s, d in [(s_csv, csv_p), (s_prov, prov_p), (s_val, val_p), (s_sum, sum_p)]:
        shutil.copy2(s, d)
        if not d.exists() or d.stat().st_size != s.stat().st_size:
            raise RuntimeError(f"portal mount dropped {d.name} on copy")

    print("\n".join(lines))
    print("\nvalidation:")
    for c in checks:
        print(f"  {c['status']:4s}  {c['check']}: {c['value']:.1f} {c['op']} {c['threshold']}")


if __name__ == "__main__":
    main()
