"""Run a proposal card (spec v0.2, D-111, D-114).

    python3 -m tools.engines.ai_infra.run_proposal proposals/PC-2026-0001.yaml --seeds 20
    python3 -m tools.engines.ai_infra.run_proposal proposals/PC-2026-0001.yaml --no-write

Every option, no build included, runs all five modules on the same seed streams. A module a card
cannot feed is reported blocked or indeterminate, never dropped; for no build, a module with no
site to screen (flood, fiber, water draw) is reported not applicable. Each build option's
difference from no build is computed per seed, then summarised. Refusals and holds write a ledger
record with the reason and no results. Every result is SPECULATIVE.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json

import h3
import numpy as np
import yaml
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from tools.engines.ai_infra import (cooling_water, data, fiber, fiscal, flood, gate, network, power_flow,
                                    proposal, rate_impact, run, tribal)
from tools.engines.ai_infra.run import band

NOT_APPLICABLE = "not applicable: no build places no site"


def _site_xy(county, f_enu, site):
    lat, lon = h3.cell_to_latlng(site["geography_id"])
    x, y = f_enu(lon, lat)
    cell = Polygon([f_enu(lo, la) for la, lo in h3.cell_to_boundary(site["geography_id"])])
    return (x, y), (lon, lat), cell


def run_card(ecard, seeds, cfg, activsg):
    fips5 = ecard["counties"][0]
    county = data.County(fips5)
    tier = data.tier_a()
    trow = tier[tier.fips5 == fips5].iloc[0]
    state = trow.state_abbr
    f_enu, f_wgs = county.enu
    b = county.json("viewer_data/boundaries.json")
    poly = unary_union([Polygon(p).buffer(0) for p in b["county_parts"]])
    tstat = tribal.county_status(poly, tribal.parts(county))

    # Sites: public geography only, never moved; outside the county or on tribal land is refused.
    sites, why = {}, []
    for o in ecard["options"]:
        if o["is_no_build"]:
            continue
        xy, lonlat, cell = _site_xy(county, f_enu, o["site"])
        if not poly.contains(Point(xy)):
            why.append(f"option {o['option_id']}: site cell centroid is outside the county")
        hit = tribal.touches(cell, tstat)
        if hit:
            # D-420: a nation's request covers only its own land; every nation whose land the cell touches must be the submitter
            nation_ok = (ecard["submitter_verified"] and ecard["publication"] == "nation_terms"
                         and set(ecard["submitter_nation_geoids"]) >= {t["geoid"] for t in hit})
            if not nation_ok:
                why.append(f"option {o['option_id']}: site touches tribal land ({', '.join(t['name'] for t in hit)}); "
                           "refused under D-420 unless the card is that nation's government's (verified before intake)")
        sites[o["option_id"]] = {"xy": xy, "lonlat": lonlat, **o["site"]}
    if why:
        raise proposal.Refused(why)

    pmask = tribal.population_mask(fips5, tstat)
    ff, ff_entries = fiscal.build(fips5, state)
    feats = county.json("layers_raw/osm/power.geojson")["features"]
    net = network.build(feats, f_enu, poly, cfg["network"])
    cands = rate_impact.candidates(fips5, state, run.eia_for(2024), 2024)
    acs = data.acs_income_quintiles()
    arow = acs[acs.fips5 == fips5]
    arow = arow.iloc[0].to_dict() if len(arow) else None
    income_masked = pmask["income_row"] is None
    if isinstance(pmask["income_row"], dict):
        arow = {**(arow or {}), **pmask["income_row"]}
    hh_in = run.households_input(fips5, tier)

    # Per-site context, fixed across seeds.
    ctx = {}
    fstat = flood.county_status(data.nfhl_status(), fips5)
    asof = cfg["fiber"]["bdc_as_of"]
    crow = data.bdc_fiber(asof, "fiber_county")
    crow = crow[crow.fips5 == fips5]
    for oid, st in sites.items():
        lon, lat = st["lonlat"]
        ctx[oid] = {
            "water": run.water_context(county, fips5, lat, lon, cfg),
            "flood_zones": (flood.prepare(data.nfhl_zones(fips5), f_enu, st["xy"], cfg["flood"]["search_m"])
                            if fstat and fstat["status"] != "none" else []),
            "fiber": fiber.run(lat, lon, run._fiber_hexes(asof), crow.iloc[0].to_dict() if len(crow) else None,
                               cfg["fiber"]["search_radius_km"]),
        }

    scen_out = {}
    for sc in ecard["scenarios"]:
        nb = sc.get("no_build", False)
        per_seed = []
        for seed in range(seeds):
            r_load, r_on, r_cty, r_pf = (np.random.default_rng([int(fips5), seed, k]) for k in (1, 2, 3, 4))
            L = cfg["load"]
            pue = power_flow.u(r_load, L["pue"])
            lf = power_flow.u(r_load, L["facility_load_factor"])
            pf = power_flow.u(r_load, L["facility_power_factor"])
            it = sc["it_load_mw"]
            peak, avg = it * pue, it * pue * lf
            on, o = sc.get("onsite") or {}, cfg["onsite"]
            st_credit = on.get("storage_mwh", 0) / o["storage_duration_h"] * power_flow.u(r_on, o["storage_peak_availability"])
            net_peak = max(peak - on.get("firm_mw", 0) - st_credit - on.get("solar_mw", 0) * o["solar_peak_credit"], 0.0)
            solar_mwh = on.get("solar_mw", 0) * 8760 * power_flow.u(r_on, o["solar_capacity_factor"])
            grid_mwh = max(avg * 8760 - solar_mwh, 0.0)
            onsite_capex = (on.get("solar_mw", 0) * power_flow.u(r_on, cfg["costs"]["solar_musd_per_mw"])
                            + on.get("storage_mwh", 0) * power_flow.u(r_on, cfg["costs"]["storage_musd_per_mwh"])
                            + on.get("firm_mw", 0) * power_flow.u(r_on, cfg["costs"]["firm_musd_per_mw"])) * 1e6
            cpeak, cinfo = run.county_load(fips5, cands, tier, cfg, r_cty, hh_in)
            cpf = power_flow.u(r_cty, L["county_power_factor"])
            if cpeak is None:
                pfo = {"status": "blocked", "reason": cinfo["reason"]}
            elif nb:
                pfo = power_flow.base_only(net, cpeak, cpf, cfg, activsg, state, r_pf)
            else:
                pfo = power_flow.run(net, sites[sc["option_id"]]["xy"], net_peak, pf, cpeak, cpf, cfg, activsg, state, r_pf)
            rates = {}
            for alloc in rate_impact.ALLOCATIONS:
                rr = np.random.default_rng([int(fips5), seed, 5])
                if pfo.get("status") == "computed":
                    rates[alloc] = rate_impact.run(cands, pfo.get("required_upgrades"),
                                                   {"peak_mw_net": 0.0 if nb else net_peak, "grid_mwh": 0.0 if nb else grid_mwh},
                                                   {"capex_usd": onsite_capex}, alloc, arow, cfg, rr)
                else:
                    rates[alloc] = {"status": "blocked", "reason": f"power_flow {pfo.get('status')}"}
            seed_rec = {"seed": seed, "inputs": {"it_load_mw": it, "pue": pue, "facility_load_factor": lf,
                                                 "facility_peak_mw": peak, "net_peak_mw": net_peak, "grid_mwh": grid_mwh,
                                                 "county_peak_mw": cpeak, "county_load_info": cinfo,
                                                 "onsite_capex_usd": onsite_capex},
                        "power_flow": pfo, "rate_impact": rates}
            if not nb:
                c = ctx[sc["option_id"]]
                w = c["water"]
                seed_rec["cooling_water"] = cooling_water.run(
                    w["weather"], avg / pue, pue, sc["cooling"], w["county_use"], (w["source_gauge"], w["nearest_gauge"]),
                    w["community_water_systems"], cfg, np.random.default_rng([int(fips5), seed, 6]))
                seed_rec["flood"] = flood.run(fstat, c["flood_zones"], sites[sc["option_id"]]["xy"], cfg,
                                              np.random.default_rng([int(fips5), seed, 7]))
            per_seed.append(seed_rec)
        if income_masked:
            for r_ in (x for s_ in per_seed for x in s_["rate_impact"].values()):
                for u_ in r_.get("per_utility", []):
                    u_["lowest_quintile_energy_cost_share_change_pp"] = run.MASKED_INCOME
                    for c_ in (u_.get("cases") or {}).values():
                        c_["lowest_quintile_energy_cost_share_change_pp"] = run.MASKED_INCOME
        summ = {"modules": True, "power_rates": run.summarise(per_seed, cands)}
        if nb:
            summ.update(cooling_water=NOT_APPLICABLE, flood=NOT_APPLICABLE, fiber=NOT_APPLICABLE)
        else:
            summ.update(cooling_water=run.summarise_water(per_seed), flood=run.summarise_flood(per_seed),
                        fiber={"fiber": True, **ctx[sc["option_id"]]["fiber"]})
        scen_out[sc["name"]] = {"scenario": sc, "summary": summ, "seeds": per_seed}

    site_rec = {oid: {"lon": st["lonlat"][0], "lat": st["lonlat"][1], "enu_m": list(st["xy"]),
                      "resolution": st["resolution"], "geography_id": st["geography_id"],
                      "location_basis": st.get("location_basis"),
                      "note": "engine runs at the cell centroid; the site is the submitter's and is never moved",
                      "provenance": "hypothetical"} for oid, st in sites.items()}
    return {"county": {**county.record(), "state": state, "rucc_2023": int(trow.rucc_2023)},
            "modules": proposal.MODULES, "backtest": None, "eia_year": 2024, "site": site_rec,
            "candidate_utilities": cands, "network": net.summary, "county_households_input": hh_in,
            "flood_context": {"county_status": fstat},
            "water_context": {oid: {k: v for k, v in c["water"].items() if k != "weather"} for oid, c in ctx.items()},
            "fiber_context": {"bdc_as_of": asof},
            "tribal_mask": pmask["tribal_mask"], "fiscal_facts": ff,
            "not_modelled_entries": pmask["entries"] + ff_entries, "scenarios": scen_out}


def judge_card(ecard, rec):
    """Every module's bars, per scenario, with option_id on every item (judged by run.judge per module)."""
    misses, passes = [], []
    f = rec["county"]["fips5"]
    for name, sc in rec["scenarios"].items():
        s = sc["summary"]
        oid = sc["scenario"]["option_id"]
        allowed = set(sc["scenario"].get("allocations") or rate_impact.ALLOCATIONS)
        pr = s["power_rates"]
        pr = {**pr, "rate_impact": {a: v for a, v in pr["rate_impact"].items() if a in allowed}}
        parts = [pr]
        for k in ("cooling_water", "flood", "fiber"):
            if s[k] == NOT_APPLICABLE:
                misses.append({"county": f, "scenario": name, "option_id": oid, "module": k,
                               "criterion": k, "status": "not_applicable", "value": NOT_APPLICABLE})
            else:
                parts.append(s[k])
        for p in parts:
            m, ps = run.judge(ecard, {"county": rec["county"], "site": {"note": ""},
                                      "scenarios": {name: {"summary": p}}})
            misses += [{**x, "option_id": oid} for x in m]
            passes += [{**x, "option_id": oid} for x in ps]
    order = {"miss": 0, "indeterminate": 1, "blocked": 1, "not_applicable": 3}
    misses.sort(key=lambda m: order.get(m["status"], 2))
    return misses, passes


