#!/usr/bin/env bash
# Runs ON the instance from ~/coolpilot. Usage: remote_setup.sh LABEL   (LABEL = standard | cool)
# COOL_PYTHON=/path/to/vendor/python makes the venv inherit that interpreter's own cv2/numpy;
# the standard opencv and numpy wheels are then NOT installed, so they cannot shadow COOL.
set -euo pipefail
cd "$HOME/coolpilot"
LABEL="${1:-standard}"
VENV="$HOME/venv-$LABEL"
if [ -n "${COOL_PYTHON:-}" ]; then
  PY="$COOL_PYTHON"; FLAGS=(--system-site-packages)
  grep -viE '^(opencv|numpy)' requirements.txt > "$HOME/requirements-$LABEL.txt"
else
  sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip >/dev/null
  PY=python3; FLAGS=(); cp requirements.txt "$HOME/requirements-$LABEL.txt"
fi
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), sys.version'
[ -d "$VENV" ] || "$PY" -m venv "${FLAGS[@]}" "$VENV"
"$VENV/bin/pip" install -q --disable-pip-version-check -r "$HOME/requirements-$LABEL.txt"

echo "== runtime identity"
"$VENV/bin/python" -c 'import cv2, numpy, platform, sys; print(platform.machine(), sys.version.split()[0], "numpy", numpy.__version__, "cv2", cv2.__version__, cv2.__file__)'
"$VENV/bin/python" -c 'import cv2; print(cv2.getBuildInformation())' > "results/build-$LABEL.txt"

echo "== tests"
set +e
"$VENV/bin/python" -m unittest discover -s tests > "results/tests-$LABEL.txt" 2>&1; TESTS=$?
set -e
tail -4 "results/tests-$LABEL.txt"; echo "tests exit code: $TESTS (full log: results/tests-$LABEL.txt)"

echo "== profile ($LABEL)"
"$VENV/bin/python" -m experiments.opencv_profile --flow --repeat 3 --out "results/profile-$LABEL.json"

echo "== service"
sudo tee /etc/systemd/system/coolpilot.service >/dev/null <<UNIT
[Unit]
Description=COOLPilot ($LABEL OpenCV)
After=network.target
[Service]
User=$USER
WorkingDirectory=$HOME/coolpilot
Environment=COOLPILOT_DATA=$HOME/coolpilot/data
ExecStart=$VENV/bin/uvicorn coolpilot.api:app --host 127.0.0.1 --port 8769 --workers 1 --no-access-log
Restart=on-failure
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable coolpilot >/dev/null 2>&1
sudo systemctl restart coolpilot
for _ in $(seq 1 30); do curl -fsS -m 3 http://127.0.0.1:8769/api/health >/dev/null 2>&1 && break; sleep 2; done
curl -fsS http://127.0.0.1:8769/api/health && echo
curl -fsS http://127.0.0.1:8769/api/system | "$VENV/bin/python" -c 'import json,sys; d=json.load(sys.stdin); print({k: d["runtime"][k] for k in ("distribution","opencv_version","architecture","system","cpu_count","opencv_path")}, "cool:", d["cool"]["available"])'
