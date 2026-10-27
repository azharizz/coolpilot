#!/usr/bin/env bash
# Same-host benchmark: licensed COOL vs the standard OpenCV 5.0.0 wheel, on ONE COOL (Graviton) instance.
# Run ON the instance from ~/coolpilot after the code and data/ are in place:
#     bash experiments/cool_benchmark.sh
# Writes results/cool/: identity, build info, tests, per-stage profiles (1 and all threads), NanoDet timing,
# and the profile comparison (which also checks that both builds give identical measurements and detections).
set -uo pipefail
cd "$HOME/coolpilot"; R=results/cool; mkdir -p "$R" results
step() { echo "== $(date -u +%H:%M:%S) $*"; }
NPROC=$(nproc)

step "0. instance and COOL identity"
TOKEN=$(curl -fsS -m 3 -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60" || true)
meta() { curl -fsS -m 3 -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/$1" || echo unknown; }
{ echo "instance_type=$(meta instance-type)"; echo "ami_id=$(meta ami-id)"; echo "region=$(meta placement/region)"; echo "nproc=$NPROC"
  echo "cpu=$(lscpu | sed -n 's/^Model name: *//p' | head -1)"; uname -a
  ls -d /opt/cool/* 2>/dev/null; find /opt/cool -maxdepth 2 -iname '*version*' -o -maxdepth 2 -iname '*release*' 2>/dev/null | head; } > "$R/identity.txt"
for f in $(find /opt/cool -maxdepth 2 -type f \( -iname '*version*' -o -iname '*release*' \) 2>/dev/null | head -5); do echo "--- $f"; head -20 "$f"; done >> "$R/identity.txt"
cat "$R/identity.txt"

step "1. COOL interpreter: setup, tests, profile (deploy/aws/remote_setup.sh cool)"
COOL_VENV="${COOL_VENV:-$(ls -d /opt/cool/venvs/python_3.1* 2>/dev/null | sort | tail -1)}"
export COOL_VENV
bash deploy/aws/remote_setup.sh cool > "$R/setup-cool.log" 2>&1; echo "cool setup exit $?"; grep -E "runtime identity|aarch64|distribution|tests exit" -A1 "$R/setup-cool.log" | head -8
step "2. standard OpenCV 5.0.0 wheel on the same host (remote_setup.sh standard)"
bash deploy/aws/remote_setup.sh standard > "$R/setup-standard.log" 2>&1; echo "standard setup exit $?"; grep -E "aarch64|distribution|tests exit" "$R/setup-standard.log" | head -4
cp results/build-cool.txt results/build-standard.txt results/tests-cool.txt results/tests-standard.txt results/profile-cool.json results/profile-standard.json "$R/" 2>/dev/null

cool() { PYTHONPATH="/opt/cool/$(basename "$COOL_VENV")/site-packages:$HOME/deps-cool" LD_LIBRARY_PATH="/opt/cool/cpp_sdk/lib:${LD_LIBRARY_PATH:-}" COOLPILOT_COOL_ROOT=/opt/cool "$COOL_VENV/bin/python" "$@"; }
standard() { "$HOME/venv-standard/bin/python" "$@"; }
wheel412() { "$HOME/venv-412/bin/python" "$@"; }   # same OpenCV version as COOL, standard wheel: isolates what COOL adds
step "2b. standard OpenCV 4.12 wheel (same version as COOL) on the same host"
if [ ! -x "$HOME/venv-412/bin/python" ]; then
  python3 -m venv "$HOME/venv-412"
  grep -viE '^(opencv|numpy)' requirements.txt > /tmp/req-rest.txt
  "$HOME/venv-412/bin/pip" install -q --disable-pip-version-check "opencv-python-headless==$(cool -c 'import cv2; print(cv2.__version__)').*" -r /tmp/req-rest.txt   # 4.12 wheels need numpy 2
fi
wheel412 -c "import cv2, numpy; print('wheel cv2', cv2.__version__, 'numpy', numpy.__version__)"
wheel412 -m unittest discover -s tests > "$R/tests-wheel412.txt" 2>&1; echo "wheel412 tests exit $? ($(tail -1 "$R/tests-wheel412.txt"))"
rm -f "$R/profile-wheel412.json"; wheel412 -m experiments.opencv_profile --flow --repeat 3 --out "$R/profile-wheel412.json" > /dev/null 2>&1; echo "wheel412 profile t1 exit $?"
THREADS=8; [ "$NPROC" -lt 8 ] && THREADS=$([ "$NPROC" -ge 4 ] && echo 4 || echo 2)

step "3. per-stage profile, $THREADS OpenCV threads, both builds"
for b in cool wheel412 standard; do rm -f "$R/profile-$b-t$THREADS.json"; $b -m experiments.opencv_profile --threads $THREADS --repeat 3 --out "$R/profile-$b-t$THREADS.json" > /dev/null 2>&1; echo "$b t$THREADS exit $?"; done
step "4. NanoDet (OpenCV 5 DNN, new engine), 1 and $THREADS threads, both builds"
for b in cool wheel412 standard; do for t in 1 $THREADS; do $b -m experiments.dnn_timing --threads $t --out "$R/dnn-$b-t$t.json" > /dev/null 2>&1; echo "$b dnn t$t exit $? $(cat "$R/dnn-$b-t$t.json" 2>/dev/null | head -c 200)"; done; done
step "5. comparisons: 4.12 wheel vs COOL 4.12 (what COOL adds), and standard 5.0.0 vs COOL (our shipped stack vs COOL)"
for t in 1 $THREADS; do sfx=$([ $t = 1 ] && echo "" || echo "-t$t")
  standard -m experiments.opencv_profile --compare "$R/profile-wheel412$sfx.json" "$R/profile-cool$sfx.json" > "$R/compare-wheel412-vs-cool-t$t.txt" 2>&1
  standard -m experiments.opencv_profile --compare "$R/profile-standard$sfx.json" "$R/profile-cool$sfx.json" > "$R/compare-standard5-vs-cool-t$t.txt" 2>&1
done
for f in "$R"/compare-*.txt; do echo "--- $f"; tail -18 "$f"; done
step done
echo COOL_BENCHMARK_DONE
