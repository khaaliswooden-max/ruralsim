#!/usr/bin/env python3
"""Publish built county worlds to Cloudflare R2 (S3 API) as pinned snapshots (D-031).

    python3 tools/publish_world.py 31173 [16081 ...]     # publish these counties
    python3 tools/publish_world.py --rebuild-index        # rewrite worlds/index.json

Environment (GitHub Actions secrets / variables, or your shell):
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY   credentials (never commit)
    R2_BUCKET                                                bucket name, e.g. ruralsim-data
    RURALSIM_DATA_BASE                                       public base URL of the bucket,
                                                             e.g. https://data.ruralsim.io

Bucket layout, per county directory <dir> = <fips5>_<slug>:
    worlds/<dir>/snapshots/<id>/...        the whole world (layers, layers_raw, stage,
                                           viewer, viewer_data, renders) + validation report
                                           + manifest.json; never overwritten
    worlds/<dir>/current/viewer/           branded viewer, served to the public
    worlds/<dir>/current/viewer_data/      slimmed viewer data
    worlds/<dir>/latest.json               {snapshot, published_utc, validation summary}
    worlds/index.json                      every published county (rebuilt by --rebuild-index)

<id> is the UTC publish time plus the git commit of the code that built it, so any public
viewer can be traced to an exact snapshot, and the manifest's sha256 per file plus the
sources recorded in every layer's _meta.json make the build reproducible.
"""
from __future__ import annotations

import argparse, datetime, hashlib, json, mimetypes, os, pathlib, shutil, subprocess, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

SNAPSHOT_PARTS = ("layers", "layers_raw", "stage", "viewer", "viewer_data", "renders")
CT = {".json": "application/json", ".geojson": "application/geo+json", ".f32": "application/octet-stream",
      ".js": "text/javascript", ".mjs": "text/javascript", ".html": "text/html; charset=utf-8",
      ".css": "text/css", ".csv": "text/csv", ".md": "text/markdown; charset=utf-8",
      ".tif": "image/tiff", ".usda": "text/plain; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg"}
IMMUTABLE = "public, max-age=31536000, immutable"
SHORT = "public, max-age=300"


def client():
    import boto3
    acct = os.environ["R2_ACCOUNT_ID"]
    return boto3.client("s3", endpoint_url=f"https://{acct}.r2.cloudflarestorage.com",
                        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
                        region_name="auto")


def bucket():
    return os.environ["R2_BUCKET"]


def _ct(path: pathlib.Path) -> str:
    return CT.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def put_file(s3, path: pathlib.Path, key: str, cache: str):
    s3.upload_file(str(path), bucket(), key, ExtraArgs={"ContentType": _ct(path), "CacheControl": cache})


def put_json(s3, obj, key: str, cache=SHORT):
    s3.put_object(Bucket=bucket(), Key=key, Body=json.dumps(obj, indent=1).encode(),
                  ContentType="application/json", CacheControl=cache)


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "--short=7", "HEAD"], text=True).strip()
    except Exception:
        return "nogit"


def validation_summary(world_dir_name: str) -> dict:
    p = REPO / "validation" / f"{world_dir_name}_validation.json"
    if not p.exists():
        return {"status": "missing"}
    v = json.loads(p.read_text())
    checks = v if isinstance(v, list) else (v.get("checks") or v.get("results") or [])
    statuses = [c.get("status") for c in checks if isinstance(c, dict)]
    return {"checks": len(statuses), "pass": statuses.count("PASS"), "flag": statuses.count("FLAG"),
            "fail": statuses.count("FAIL")}


