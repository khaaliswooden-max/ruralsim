#!/usr/bin/env python3
"""Build the public RuralSim website into public/ (static; Vercel serves it as-is).

    python3 tools/build_site.py

Standard library only, so the Vercel build image needs no installs. Inputs are the
committed outputs of the simulation pipeline: worlds/*/viewer + viewer_data + renders,
experiments/ledger (latest 20-seed run per card), national/, pilots/. Political columns
in pilots/ are never read into the site (D-007).
"""
import csv, glob, json, math, os, re, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
OUT = ROOT / "public"

ARCHETYPE = {
    "great_plains_farming": "Great Plains farming",
    "appalachian_persistent_poverty": "Appalachian persistent poverty",
    "black_belt_persistent_poverty": "Black Belt persistent poverty",
    "mountain_west_recreation": "Mountain West recreation",
    "tribal_lands": "Tribal lands",
}

# Pre-stated success criteria, transcribed from experiments/seed_experiments.yaml.
# value(primary) -> the number compared with the threshold, per seed.
CARDS = {
    "EXP-0001": dict(label="Change in 90th-percentile ambulance response time", unit="%",
                     value=lambda p: p.get("change_pct"), op="<=", threshold=-15),
    "EXP-0002": dict(label="Change in mean travel time to primary care", unit="%",
                     value=lambda p: p.get("change_pct"), op="<=", threshold=-30),
    "EXP-0003": dict(label="Change in hospital-feeder outage hours per year", unit="%",
                     value=lambda p: p.get("change_pct"), op="<=", threshold=-50),
    "EXP-0004": dict(label="Unserved households covered at 100/20 Mbps", unit="%",
                     value=lambda p: 100 * p["share_unserved_covered"], op=">=", threshold=95),
    "EXP-0005": dict(label="Field-robot missions completed", unit="%",
                     value=lambda p: p.get("mission_completion_rate"), op=">=", threshold=90),
    "EXP-0006": dict(label="Households reachable within 30 minutes by drone", unit="%",
                     value=lambda p: 100 * p["drone_intervention"], op=">=", threshold=80,
                     baseline=lambda p: 100 * p["road_baseline"], baseline_label="by road today"),
    "EXP-0007": dict(label="Electricity rate change for the lowest-income fifth", unit="%",
                     value=lambda p: p.get("lowest_quintile_rate_change_pct_with_onsite"), op="<=", threshold=2),
    "EXP-0008": dict(label="Winters with all 72 outage hours served", unit="%",
                     value=lambda p: 100 * p["share_served"], op=">=", threshold=95),
    "EXP-0009": dict(label="Clinic AI availability during internet outages", unit="%",
                     value=lambda p: p.get("availability_during_outages_pct"), op=">=", threshold=99),
    "EXP-0010": dict(label="Conditional statement only", unit="", value=None, op=None, threshold=None),
}

CONSTRAINT_NAMES = {
    "no_loss_of_essential_service": "No household loses an essential service",
    "protect_lowest_income_quintile": "Lowest-income fifth is not made worse off",
    "water_within_recharge": "Water use stays within recharge",
    "no_displacement": "No one is displaced",
    "worst_off_decile_must_gain": "Worst-off tenth of households gains",
    "political_variables_excluded": "Political variables excluded",
}


def pct(vals, q):
    s = sorted(vals)
    k = (len(s) - 1) * q / 100
    f, c = math.floor(k), math.ceil(k)
    return s[f] if f == c else s[f] + (s[c] - s[f]) * (k - f)


def mean(xs):
    return sum(xs) / len(xs)


def county_dirs():
    out = {}
    for d in sorted((ROOT / "worlds").iterdir()):
        if d.is_dir():
            out[d.name[:5]] = d.name
    return out


