#!/bin/bash
# Render verification captures for one county via headless chromium (xvfb + swiftshader).
# Usage: tools/render_county.sh <fips> [cam=x,z,h for a second close-up]
# Requires: repo-root http server on :8931 (python3 -m http.server 8931 from ruralsim/).
set -u
FIPS=${1:?fips required}
CAM=${2:-}
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DIR=$(ls -d "$REPO"/worlds/${FIPS}_* | head -1)
NAME=$(basename "$DIR")
BASE="http://localhost:8931/worlds/${NAME}/viewer/index.html"
OUT="$DIR/renders"; mkdir -p "$OUT"
shot() { # url_suffix out_name
  rm -rf /tmp/ccap_$2
  xvfb-run -a -s "-screen 0 1600x1000x24" "${CHROMIUM:-chromium}" --no-sandbox --headless=new \
    --enable-unsafe-swiftshader --disk-cache-dir=/tmp/ccap_$2 \
    --screenshot="$OUT/$2.png" --window-size=1600,1000 --virtual-time-budget=90000 \
    "$BASE?capture=1&$1" 2>/dev/null
  echo "$2.png: $(stat -c%s "$OUT/$2.png" 2>/dev/null) bytes"
}
shot "t=$(date +%s)" county_overview
if [ -n "$CAM" ]; then shot "cam=$CAM" town_closeup; fi
