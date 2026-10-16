#!/usr/bin/env bash
# Builds build/function.zip for Lambda python3.12 on arm64 (Graviton). No Docker needed:
# dependencies are installed from aarch64 wheels only, so nothing is compiled for the wrong CPU.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/../../.." && pwd)"
OUT="$HERE/build"; rm -rf "$OUT"; mkdir -p "$OUT/pkg"
[ -f "$ROOT/web/dist/index.html" ] || { echo "Run 'npm run build' in web/ first." >&2; exit 1; }
python3 -m pip install --quiet --disable-pip-version-check --target "$OUT/pkg" \
  --platform manylinux2014_aarch64 --platform manylinux_2_17_aarch64 --platform manylinux_2_28_aarch64 \
  --implementation cp --python-version 3.12 --only-binary=:all: -r "$ROOT/requirements.txt"
mkdir -p "$OUT/pkg/web"
cp -R "$ROOT/coolpilot" "$OUT/pkg/coolpilot"; cp -R "$ROOT/web/dist" "$OUT/pkg/web/dist"
cp "$HERE/run.sh" "$HERE/fetch_data.py" "$OUT/pkg/"; chmod +x "$OUT/pkg/run.sh"
find "$OUT/pkg" \( -name __pycache__ -o -name tests -o -name '*.dist-info' -prune \) -type d -exec rm -rf {} + 2>/dev/null || true
find "$OUT/pkg" -name '*.pyc' -delete
(cd "$OUT/pkg" && zip -qr9 "$OUT/function.zip" .)
echo "unzipped: $(du -sm "$OUT/pkg" | cut -f1) MB (Lambda limit 250), zipped: $(du -sm "$OUT/function.zip" | cut -f1) MB"
