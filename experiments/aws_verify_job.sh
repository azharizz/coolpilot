#!/usr/bin/env bash
# Graviton evaluation for the verifier work. Runs ON the instance from ~/coolpilot (after remote_setup.sh standard).
# Writes results/ ; agent arm needs ~/coolpilot/.env.agent (NEBIUS_*), otherwise it fails safe (alarms kept).
set -uo pipefail
cd ~/coolpilot; export COOLPILOT_DATA=~/coolpilot/data; PY=~/venv-standard/bin/python
[ -f .env.agent ] && { set -a; . ./.env.agent; set +a; }
step() { echo "== $(date -u +%H:%M) $*"; }

step "1. three verifier arms (unpaced, every frame)"
for pair in "oxford-camera-holdout tuning" "oxford-camera-holdout validation" "oxford-camera-holdout-fresh validation"; do
  set -- $pair
  $PY -m experiments.verify_eval --dataset $1 --split $2 --arms none rule agent --out results/verify-$1-$2.json > results/verify-$1-$2.txt 2>&1
  grep '^{' results/verify-$1-$2.txt | cut -c1-260
done

step "2. paced held-out benchmark on fresh seeds: verifier off vs rule (2 repetitions each)"
for mode in off rule; do
  $PY - "$mode" <<'PY'
import json, sys
from coolpilot.camera_dataset import catalog
from experiments.evaluation_runs import GOALS
d = next(c for c in catalog() if c["id"] == "oxford-camera-holdout-fresh")
req = {"workload": "camera_health", "repetitions": 2, "name": "fresh paced",
       "camera": {"dataset": d["id"], "dataset_sha256": d["sha256"], "goals": GOALS, "verifier": sys.argv[1]}}
open(f"results/paced-request-{sys.argv[1]}.json", "w").write(json.dumps(req))
PY
  $PY -m coolpilot.simulation.camera_benchmark --request results/paced-request-$mode.json --config results/default-config.json --split validation > results/paced-fresh-$mode.json 2> results/paced-fresh-$mode.err
  echo "paced $mode exit $?"
done

step "3. OpenCV 4.13 vs 5.0 on this host"
if [ ! -x ~/venv-4x/bin/python ]; then
  python3 -m venv ~/venv-4x
  grep -viE '^(opencv|numpy)' requirements.txt > /tmp/req-rest.txt
  ~/venv-4x/bin/pip install -q --disable-pip-version-check opencv-python-headless==4.13.0.92 numpy -r /tmp/req-rest.txt
fi
for v in 4x standard; do
  P=$HOME/venv-$v/bin/python
  $P -m experiments.dnn_timing --out results/dnn-$v.json
  rm -f results/profile-cmp-$v.json; $P -m experiments.opencv_profile --repeat 3 --out results/profile-cmp-$v.json > /dev/null
done
$PY -m experiments.opencv_profile --compare results/profile-cmp-4x.json results/profile-cmp-standard.json > results/profile-4x-vs-5x.txt 2>&1
tail -20 results/profile-4x-vs-5x.txt
step DONE
