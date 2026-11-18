"""EIA-860 and EIA-861 national files used by fetch_grid.py, downloaded once (D-044).

Run #22 (NC/SC) lost Avery NC (37011) to one DNS failure on www.eia.gov ("Temporary
failure in name resolution"): every county job downloaded both zips itself, with no
retry. The plan job now prefetches them into $RURALSIM_CACHE/eia (shared with county
jobs through the Actions cache), and a county job that still has to download retries
with backoff and writes through a .part file so a cut-off download is never reused.
"""
from __future__ import annotations

import os, pathlib, time, urllib.request

CACHE = pathlib.Path(os.environ.get("RURALSIM_CACHE", "/tmp/ruralsim_cache")) / "eia"
UA = {"User-Agent": "RuralSim/1.0 (+https://www.ruralsim.io; county twin build)"}
EIA860 = "https://www.eia.gov/electricity/data/eia860/archive/xls/eia8602024.zip"
EIA861 = "https://www.eia.gov/electricity/data/eia861/archive/zip/f8612024.zip"


def ensure(url: str, tries: int = 6) -> pathlib.Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / url.rsplit("/", 1)[1]
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    part = dest.with_name(dest.name + ".part")
    for attempt in range(tries):
        try:
            print(f"downloading {url} ...", flush=True)
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=900) as r, \
                    open(part, "wb") as f:
                expected = int(r.headers.get("Content-Length") or 0)
                while True:
                    c = r.read(1 << 20)
                    if not c:
                        break
                    f.write(c)
            if expected and part.stat().st_size != expected:
                raise IOError(f"short download: {part.stat().st_size} of {expected} bytes")
            part.replace(dest)
            return dest
        except Exception as e:
            if attempt + 1 == tries:
                raise
            wait = 15 * 2 ** attempt
            print(f"  {url.rsplit('/', 1)[1]}: {e}; retry in {wait} s", flush=True)
            time.sleep(wait)


def prefetch() -> None:
    for u in (EIA860, EIA861):
        ensure(u)