def build_pilots(dirs):
    with open(ROOT / "pilots" / "pilot_counties.csv") as fh:
        rows = {r["fips5"]: r for r in csv.DictReader(fh)}
    geo = json.load(open(ROOT / "pilots" / "pilot_county_boundaries.geojson"))
    # one shared scale: km per unit identical for every county, so sizes are comparable
    shapes = []
    for f in geo["features"]:
        fips = f["properties"]["fips5"]
        g = f["geometry"]
        rings = g["coordinates"] if g["type"] == "Polygon" else [r for poly in g["coordinates"] for r in poly]
        lat0 = float(rows[fips]["centroid_lat"])
        kx = 111.32 * math.cos(math.radians(lat0))
        pts = [[(x * kx, -y * 110.57) for x, y in ring] for ring in rings]
        xs = [p[0] for r in pts for p in r]; ys = [p[1] for r in pts for p in r]
        minx, miny = min(xs), min(ys)
        pts = [[(x - minx, y - miny) for x, y in r] for r in pts]
        w, h = max(xs) - minx, max(ys) - miny
        d = " ".join("M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in r) + " Z" for r in pts)
        shapes.append((fips, w, h, d))
    pilots = []
    for fips, w, h, d in shapes:
        r = rows[fips]
        pilots.append({
            "fips": fips, "dir": dirs[fips],
            "name": r["county_name"], "state": r["state_abbr"],
            "archetype": ARCHETYPE.get(r["archetype"], r["archetype"]),
            "selection_rule": r["selection_rule"],
            "land_area_sqmi": round(float(r["land_area_sqmi"])),
            "pop_2024": int(float(r["pop_2024_estimate"])),
            "peak_pop": int(float(r["peak_pop"])), "peak_decade": r["peak_pop_decade"],
            "pct_of_peak": round(float(r["pop_2020_pct_of_peak"])),
            "poverty_rate": float(r["poverty_rate_2023"]),
            "median_income": int(float(r["median_hh_income_2023"])),
            "hospitals": r["hospitals"],
            "width_km": round(w, 2), "height_km": round(h, 2), "path": d,
        })
    order = ["31173", "16081", "54047", "20019", "01131"]
    pilots.sort(key=lambda p: order.index(p["fips"]) if p["fips"] in order else 99)
    return pilots


def build_experiments(pilots):
    # stdlib-only: card text fields are read from the YAML with a small regex reader
    import_yaml_free = (ROOT / "experiments" / "seed_experiments.yaml").read_text()
    names = {p["fips"]: f'{p["name"]}, {p["state"]}' for p in pilots}
    cards = []
    for cid, spec in CARDS.items():
        files = sorted(glob.glob(str(ROOT / "experiments" / "ledger" / cid / "*_20seeds.json")))
        if not files:
            continue
        run = json.load(open(files[-1]))
        seeds = run["seed_results"]
        block = re.search(rf"- id: {cid}\n(.*?)(?=\n- id: |\Z)", import_yaml_free, re.S).group(1)

        def field(key):
            m = re.search(rf"^\s+{key}:\s*(.+?)\s*$", block, re.M)
            return m.group(1).strip().strip("'\"") if m else ""
        fips = re.search(r"counties:\s*\n?\s*-?\s*\[?'?\"?(\d{5})", block).group(1)
        entry = {
            "id": cid, "title": run["title"], "county": names.get(fips, fips), "fips": fips,
            "hypothesis": field("hypothesis"), "criterion": field("success_criterion"),
            "risks": field("risks_to_residents"), "provenance": run["provenance_floor"],
            "label": spec["label"], "unit": spec["unit"], "op": spec["op"], "threshold": spec["threshold"],
            "constraints_all": run["constraints_passed_all_seeds"],
        }
        cons = {}
        for s in seeds:
            for k, v in s["constraints"].items():
                cons.setdefault(k, []).append(v["passed"])
        entry["constraints"] = [{"name": CONSTRAINT_NAMES.get(k, k), "passed": all(v),
                                 "seeds_failed": v.count(False)} for k, v in cons.items()]
        rq = {}
        for side in ("rqli_baseline", "rqli_intervention"):
            rq[side] = {k: round(mean([s[side][k] for s in seeds]), 4)
                        for k in ("p10", "p50", "p90", "mean", "worst_off_decile_mean")}
        entry["rqli"] = rq
        if spec["value"] is None:
            entry["values"] = []
            entry["verdict"] = "conditional"
            entry["statement"] = seeds[0]["primary"].get("statement", "")
        else:
            vals = [float(spec["value"](s["primary"])) for s in seeds]
            entry["values"] = [round(v, 3) for v in vals]
            lo, hi = pct(vals, 5), pct(vals, 95)
            entry["interval90"] = [round(lo, 2), round(hi, 2)]
            entry["mean"] = round(mean(vals), 2)
            ok = hi <= spec["threshold"] if spec["op"] == "<=" else lo >= spec["threshold"]
            # met = the whole 90% interval clears the threshold AND every hard constraint holds
            entry["criterion_cleared"] = bool(ok)
            entry["verdict"] = "met" if ok and run["constraints_passed_all_seeds"] else "not_met"
            if "baseline" in spec:
                entry["baseline_mean"] = round(mean([spec["baseline"](s["primary"]) for s in seeds]), 2)
                entry["baseline_label"] = spec["baseline_label"]
        cards.append(entry)
    return cards


NAT_COLS = [
    ("fips5", "fips", str), ("county_name", "name", str), ("state_abbr", "st", str),
    ("rucc_2023", "rucc", float), ("nonmetro_2023", "nonmetro", float),
    ("pop_2024_estimate", "pop", float), ("pop_change_2020_2024_pct", "chg", float),
    ("pop_2020_pct_of_peak", "peakpct", float), ("median_hh_income_2023", "income", float),
    ("poverty_rate_2023", "poverty", float), ("n_hospitals", "hosp", float),
    ("n_critical_access_hospitals", "cah", float), ("pct_65_plus_2020", "age65", float),
    ("typ_persistent_poverty_1721", "pp", float),
]


def build_national():
    rows = []
    with open(ROOT / "national" / "tier_a_county_stats.csv") as fh:
        for r in csv.DictReader(fh):
            o = {}
            for src, dst, t in NAT_COLS:
                v = r.get(src, "")
                if t is float:
                    try:
                        v = float(v)
                        v = None if math.isnan(v) else (int(v) if v.is_integer() else round(v, 1))
                    except ValueError:
                        v = None
                o[dst] = v
            rows.append(o)
    return rows


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    dirs = county_dirs()
    pilots = build_pilots(dirs)

    # static pages + assets
    for p in SITE.iterdir():
        (shutil.copytree if p.is_dir() else shutil.copy2)(p, OUT / p.name)

    # 3D worlds: viewer + data + renders; add a link back to the site
    back = ('<a href="/" id="sitehome" style="position:fixed;z-index:10;left:12px;bottom:12px;'
            'font:500 13px/1 \'Public Sans\',system-ui,sans-serif;color:#12181d;background:#d9a441;'
            'padding:9px 12px;border-radius:6px;text-decoration:none">All counties</a>')
    for fips, name in dirs.items():
        src, dst = ROOT / "worlds" / name, OUT / "worlds" / name
        for sub in ("viewer", "viewer_data"):
            if (src / sub).exists():
                shutil.copytree(src / sub, dst / sub)
        idx = dst / "viewer" / "index.html"
        html = idx.read_text()
        html = html.replace("<body>", "<body>\n" + back, 1)
        html = html.replace("</head>", '<link rel="icon" href="/favicon.svg" type="image/svg+xml">\n</head>', 1)
        # the build-time note box sits bottom-left; nudge it above the link
        html = html.replace("#note { position:fixed; left:12px; bottom:12px;",
                            "#note { position:fixed; left:12px; bottom:56px;", 1)
        idx.write_text(html)

    data = OUT / "data"
    data.mkdir(exist_ok=True)
    (data / "pilots.json").write_text(json.dumps(pilots))
    (data / "experiments.json").write_text(json.dumps(build_experiments(pilots)))
    (data / "national.json").write_text(json.dumps(build_national(), separators=(",", ":")))
    shutil.copy2(ROOT / "national" / "tier_a_county_stats.csv", data / "tier_a_county_stats.csv")

    n = sum(1 for _ in OUT.rglob("*") if _.is_file())
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
    print(f"site built: {n} files, {size:.1f} MB -> {OUT}")


if __name__ == "__main__":
    main()
