"""Progressive viewer and shared three.js (D-500 fixes 2 and 3): template, upgrade and gzip paths."""
import pathlib, sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import build_site as bs  # noqa: E402

TPL = (REPO / "tools" / "viewer_template.html").read_text()
PILOT = (REPO / "worlds" / "01131_wilcox_al" / "viewer" / "index.html").read_text()   # a v1 viewer


def test_template_is_v2_with_gz_off_and_local_vendor():
    assert bs.VIEWER_V2 in TPL and bs.GZ_OFF in TPL
    assert '"./vendor/three.module.js"' in TPL and "'./vendor/OrbitControls.js'" in TPL
    # one importmap + module block, holding everything county-independent
    i, j = bs._script_block(TPL)
    assert "{{" not in TPL[i:j]
    for marker in ("__RURALSIM_FIRST_DRAW", "__RURALSIM_READY", "Promise.allSettled", "loadstatus"):
        assert marker in TPL[i:j], marker


def test_upgrade_v1_pilot_keeps_head_and_hud_and_swaps_script():
    html, st = bs.upgrade_viewer(PILOT, three_base="https://www.ruralsim.io" + bs.SHARED_VENDOR)
    assert st == "upgraded" and bs.VIEWER_V2 in html and bs.GZ_OFF in html   # pilot read plain files
    assert html[:html.index('<script type="importmap">')] == PILOT[:PILOT.index('<script type="importmap">')]
    assert '"https://www.ruralsim.io/vendor/three-r160/three.module.js"' in html
    assert "'https://www.ruralsim.io/vendor/three-r160/OrbitControls.js'" in html
    assert "./vendor/" not in html
    again, st2 = bs.upgrade_viewer(html, three_base="https://www.ruralsim.io" + bs.SHARED_VENDOR)
    assert st2 == "current" and again == html                              # idempotent


def test_upgrade_keeps_gzip_state_of_a_repacked_v1_viewer(tmp_path):
    (tmp_path / "roads.json").write_text("[]")
    v1 = PILOT.replace("{{", "")
    gz_html, gz = bs.gzip_viewer(v1, tmp_path)                             # D-055 legacy patch
    assert gz and "DecompressionStream" in gz_html
    html, st = bs.upgrade_viewer(gz_html)
    assert st == "upgraded" and bs.GZ_ON in html and bs.GZ_OFF not in html


def test_gzip_viewer_flips_the_v2_flag_and_writes_files(tmp_path):
    (tmp_path / "boundaries.json").write_text('{"county": []}')
    html, gz = bs.gzip_viewer(TPL, tmp_path)
    assert [g.name for g in gz] == ["boundaries.json.gz"] and bs.GZ_ON in html
    assert bs.gzip_viewer(html, tmp_path) == (html, [])


def test_upgrade_leaves_unknown_pages_alone():
    assert bs.upgrade_viewer("<html><body>hi</body></html>") == ("<html><body>hi</body></html>", "unrecognised")


def test_shared_vendor_files_match_the_world_copies():
    for f in ("three.module.js", "OrbitControls.js"):
        shared = (REPO / "site" / "vendor" / f"three-r{bs.THREE_REV}" / f).read_bytes()
        assert shared == (REPO / "worlds" / "01131_wilcox_al" / "viewer" / "vendor" / f).read_bytes()
    assert f"REVISION = '{bs.THREE_REV}'" in (REPO / "site" / "vendor" / f"three-r{bs.THREE_REV}" / "three.module.js").read_text()