def _per_seed_series(scen):
    """Per-seed values of the comparison outputs, aligned by seed."""
    out = {}
    for s in scen["seeds"]:
        p = s["power_flow"]
        b = p.get("base_case") or {}
        for k in ("max_loading_pct", "min_voltage_pu"):
            v = p.get(k)
            out.setdefault(f"power_flow.{k}", []).append(v if isinstance(v, (int, float)) else None)
            if p.get("no_build"):
                out.setdefault(f"power_flow.{k}.own_base", []).append(v if isinstance(v, (int, float)) else None)
            else:
                bv = b.get(k)
                out.setdefault(f"power_flow.{k}.own_base", []).append(bv if isinstance(bv, (int, float)) else None)
        for alloc, r in s["rate_impact"].items():
            for x in r.get("per_utility", []):
                if x.get("status") == "computed":
                    out.setdefault(f"rate_impact.{alloc}.{x['utility_number']}.lowest_quintile_rate_change_pct", []
                                   ).append(x["lowest_quintile_rate_change_pct"])
        cw = s.get("cooling_water")
        if cw:
            for k in ("annual_withdrawal_m3", "peak_day_withdrawal_m3"):
                out.setdefault(f"cooling_water.{k}", []).append(cw.get(k))
    return out


def comparison(rec, ecard, misses):
    """Per option and output: p10/p50/p90 and the difference from no build, computed per seed and then
    summarised (never the difference of two medians). Grid differences use each option's own base
    case (the county as it stands, solved in the same seed with the same draws); rate and water
    differences use no build's own values, which are zero by construction."""
    scen = rec["scenarios"]
    nb = scen["no_build"]
    nbs = _per_seed_series(nb)
    out = {}
    for name, sc in scen.items():
        oid = sc["scenario"]["option_id"]
        ser = _per_seed_series(sc)
        rows = {}
        for k, xs in ser.items():
            if k.endswith(".own_base"):
                continue
            row = {"value": band(xs)}
            if name != "no_build":
                if k.startswith("power_flow."):
                    base = ser.get(k + ".own_base", [])
                    basis = "option's own base case, same seed and draws"
                else:
                    base = nbs.get(k, [0.0] * len(xs))
                    basis = "no build, same seed"
                d = [a - b_ for a, b_ in zip(xs, base) if isinstance(a, (int, float)) and isinstance(b_, (int, float))]
                row.update(difference_from_no_build=band(d), difference_basis=basis)
            rows[k] = row
        out[name] = {"option_id": oid, "misses_first": [m for m in misses if m.get("scenario") == name
                                                         and m["status"] != "not_applicable"],
                     "outputs": rows}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("card_path")
    ap.add_argument("--seeds", type=int)
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)
    cfg = yaml.safe_load((run.HERE / "params" / "assumed.yaml").read_text())
    activsg = json.loads((run.HERE / "params" / "activsg_distributions.json").read_text())
    raw, sha = proposal.load(a.card_path)
    t0 = dt.datetime.now(dt.UTC)
    base = {"run_id": f"{raw.get('card_id')}/{t0.strftime('%Y%m%dT%H%M%SZ')}", "card_id": raw.get("card_id"),
            "run_kind": "proposal_card", "grade": "SPECULATIVE", "disclosure": run.DISCLOSURE,
            "engine": "tools/engines/ai_infra", "engine_version": run.git_commit(), "spec_version": run.SPEC_VERSION,
            "params_sha256": run.sha(run.HERE / "params" / "assumed.yaml"),
            "activsg_sha256": run.sha(run.HERE / "params" / "activsg_distributions.json"),
            "environment": run.environment(), "card_sha256": sha}
    recs, status = [], "run"
    try:
        ecard = proposal.compile_card(raw, sha)
        held = proposal.holds(ecard["counties"][0])
        if held:
            raise proposal.Held(held[0])
        seeds = a.seeds or ecard["seeds"]
        rec = run_card(ecard, seeds, cfg, activsg)
        misses, passes = judge_card(ecard, rec)
        recs = [rec]
        out = {**base, "status": "run", "proposal_card": ecard["proposal_card"], "publication": ecard["publication"],
               "tribal_mask": rec["tribal_mask"], "seeds": seeds,
               "mode": "promotable-count" if seeds >= 20 else "screening", "provenance_floor": "assumed",
               "criterion": ecard["criterion"], "criteria_set_by": ecard["proposal_card"]["bars_set_by"],
               "options": [{k: v for k, v in o.items() if k != "site"} for o in ecard["options"]],
               "misses": misses, "passes": passes, "comparison": comparison(rec, ecard, misses),
               "fiscal_facts": rec["fiscal_facts"],
               "stated_not_checked": ({"label": "stated by the submitter, not checked by RuralSim",
                                       "items": ecard["stated_not_checked"]} if ecard["stated_not_checked"] else None),
               "decision": ecard["decision"], "county_rules": ecard["county_rules"],
               "eia_tables": {2024: data.eia_meta(2024)}, "acs_tables": {"year": 2024, "meta": data.acs_meta(2024)},
               "water_tables": data.water_meta(), "flood_tables": data.nfhl_meta(),
               "bdc_tables": data.bdc_meta(cfg["fiber"]["bdc_as_of"]), "counties": recs}
    except proposal.Refused as e:
        status = "refused"
        out = {**base, "status": "refused", "reasons": e.reasons, "counties": []}
    except proposal.Held as e:
        status = "held"
        out = {**base, "status": str(e), "reason": "back-test county or brief candidate: held until step 3's first "
                                                      "back-test run is recorded (PREREGISTRATION §8)", "counties": []}
    run.finish(out, recs, proposal.MODULES)
    if not a.no_write:
        d = run.LEDGER / str(raw.get("card_id"))
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{t0.strftime('%Y%m%dT%H%M%S')}_{status}.json"
        p.write_text(json.dumps(out, indent=1, default=float))
        print("wrote", p.relative_to(run.ROOT))
    if status == "run":
        print(f"misses/indeterminate: {sum(1 for m in out['misses'] if m['status'] != 'not_applicable')}  "
              f"passes: {len(out['passes'])}")
    else:
        print(status + ":", out.get("reasons") or out.get("reason"))
    return out


if __name__ == "__main__":
    main()
