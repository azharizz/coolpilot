#!/usr/bin/env bash
# Measured capacity on ONE instance: N camera streams at once (1 OpenCV thread each, production pipeline,
# no optional flow candidate, unpaced), per build. Each stream runs experiments.opencv_profile on the three
# Oxford stereo clips. Real-time cameras = sum of per-stream frames/s / source fps.
#     bash experiments/cool_capacity.sh BUILD...      (BUILD = cool | standard)
set -uo pipefail
cd "$HOME/coolpilot"; R=results/capacity; mkdir -p "$R"; N=$(nproc)
cool() { PYTHONPATH="/opt/cool/python_3.12/site-packages:$HOME/deps-cool" LD_LIBRARY_PATH="/opt/cool/cpp_sdk/lib:${LD_LIBRARY_PATH:-}" COOLPILOT_COOL_ROOT=/opt/cool /opt/cool/venvs/python_3.12/bin/python "$@"; }
standard() { "$HOME/venv-standard/bin/python" "$@"; }
for b in "$@"; do
  rm -f "$R"/cap-$b-*.json
  read -r busy0 idle0 < <(awk '/^cpu /{print $2+$3+$4+$7+$8, $5+$6}' /proc/stat)
  for i in $(seq 1 "$N"); do $b -m experiments.opencv_profile --threads 1 --repeat 1 --out "$R/cap-$b-$i.json" > /dev/null 2>&1 & done; wait
  read -r busy1 idle1 < <(awk '/^cpu /{print $2+$3+$4+$7+$8, $5+$6}' /proc/stat)
  $b - "$b" "$N" "$busy0" "$idle0" "$busy1" "$idle1" <<'PY' | tee "$R/summary-$b.json"
import glob, json, sys
b, n = sys.argv[1], int(sys.argv[2]); busy0, idle0, busy1, idle1 = map(float, sys.argv[3:7])
runs = [json.load(open(f)) for f in sorted(glob.glob(f"results/capacity/cap-{b}-*.json"))]
env = runs[0]["environment"] if runs else {}
fps = [sum(v["frames"] for v in r["videos"].values()) / sum(v["wall_s"] for v in r["videos"].values()) for r in runs]
p95 = max(v["analysis_ms_p95"] for r in runs for v in r["videos"].values())
total = sum(fps); source = 271 / 19.0
print(json.dumps({"build": b, "opencv": env.get("opencv_version"), "distribution": env.get("distribution"), "machine": env.get("architecture"),
                  "streams": n, "completed": len(runs), "frames_per_s_total": round(total, 1), "frames_per_s_per_stream": round(total / max(len(runs), 1), 1),
                  "analysis_p95_ms": round(p95, 2), "cpu_utilisation": round((busy1 - busy0) / max(busy1 - busy0 + idle1 - idle0, 1), 3),
                  "source_fps": round(source, 2), "realtime_cameras": int(total / source)}))
PY
done
echo CAPACITY_DONE
