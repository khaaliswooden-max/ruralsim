#!/usr/bin/env python3
"""Load-time budget check for the county viewer (D-500), run in CI.

    pip install playwright PyYAML && python -m playwright install --with-deps chromium
    python3 tools/perf/viewer_budget.py                        # every county and line in specs/perf_budget.yaml
    python3 tools/perf/viewer_budget.py --legacy               # the pre-D-500 viewer, for a before/after
    python3 tools/perf/viewer_budget.py --record-ceilings      # print ceilings to paste into the budget file

What it measures is this branch's viewer, not what is published: the viewer is built from
tools/viewer_template.html exactly as publish_world.py builds it (branded, .gz data, shared
three.js), and served from two local servers that stand in for production:
  * a "worlds" server like R2: the county's published viewer_data .gz files, downloaded from
    R2 once and served as stored, with no compression on the way (r2.dev behaves this way);
  * a "site" server like ruralsim.io on Vercel: site/vendor/ with Content-Encoding and CORS.
Each load is cold (cache disabled) in headless Chromium, throttled with DevTools to the
budget's profiles. Requests to any other host (favicons on ruralsim.io) are blocked, so the
numbers depend only on this branch and the county's data.

Metrics, per county and profile, median of `runs` loads:
  first_paint_s  navigation to window.__RURALSIM_FIRST_DRAW (county outline on screen);
                 the legacy viewer has no such flag and draws nothing until it is usable
  usable_s       navigation to window.__RURALSIM_READY plus two frames: every layer in
  bytes          bytes on the wire, all requests
  vendor_bytes   bytes on the wire for three.module.js and OrbitControls.js

Caveat: headless Chromium draws WebGL in software (SwiftShader), so usable_s includes CPU work
a real GPU does faster. first_paint_s and the byte counts are network-bound and transfer well.
Exit 1 when an enforced line or a regression ceiling is missed. Writes perf_results.json and,
under GitHub Actions, a job summary with misses first.
"""
from __future__ import annotations

import argparse, contextlib, functools, gzip, http.server, json, os, pathlib, shutil, statistics
import subprocess, sys, threading, time, urllib.request

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import yaml  # noqa: E402
import build_site as bs  # noqa: E402

DATA_FILES = ["boundaries.json", "bridges.json", "buildings.json", "facilities.json", "hydrology.json",
              "layer_meta.json", "population_series.json", "power_lines.json", "power_points.json",
              "rail.json", "roads.json", "terrain_grid.f32", "terrain_meta.json"]
WORLD_PORT, SITE_PORT = 8761, 8762


# ---------------- servers ----------------
class WorldHandler(http.server.SimpleHTTPRequestHandler):
    """Like r2.dev: files as stored, .gz served as application/gzip with no Content-Encoding."""
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".gz": "application/gzip", ".js": "text/javascript", ".f32": "application/octet-stream"}

    def log_message(self, *a):
        pass


class SiteHandler(http.server.SimpleHTTPRequestHandler):
    """Like Vercel for /vendor/: compressed for clients that accept it, CORS open, cacheable."""
    def log_message(self, *a):
        pass

    def do_GET(self):
        p = pathlib.Path(self.translate_path(self.path))
        if not p.is_file():
            return self.send_error(404)
        body = p.read_bytes()
        enc = "gzip" in (self.headers.get("Accept-Encoding") or "")
        if enc:
            body = _gz_cached(str(p))
        self.send_response(200)
        self.send_header("Content-Type", "text/javascript" if p.suffix == ".js" else "application/octet-stream")
        if enc:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        self.wfile.write(body)


@functools.lru_cache(maxsize=None)
def _gz_cached(path: str) -> bytes:
    return gzip.compress(pathlib.Path(path).read_bytes(), compresslevel=9, mtime=0)


@contextlib.contextmanager
def serve(root: pathlib.Path, handler, port: int):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(handler, directory=str(root)))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()


