#!/usr/bin/env python3
"""Offline test of tools/publish_world.py against a mocked S3 bucket (D-031).

    pip install "moto[s3]"   # test-only dependency
    python3 tests/test_publish_world.py

Publishes two committed pilot worlds, rebuilds the index, and checks the bucket layout,
the branded viewer, cache headers and the manifest.
"""
import json, os, pathlib, sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
try:
    import boto3
    from moto import mock_aws
except ImportError:
    print("test_publish_world: skipped (pip install boto3 'moto[s3]')")
    sys.exit(0)

os.environ.update(R2_ACCOUNT_ID="test", R2_ACCESS_KEY_ID="test", R2_SECRET_ACCESS_KEY="test",
                  R2_BUCKET="ruralsim-test")
import publish_world as pw  # noqa: E402

with mock_aws():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="ruralsim-test")
    pw.client = lambda: s3
    pw.main(["31173", "20019", "--rebuild-index"])

    get = lambda k: s3.get_object(Bucket="ruralsim-test", Key=k)["Body"].read()
    keys = [o["Key"] for p in s3.get_paginator("list_objects_v2").paginate(Bucket="ruralsim-test")
            for o in p.get("Contents", [])]

    idx = json.loads(get("worlds/index.json"))
    assert idx["count"] == 2 and [c["fips5"] for c in idx["counties"]] == ["20019", "31173"], idx
    c = idx["counties"][1]
    assert c["viewer"] == "worlds/31173_thurston_ne/current/viewer/index.html"
    assert c["validation"]["checks"] > 0

    html = get("worlds/31173_thurston_ne/current/viewer/index.html").decode()
    assert 'href="https://www.ruralsim.io/"' in html and "osmcredit" in html
    assert "'../viewer_data/'" in html  # viewer reads its data from the sibling folder on R2

    snaps = {k.split("/snapshots/")[1].split("/")[0] for k in keys if "31173" in k and "/snapshots/" in k}
    assert len(snaps) == 1
    snap = snaps.pop()
    m = json.loads(get(f"worlds/31173_thurston_ne/snapshots/{snap}/manifest.json"))
    assert m["snapshot"] == snap and len(m["files"]) > 20
    assert all(len(f["sha256"]) == 64 for f in m["files"])
    assert any(f["path"].startswith("validation/") for f in m["files"])
    assert "layers_raw/osm" in m["layer_sources"]

    h = s3.head_object(Bucket="ruralsim-test", Key=f"worlds/31173_thurston_ne/snapshots/{snap}/manifest.json")
    assert "immutable" in h["CacheControl"]
    h = s3.head_object(Bucket="ruralsim-test", Key="worlds/31173_thurston_ne/current/viewer/index.html")
    assert h["CacheControl"] == pw.SHORT and h["ContentType"].startswith("text/html")

print("test_publish_world: all checks passed")
