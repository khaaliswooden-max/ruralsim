#!/bin/bash
# Relaunch a county build whenever none is running, until it completes.
# Lives in the repo (not /tmp) so sandbox restarts don't lose it.
# Usage: supervise_build.sh <fips> <max_rounds>
FIPS=$1; MAX=${2:-40}
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG=/tmp/build_${FIPS}.log
for i in $(seq 1 $MAX); do
  if ! pgrep -f "build_county.py $FIPS" > /dev/null; then
    if grep -aq "county build complete" "$LOG" 2>/dev/null; then echo "complete"; exit 0; fi
    echo "[$(date +%H:%M)] round $i: launching build $FIPS"
    cd "$REPO" && nohup python3 tools/build_county.py $FIPS >> "$LOG" 2>&1 &
  fi
  sleep 420
done
echo "exhausted rounds"