# ---------------- county worlds ----------------
def fetch_county(base: str, c: dict, cache: pathlib.Path) -> pathlib.Path:
    """Download the county's published viewer_data .gz files once."""
    vd = cache / c["dir"] / "viewer_data"
    vd.mkdir(parents=True, exist_ok=True)
    for f in DATA_FILES:
        dst = vd / (f + ".gz")
        if dst.exists() and dst.stat().st_size:
            continue
        url = f"{base}/worlds/{c['dir']}/current/viewer_data/{f}.gz"
        req = urllib.request.Request(url, headers={"User-Agent": "ruralsim-perf-check"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    dst.write_bytes(r.read())
                break
            except Exception as e:
                if attempt == 3:
                    raise SystemExit(f"{c['dir']}: cannot download {f}.gz: {e}")
                time.sleep(2 ** attempt)
    return vd


def build_viewer(c: dict, root: pathlib.Path, site_origin: str, legacy_tpl: str | None):
    """Write <root>/<dir>/viewer/index.html as publish_world.py would (D-031, D-055, D-500)."""
    vdir = root / c["dir"] / "viewer"
    vdir.mkdir(parents=True, exist_ok=True)
    tpl = legacy_tpl if legacy_tpl is not None else (REPO / "tools" / "viewer_template.html").read_text()
    st, name = c["dir"].rsplit("_", 1)[1].upper(), c["name"]
    html = (tpl.replace("{{COUNTY_NAME}}", name).replace("{{ST}}", st).replace("{{FIPS}}", c["fips5"])
               .replace("{{KIND}}", "county").replace("{{UTM}}", "UTM"))
    html = bs.brand_viewer_html(html, home=bs.SITE_URL + "/")
    if legacy_tpl is not None:
        # as published before D-500: .gz data, three.js uncompressed beside the viewer
        html = html.replace(bs.FETCH_PLAIN, bs.FETCH_GZ, 1).replace(bs.TERRAIN_PLAIN, bs.TERRAIN_GZ, 1)
        shutil.copytree(REPO / "site" / "vendor" / f"three-r{bs.THREE_REV}", vdir / "vendor", dirs_exist_ok=True)
    else:
        html = html.replace(bs.GZ_OFF, bs.GZ_ON, 1)
        html, status = bs.upgrade_viewer(html, three_base=site_origin + bs.SHARED_VENDOR)
        assert status == "current", status
    (vdir / "index.html").write_text(html)
    return f"/{c['dir']}/viewer/index.html"


# ---------------- one load ----------------
def load_once(browser, url: str, prof: dict, legacy: bool) -> dict:
    ctx = browser.new_context(viewport={"width": 1366, "height": 768})
    page = ctx.new_page()
    page.route("**/*", lambda r: r.continue_() if r.request.url.startswith("http://127.0.0.1") else r.abort())
    cdp = ctx.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
    cdp.send("Network.emulateNetworkConditions", {
        "offline": False, "latency": prof["rtt_ms"],
        "downloadThroughput": prof["down_mbps"] * 1e6 / 8, "uploadThroughput": prof["up_mbps"] * 1e6 / 8})
    urls, tally = {}, {"bytes": 0, "vendor_bytes": 0, "requests": 0, "failed": 0}
    cdp.on("Network.requestWillBeSent", lambda e: urls.__setitem__(e["requestId"], e["request"]["url"]))

    def fin(e):
        n = e["encodedDataLength"]
        tally["bytes"] += n
        tally["requests"] += 1
        u = urls.get(e["requestId"], "")
        if u.endswith("three.module.js") or u.endswith("OrbitControls.js"):
            tally["vendor_bytes"] += n
    cdp.on("Network.loadingFinished", fin)
    def failed(e):  # requests this harness blocked on purpose (other hosts) are not failures
        if urls.get(e["requestId"], "").startswith("http://127.0.0.1"):
            tally["failed"] += 1
    cdp.on("Network.loadingFailed", failed)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)[:200]))
    t0 = time.perf_counter()
    page.goto(url, wait_until="commit", timeout=300_000)
    first = None
    if not legacy:
        page.wait_for_function("window.__RURALSIM_FIRST_DRAW !== undefined", timeout=300_000, polling=50)
        first = time.perf_counter() - t0
    page.wait_for_function("window.__RURALSIM_READY === true", timeout=600_000, polling=100)
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    usable = time.perf_counter() - t0
    blocked = page.evaluate("() => document.getElementById('loadstatus')?.textContent || ''")
    ctx.close()
    return {"first_paint_s": round(first if first is not None else usable, 2), "usable_s": round(usable, 2),
            **tally, "errors": errors, "status_line": blocked}


# ---------------- budget ----------------
def evaluate(budget: dict, results: dict) -> list[dict]:
    rows = []
    for c in budget["counties"]:
        for ln in budget["lines"]:
            if c["class"] not in ln["classes"]:
                continue
            r = results.get(f"{c['fips5']}/{ln['profile']}")
            if r is None:
                continue
            v = r[ln["metric"]]
            rows.append({"county": c["name"], "line": ln["text"], "kind": "D-500 bar", "metric": ln["metric"],
                         "profile": ln["profile"], "value": v, "bar": ln["max"], "ok": v <= ln["max"],
                         "enforced": bool(ln["enforce"])})
        for block, enforced in (("ceilings", True), ("ceilings_reported", False)):
            for key, ceil in (budget.get(block) or {}).get(c["fips5"], {}).items():
                prof, metric = key.split(".", 1)
                r = results.get(f"{c['fips5']}/{prof}")
                if r is None:
                    continue
                v = r[metric]
                rows.append({"county": c["name"], "line": f"No regression: {metric} at {prof}", "kind": "ceiling",
                             "metric": metric, "profile": prof, "value": v, "bar": ceil, "ok": v <= ceil,
                             "enforced": enforced})
    return rows


def fmt(metric: str, v) -> str:
    return f"{v / 1e6:.2f} MB" if metric == "bytes" else f"{v / 1e3:.0f} KB" if metric == "vendor_bytes" else f"{v:.1f} s"


