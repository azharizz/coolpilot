#!/usr/bin/env bash
# Runs ON the instance from ~/coolpilot. Usage: remote_setup.sh LABEL   (LABEL = standard | cool)
#
# standard: a venv with the pinned opencv-python-headless 5.0.0 wheel.
# cool:     the vendor's own interpreter (COOL AMI: /opt/cool/venvs/python_3.12) so the vendor cv2 and
#           numpy are used. Our other dependencies go to a separate --target directory placed on
#           PYTHONPATH; the standard opencv and numpy wheels are never installed, so they cannot shadow COOL.
set -euo pipefail
cd "$HOME/coolpilot"
LABEL="${1:-standard}"
COOL_ROOT="${COOLPILOT_COOL_ROOT:-/opt/cool}"
COOL_VENV="${COOL_VENV:-$COOL_ROOT/venvs/python_3.12}"
mkdir -p results

if [ "$LABEL" = cool ]; then
  [ -x "$COOL_VENV/bin/python" ] || { echo "No COOL interpreter at $COOL_VENV (is this the COOL AMI?)" >&2; exit 1; }
  PY="$COOL_VENV/bin/python"; DEPS="$HOME/deps-cool"
  grep -viE '^(opencv|numpy)' requirements.txt > "$HOME/requirements-cool.txt"
  "$PY" -m pip install -q --disable-pip-version-check --upgrade --target "$DEPS" -r "$HOME/requirements-cool.txt"
  # The vendor cv2 and numpy live in $COOL_ROOT/python_3.x/site-packages, not in the venv itself (measured on the AMI).
  SITE="$COOL_ROOT/$(basename "$COOL_VENV")/site-packages"
  export PYTHONPATH="$SITE:$DEPS" LD_LIBRARY_PATH="$COOL_ROOT/cpp_sdk/lib:${LD_LIBRARY_PATH:-}" COOLPILOT_COOL_ROOT="$COOL_ROOT"
  ENVLINES="Environment=PYTHONPATH=$SITE:$DEPS
Environment=LD_LIBRARY_PATH=$COOL_ROOT/cpp_sdk/lib
Environment=COOLPILOT_COOL_ROOT=$COOL_ROOT"
else
  sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip >/dev/null
  VENV="$HOME/venv-standard"
  [ -d "$VENV" ] || python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --disable-pip-version-check -r requirements.txt
  PY="$VENV/bin/python"; ENVLINES=""
fi
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), sys.version'

echo "== runtime identity"
"$PY" -c 'import cv2, numpy, platform, sys; print(platform.machine(), sys.version.split()[0], "numpy", numpy.__version__, "cv2", cv2.__version__, cv2.__file__)'
"$PY" -c 'import cv2; print(cv2.getBuildInformation())' > "results/build-$LABEL.txt"
"$PY" -c 'from coolpilot.runtime import environment as e; d = e(); print("distribution:", d["distribution"], "accelerators:", d["accelerators"])'

echo "== tests"
set +e
"$PY" -m unittest discover -s tests > "results/tests-$LABEL.txt" 2>&1; TESTS=$?
set -e
tail -4 "results/tests-$LABEL.txt"; echo "tests exit code: $TESTS (full log: results/tests-$LABEL.txt)"

echo "== profile ($LABEL)"
rm -f "results/profile-$LABEL.json"
"$PY" -m experiments.opencv_profile --flow --repeat 3 --out "results/profile-$LABEL.json"

echo "== service"
sudo tee /etc/systemd/system/coolpilot.service >/dev/null <<UNIT
[Unit]
Description=COOLPilot ($LABEL OpenCV)
After=network.target
[Service]
User=$USER
WorkingDirectory=$HOME/coolpilot
Environment=COOLPILOT_DATA=$HOME/coolpilot/data
# Optional agent keys (NEBIUS_*), copied separately with mode 600; never synced with the code.
EnvironmentFile=-$HOME/coolpilot/.env.agent
$ENVLINES
ExecStart=$PY -m uvicorn coolpilot.api:app --host 127.0.0.1 --port 8769 --workers 1 --no-access-log
Restart=on-failure
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable coolpilot >/dev/null 2>&1
sudo systemctl restart coolpilot
for _ in $(seq 1 30); do curl -fsS -m 3 http://127.0.0.1:8769/api/health >/dev/null 2>&1 && break; sleep 2; done
curl -fsS http://127.0.0.1:8769/api/health && echo
curl -fsS http://127.0.0.1:8769/api/system | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print({k: d["runtime"].get(k) for k in ("distribution","opencv_version","architecture","system","cpu_count","opencv_path","accelerators")}, "cool:", d["cool"]["available"])'