def publish(fips: str, s3) -> dict:
    from county_config import get
    from build_site import SITE_URL, brand_viewer_html, slim_viewer_data
    C = get(fips)
    world = C.world
    if not (world / "viewer" / "index.html").exists():
        raise SystemExit(f"{fips}: no built viewer in {world} — run tools/build_county.py first")
    now = datetime.datetime.now(datetime.timezone.utc)
    snap = f"{now:%Y%m%dT%H%M%SZ}-{git_sha()}"
    prefix = f"worlds/{C.dir_name}"

    # 1. immutable snapshot: every world file + validation report, with a manifest
    files = []
    for part in SNAPSHOT_PARTS:
        root = world / part
        if root.exists():
            files += [p for p in sorted(root.rglob("*")) if p.is_file() and not p.name.startswith(".")]
    vfiles = sorted((REPO / "validation").glob(f"{C.dir_name}_validation.*"))
    manifest = {"fips5": C.fips, "dir": C.dir_name, "snapshot": snap,
                "published_utc": now.isoformat(timespec="seconds"), "code_commit": git_sha(),
                "boundary_source": C.boundary_source, "files": [], "layer_sources": {}}
    for p in files + vfiles:
        rel = p.relative_to(world) if p.is_relative_to(world) else pathlib.Path("validation") / p.name
        put_file(s3, p, f"{prefix}/snapshots/{snap}/{rel.as_posix()}", IMMUTABLE)
        manifest["files"].append({"path": rel.as_posix(), "bytes": p.stat().st_size, "sha256": sha256(p)})
        if p.name == "_meta.json":
            try:
                manifest["layer_sources"][rel.parent.as_posix()] = json.loads(p.read_text())
            except ValueError:
                pass
    put_json(s3, manifest, f"{prefix}/snapshots/{snap}/manifest.json", IMMUTABLE)

    # 2. public viewer: branded HTML + slimmed data, replacing the previous "current"
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        shutil.copytree(world / "viewer", d / "viewer")
        shutil.copytree(world / "viewer_data", d / "viewer_data")
        idx = d / "viewer" / "index.html"
        idx.write_text(brand_viewer_html(idx.read_text(), home=SITE_URL + "/"))
        slim_viewer_data(d / "viewer_data")
        for p in sorted(d.rglob("*")):
            if p.is_file():
                put_file(s3, p, f"{prefix}/current/{p.relative_to(d).as_posix()}", SHORT)

    latest = {"fips5": C.fips, "dir": C.dir_name, "name": C.county_name, "state": C.st,
              "snapshot": snap, "published_utc": manifest["published_utc"],
              "viewer": f"{prefix}/current/viewer/", "validation": validation_summary(C.dir_name)}
    put_json(s3, latest, f"{prefix}/latest.json")
    nbytes = sum(f["bytes"] for f in manifest["files"])
    print(f"{C.dir_name}: snapshot {snap}, {len(manifest['files'])} files, {nbytes / 1e6:.1f} MB; "
          f"validation {latest['validation']}")
    return latest


def publish_log(s3, fips: str, path: str, run: str):
    """Build log for one county and run, public, so failures can be read without
    GitHub sign-in: logs/<run>/<fips5>.txt (D-032)."""
    p = pathlib.Path(path)
    if not p.exists():
        print(f"no log at {p}; nothing to publish")
        return
    key = f"logs/{run}/{fips}.txt"
    s3.upload_file(str(p), bucket(), key,
                   ExtraArgs={"ContentType": "text/plain; charset=utf-8", "CacheControl": SHORT})
    print(f"log: {key}")


def rebuild_index(s3):
    counties = []
    pag = s3.get_paginator("list_objects_v2")
    for page in pag.paginate(Bucket=bucket(), Prefix="worlds/", Delimiter="/"):
        for cp in page.get("CommonPrefixes", []):
            key = cp["Prefix"] + "latest.json"
            try:
                obj = s3.get_object(Bucket=bucket(), Key=key)
                counties.append(json.loads(obj["Body"].read()))
            except s3.exceptions.NoSuchKey:
                continue
    counties.sort(key=lambda c: c["fips5"])
    idx = {"generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "count": len(counties), "counties": counties}
    put_json(s3, idx, "worlds/index.json")
    print(f"worlds/index.json: {len(counties)} counties")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Publish county worlds to R2 (D-031)")
    ap.add_argument("fips", nargs="*")
    ap.add_argument("--rebuild-index", action="store_true")
    ap.add_argument("--log", help="publish this build log for the single fips given (needs --run)")
    ap.add_argument("--run", help="run id the log belongs to, e.g. the GitHub Actions run id")
    a = ap.parse_args(argv)
    if a.log:
        if len(a.fips) != 1 or not a.run:
            ap.error("--log needs exactly one fips5 and --run")
        publish_log(client(), a.fips[0], a.log, a.run)
        return
    if not a.fips and not a.rebuild_index:
        ap.error("give one or more fips5 codes, or --rebuild-index")
    s3 = client()
    for f in a.fips:
        publish(f, s3)
    if a.rebuild_index:
        rebuild_index(s3)


if __name__ == "__main__":
    main()