def summary_md(rows: list[dict], results: dict, budget: dict, legacy: bool) -> str:
    order = lambda r: (r["ok"], not r["enforced"], r["county"])  # noqa: E731
    out = [f"## Viewer load-time budget (D-500){' — legacy viewer' if legacy else ''}", "",
           "Misses first. Headless Chromium, cold cache, DevTools throttling, software WebGL. "
           "Simulated network on a CI runner, not a real rural line.", "",
           "| Result | County | Line | Measured | Bar | Gate |", "|---|---|---|---|---|---|"]
    for r in sorted(rows, key=order):
        res = "PASS" if r["ok"] else "**MISS**"
        gate = "enforced" if r["enforced"] else "reported"
        out.append(f"| {res} | {r['county']} | {r['line']} | {fmt(r['metric'], r['value'])} | "
                   f"{fmt(r['metric'], r['bar'])} | {gate} |")
    out += ["", "| County | Profile | First paint | Usable | Transfer | three.js | Requests |",
            "|---|---|---|---|---|---|---|"]
    names = {c["fips5"]: c["name"] for c in budget["counties"]}
    for k, r in sorted(results.items()):
        f, p = k.split("/")
        out.append(f"| {names[f]} | {p} | {r['first_paint_s']:.1f} s | {r['usable_s']:.1f} s | "
                   f"{r['bytes'] / 1e6:.2f} MB | {r['vendor_bytes'] / 1e3:.0f} KB | {r['requests']} |")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", default=str(REPO / "specs" / "perf_budget.yaml"))
    ap.add_argument("--out", default="perf_results.json")
    ap.add_argument("--cache", default=str(REPO / ".perf_cache"))
    ap.add_argument("--runs", type=int)
    ap.add_argument("--counties", nargs="*", help="FIPS codes to limit the run to")
    ap.add_argument("--legacy", action="store_true", help="measure the viewer as it was before D-500")
    ap.add_argument("--legacy-ref", default="f9bcd01", help="commit whose tools/viewer_template.html is the legacy viewer")
    ap.add_argument("--record-ceilings", action="store_true")
    a = ap.parse_args(argv)
    from playwright.sync_api import sync_playwright

    budget = yaml.safe_load(pathlib.Path(a.budget).read_text())
    runs = a.runs or budget.get("runs", 2)
    base = os.environ.get("RURALSIM_DATA_BASE", budget["data_base"]).rstrip("/")
    counties = [c for c in budget["counties"] if not a.counties or c["fips5"] in a.counties]
    legacy_tpl = None
    if a.legacy:
        legacy_tpl = subprocess.run(["git", "-C", str(REPO), "show", f"{a.legacy_ref}:tools/viewer_template.html"],
                                    check=True, capture_output=True, text=True).stdout
    cache = pathlib.Path(a.cache)
    serve_root = cache / ("legacy" if a.legacy else "current")
    results = {}
    with serve(serve_root, WorldHandler, WORLD_PORT) as world, serve(REPO / "site", SiteHandler, SITE_PORT) as site:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
            for c in counties:
                vd = fetch_county(base, c, cache / "data")
                dst = serve_root / c["dir"] / "viewer_data"
                if not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(vd, dst)
                path = build_viewer(c, serve_root, site, legacy_tpl)
                profs = sorted({ln["profile"] for ln in budget["lines"] if c["class"] in ln["classes"]})
                for p in profs:
                    loads = [load_once(browser, world + path, budget["profiles"][p], a.legacy) for _ in range(runs)]
                    med = {k: statistics.median(x[k] for x in loads)
                           for k in ("first_paint_s", "usable_s", "bytes", "vendor_bytes", "requests", "failed")}
                    med["errors"] = sorted({e for x in loads for e in x["errors"]})
                    med["status_line"] = loads[-1]["status_line"]
                    results[f"{c['fips5']}/{p}"] = med
                    print(f"{c['name']:<14} {p:<8} first paint {med['first_paint_s']:5.1f} s  usable "
                          f"{med['usable_s']:5.1f} s  {med['bytes'] / 1e6:5.2f} MB  three.js "
                          f"{med['vendor_bytes'] / 1e3:5.0f} KB  errors {len(med['errors'])}", flush=True)
            browser.close()

    rows = evaluate(budget, results)
    md = summary_md(rows, results, budget, a.legacy)
    pathlib.Path(a.out).write_text(json.dumps({"legacy": a.legacy, "results": results, "lines": rows}, indent=1))
    print(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write(md)
    if a.record_ceilings:
        ceil, rep = {}, {}
        for k, r in results.items():
            f, p = k.split("/")
            ceil.setdefault(f, {}).update({f"{p}.first_paint_s": round(r["first_paint_s"] * 1.3 + 0.2, 1),
                                           f"{p}.bytes": int(r["bytes"] * 1.05)})
            rep.setdefault(f, {})[f"{p}.usable_s"] = round(r["usable_s"] * 1.3, 1)
        print(yaml.safe_dump({"ceilings": ceil, "ceilings_reported": rep}, sort_keys=True))
    errs = [k for k, r in results.items() if r["errors"] or r["failed"]]
    bad = [r for r in rows if r["enforced"] and not r["ok"]]
    if errs:
        print(f"page errors or failed requests: {errs}")
    if bad or errs:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
