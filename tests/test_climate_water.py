#!/usr/bin/env python3
"""Offline tests for the nClimDiv parser (D-029) and water-system name matching (D-030).

    python3 tests/test_climate_water.py
"""
import pathlib, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import fetch_climate as fc  # noqa: E402
import place_water_systems as pw  # noqa: E402


def climdiv_line(state, county, element, year, vals):
    return f"{state}{county}{element}{year}" + "".join(f"{v:7.2f}" for v in vals) + "   \n"


def test_climdiv():
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        files = {}
        for e, code in fc.ELEMENTS.items():
            p = d / f"climdiv-{e}cy-v1.0.0-20990101"
            lines = []
            for year in range(1990, 2022):  # 1990 and 2021 are outside the normal period
                base = {"tmax": 60.0, "tmin": 30.0, "pcpn": 2.0}[e]
                bump = 100.0 if year in (1990, 2021) else (year - 1991) / 29  # outside years must be ignored
                lines.append(climdiv_line("25", "173", code, year, [base + m + bump for m in range(12)]))
                lines.append(climdiv_line("25", "175", code, year, [base] * 12))  # neighbor county
            # a county with a missing value inside the period must be rejected
            lines.append(climdiv_line("25", "177", code, 2000, [-99.9] * 12))
            p.write_text("".join(lines))
            files[e] = p
        n = fc.climdiv_normals("NE", "31173", files)
        assert n is not None and list(n.index) == list(range(1, 13))
        # mean of bump over 1991..2020 is 0.5
        assert abs(n.loc[1, "tmax_f"] - 60.5) < 1e-9 and abs(n.loc[12, "tmin_f"] - 41.5) < 1e-9, n
        assert abs(n.loc[6, "precip_in"] - 7.5) < 1e-9
        assert n["snow_in"].isna().all() and n["wind_max_mph"].isna().all()
        assert fc.climdiv_normals("NE", "31177", files) is None       # incomplete series
        assert fc.climdiv_normals("NE", "31001", files) is None       # absent county
        assert fc.climdiv_normals("DC", "11001", files) is None       # no nClimDiv state code
    assert fc.NCDC_STATE["NE"] == "25" and fc.NCDC_STATE["WY"] == "48"
    assert fc.NCDC_STATE["HI"] == "49" and fc.NCDC_STATE["AK"] == "50"


def test_norm_and_towns():
    assert pw.norm("Pine Apple town") == "PINE APPLE"
    assert pw.norm("Keystone city") == "KEYSTONE"
    assert pw.norm("NORTHFORK (RR NAME NORTH FORK)") == "NORTHFORK"
    assert pw.norm("St. Marys") == pw.norm("Saint Marys") == "ST MARYS"
    assert pw.norm("Big Sandy CDP") == "BIG SANDY"
    r = {"city_name": "GEORGIANA,PINE APPLE", "city_served": "nan"}
    assert pw.served_towns(r) == ["GEORGIANA", "PINE APPLE"]
    assert pw.served_towns({"city_served": float("nan")}) == []
    assert pw.KEEP_WS_FIELDS == ("pws_name", "city_name", "zip_code")  # no contact fields


if __name__ == "__main__":
    test_climdiv()
    test_norm_and_towns()
    print("test_climate_water: all checks passed")
