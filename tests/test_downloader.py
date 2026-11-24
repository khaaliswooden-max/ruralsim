"""Downloader: retries with backoff, 404 is the only "missing", data host in the record (D-116)."""
import http.server
import threading
import urllib.error

import pytest

pytest.importorskip("pandapower", reason="engine environment (tools/engines/ai_infra/requirements.txt)")

from tools.engines.ai_infra import data  # noqa: E402

BODY = b"x" * 5000
STATE = {}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        n = STATE[self.path] = STATE.get(self.path, 0) + 1
        mode = self.path.strip("/").split("/")[0]
        if mode == "missing":
            self.send_response(404); self.end_headers(); return
        if mode == "forbidden":
            self.send_response(403); self.end_headers(); return
        if mode == "busy" or (mode == "busy2" and n <= 2):
            self.send_response(503); self.end_headers(); return
        if mode == "drop" and n == 1:
            self.connection.close(); return                      # dropped before any reply
        if mode == "short" and n == 1:                           # truncated body
            self.send_response(200); self.send_header("Content-Length", str(len(BODY))); self.end_headers()
            self.wfile.write(BODY[:100]); return
        self.send_response(200); self.send_header("Content-Length", str(len(BODY))); self.end_headers()
        self.wfile.write(BODY)


@pytest.fixture(scope="module")
def server():
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(data, "BACKOFF_S", 0.01)
    STATE.clear()
    data.DOWNLOADS.clear()


@pytest.mark.parametrize("mode", ["drop", "short", "busy2"])
def test_dropped_truncated_or_busy_downloads_are_retried(server, tmp_path, mode):
    p = data._get(f"{server}/{mode}/f.bin", tmp_path / "f.bin")
    assert p.read_bytes() == BODY
    assert data.DOWNLOADS[-1]["tries"] in (2, 3) and data.DOWNLOADS[-1]["outcome"] == "ok"


def test_three_tries_then_download_failed_never_missing(server, tmp_path):
    with pytest.raises(data.DownloadFailed):
        data._get(f"{server}/busy/f.bin", tmp_path / "f.bin")
    assert STATE["/busy/f.bin"] == 3 and not (tmp_path / "f.bin").exists()


def test_sha_mismatch_is_retried_then_fails(server, tmp_path):
    with pytest.raises(data.DownloadFailed, match="sha256"):
        data._get(f"{server}/ok/f.bin", tmp_path / "f.bin", sha256="0" * 64)
    assert STATE["/ok/f.bin"] == 3


def test_404_is_missing_at_once_and_other_4xx_raise(server, tmp_path, monkeypatch):
    with pytest.raises(urllib.error.HTTPError) as e:
        data._get(f"{server}/missing/f.bin", tmp_path / "f.bin")
    assert data.is_missing(e.value) and STATE["/missing/f.bin"] == 1
    with pytest.raises(urllib.error.HTTPError) as e:
        data._get(f"{server}/forbidden/f.bin", tmp_path / "f.bin")
    assert not data.is_missing(e.value) and STATE["/forbidden/f.bin"] == 1
    monkeypatch.setattr(data, "BASE", f"{server}/missing")
    monkeypatch.setattr(data, "CACHE", tmp_path)
    assert data.eia_available(2099) is False                      # real 404: absent
    monkeypatch.setattr(data, "BASE", f"{server}/busy")
    with pytest.raises(data.DownloadFailed):                      # network trouble is never "absent"
        data.eia_available(2098)


def test_download_report_names_the_host(server, tmp_path):
    data._get(f"{server}/drop/g.bin", tmp_path / "g.bin")
    data._get(f"{server}/drop/g.bin", tmp_path / "g.bin")             # second read: from the cache
    r = data.download_report()
    assert r["host"] == data.BASE and r["fetches"] == 1 and r["from_cache"] == 1 and r["retried"][0]["tries"] == 2
    assert r["missing_404"] == [] and r["failed"] == []


def test_tls_drop_mid_body_is_retried_and_never_missing(tmp_path, monkeypatch):
    import ssl
    calls = []

    def flaky(url, tmp):
        calls.append(1)
        if len(calls) == 1:
            raise ssl.SSLEOFError(8, "EOF occurred in violation of protocol")
        tmp.write_bytes(BODY)
    monkeypatch.setattr(data, "_fetch_once", flaky)
    assert data._get("https://h/f.bin", tmp_path / "f.bin").read_bytes() == BODY and len(calls) == 2

    def always(url, tmp):
        raise ssl.SSLEOFError(8, "EOF occurred in violation of protocol")
    monkeypatch.setattr(data, "_fetch_once", always)
    with pytest.raises(data.DownloadFailed) as e:
        data._get("https://h/g.bin", tmp_path / "g.bin")
    assert not data.is_missing(e.value)


def test_backoff_waits_2_then_4_seconds(tmp_path, monkeypatch):
    slept = []
    monkeypatch.setattr(data, "BACKOFF_S", 2.0)
    monkeypatch.setattr(data.time, "sleep", slept.append)

    def reset(url, tmp):
        raise ConnectionResetError(104, "Connection reset by peer")
    monkeypatch.setattr(data, "_fetch_once", reset)
    with pytest.raises(data.DownloadFailed):
        data._get("https://h/f.bin", tmp_path / "f.bin")
    assert slept == [2.0, 4.0]                                   # 3 tries, waits between them only


def test_cache_is_per_host():
    import importlib
    import os
    old = os.environ.get("RURALSIM_DATA_BASE")
    try:
        os.environ["RURALSIM_DATA_BASE"] = "https://a.example"
        a = importlib.reload(data).CACHE
        os.environ["RURALSIM_DATA_BASE"] = "https://b.example/sub"
        b = importlib.reload(data).CACHE
    finally:
        if old is None:
            os.environ.pop("RURALSIM_DATA_BASE", None)
        else:
            os.environ["RURALSIM_DATA_BASE"] = old
        importlib.reload(data)
    assert a != b and a.name == "a.example" and b.name == "b.example_sub"
