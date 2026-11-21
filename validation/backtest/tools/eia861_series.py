"""Residential price and total-sales series from EIA Form 861, for the back-test.

Reads the EIA-861 annual zips (2004-2024 layouts: file2.xls up to 2011,
Sales_Ult_Cust_<year>.xlsx from 2012) and writes, per utility and year:
residential revenue, sales, customers and average price (cents/kWh), and total
retail sales (MWh), plus two benchmarks: the same-state bundled residential
average, and the average of same-state utilities of the same EIA ownership class
(the utility itself excluded). Part A (bundled service) rows only, so delivery-only and energy-only
rows of retail-choice states are not double counted; this is recorded in the
output. EIA-861 is public domain.

Usage:
  python3 eia861_series.py --zips DIR --out observed_eia861.csv \
      --utility 7490:OK --utility 13690:WA ...  --years 2004-2024

This is reference data for the back-test (validation/backtest/), not a world
layer; it does not touch the build pipeline.
"""
import argparse, csv, glob, io, os, re, sys, zipfile
import pandas as pd


def _find_sheet(z: zipfile.ZipFile, year: int):
    names = z.namelist()
    if year >= 2012:
        pat = re.compile(rf"(^|/)Sales_Ult_Cust_{year}\.xlsx?$", re.I)
    else:
        pat = re.compile(r"(^|/)file2(_\d{4})?\.xls$", re.I)
    hits = [n for n in names if pat.search(n)]
    if not hits:
        raise SystemExit(f"{year}: no sales sheet in zip ({names[:8]}...)")
    return hits[0]


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if pd.isna(v) else float(v)
    s = str(v).strip().replace(",", "")
    if s in ("", ".", "*", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


_OWN = {  # EIA's ownership labels changed across layouts; map to one vocabulary
    "MUNICIPAL": "municipal", "COOPERATIVE": "cooperative", "POLITICAL SUBDIVISION": "political_subdivision",
    "STATE": "state", "FEDERAL": "federal", "INVESTOR OWNED": "investor_owned", "INVESTOR-OWNED": "investor_owned",
    "RETAIL POWER MARKETER": "retail_marketer", "POWER MARKETER": "retail_marketer",
    "MUNICIPAL MKTG AUTHORITY": "municipal", "BEHIND THE METER": "behind_the_meter",
}


def _own(v):
    s = str(v).strip().upper()
    return _OWN.get(s, s.lower().replace(" ", "_"))


def read_year(path: str, year: int) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        name = _find_sheet(z, year)
        raw = pd.read_excel(io.BytesIO(z.read(name)), header=None, dtype=object)
    # header row: the one naming the utility id column
    hdr_i = next(i for i in range(10) if any(
        str(x).strip().upper() in ("UTILITY NUMBER", "UTILITY_ID") for x in raw.iloc[i]))
    hdr = [str(x).strip() for x in raw.iloc[hdr_i]]
    up = [h.upper() for h in hdr]
    c_id = next(i for i, h in enumerate(up) if h in ("UTILITY NUMBER", "UTILITY_ID"))
    c_name = next(i for i, h in enumerate(up) if h in ("UTILITY NAME", "UTILITY_NAME"))
    c_state = next(i for i, h in enumerate(up) if h in ("STATE", "STATE_CODE"))
    c_own = next(i for i, h in enumerate(up) if h in ("OWNERSHIP", "OWNER TYPE"))
    c_part = next(i for i, h in enumerate(up)
                  if h in ("PART", "SCHED4PART") or h.startswith("SCHEDULE 4 PART"))
    # residential block starts at the first revenue column; layouts differ by year
    for key in ("RES REVENUE (000)", "RESIDENTIAL_REVENUES"):
        if key in up:
            c_res = up.index(key)
            break
    else:
        c_res = next(i for i, h in enumerate(up) if "DOLLARS" in h)
    # blocks of three: residential, commercial, industrial, transportation/other, total.
    # The total block is located by name where the layout names it, else by position.
    named_tot = [i for i, h in enumerate(up) if h in ("TOTAL REVENUE (000)", "TOTAL_REVENUES")]
    c_tot = named_tot[0] if named_tot else c_res + 12
    rows = []
    for _, r in raw.iloc[hdr_i + 1:].iterrows():
        uid = _num(r.iloc[c_id])
        if uid is None:
            continue
        rows.append({
            "year": year, "utility_id": int(uid), "utility_name": str(r.iloc[c_name]).strip(),
            "state": str(r.iloc[c_state]).strip(), "part": str(r.iloc[c_part]).strip(),
            "ownership": _own(r.iloc[c_own]),
            "res_rev_k": _num(r.iloc[c_res]), "res_mwh": _num(r.iloc[c_res + 1]),
            "res_cust": _num(r.iloc[c_res + 2]),
            "ind_mwh": _num(r.iloc[c_res + 7]),
            "tot_mwh": _num(r.iloc[c_tot + 1]),
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zips", required=True, help="directory of f861_<year>.zip files")
    ap.add_argument("--out", required=True)
    ap.add_argument("--utility", action="append", required=True, help="ID:STATE, repeatable")
    ap.add_argument("--years", default="2004-2024")
    a = ap.parse_args()
    y0, y1 = (int(x) for x in a.years.split("-"))
    want = [(int(u.split(":")[0]), u.split(":")[1]) for u in a.utility]
    out = []
    for y in range(y0, y1 + 1):
        p = os.path.join(a.zips, f"f861_{y}.zip")
        df = read_year(p, y)
        df = df[df["part"].str.upper().str.startswith("A")]
        for st in sorted({s for _, s in want}):
            s = df[(df["state"] == st) & df["res_mwh"].notna() & (df["res_mwh"] > 0) & df["res_rev_k"].notna()]
            st_price = 100 * 1000 * s["res_rev_k"].sum() / (1000 * s["res_mwh"].sum())
            for uid, ust in want:
                if ust != st:
                    continue
                u = df[(df["utility_id"] == uid) & (df["state"] == st)]
                if u.empty:
                    out.append({"year": y, "utility_id": uid, "state": st, "found": 0,
                                "state_res_cents_kwh": round(st_price, 3)})
                    continue
                own = u["ownership"].iloc[0]
                peers = s[(s["ownership"] == own) & (s["utility_id"] != uid)]
                peer_price = (100 * peers["res_rev_k"].sum() / peers["res_mwh"].sum()) if len(peers) else None
                rev, mwh = u["res_rev_k"].sum(min_count=1), u["res_mwh"].sum(min_count=1)
                price = (100 * rev * 1000 / (mwh * 1000)) if (rev and mwh) else None
                out.append({
                    "year": y, "utility_id": uid, "utility_name": u["utility_name"].iloc[0],
                    "state": st, "found": 1,
                    "res_rev_k": rev, "res_mwh": mwh, "res_cust": u["res_cust"].sum(min_count=1),
                    "res_cents_kwh": None if price is None else round(price, 3),
                    "ind_mwh": u["ind_mwh"].sum(min_count=1), "tot_mwh": u["tot_mwh"].sum(min_count=1),
                    "state_res_cents_kwh": round(st_price, 3),
                    "ownership": own, "peer_n": len(peers),
                    "peer_res_cents_kwh": None if peer_price is None else round(peer_price, 3),
                })
    cols = ["year", "utility_id", "utility_name", "state", "found", "res_rev_k", "res_mwh",
            "res_cust", "res_cents_kwh", "ind_mwh", "tot_mwh", "state_res_cents_kwh",
            "ownership", "peer_n", "peer_res_cents_kwh"]
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in out:
            w.writerow({k: r.get(k) for k in cols})
    print(f"wrote {len(out)} rows -> {a.out}")


if __name__ == "__main__":
    main()
