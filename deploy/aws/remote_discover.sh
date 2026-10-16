#!/usr/bin/env bash
# Runs ON a COOL instance. Reports where the vendor OpenCV lives and which interpreter imports it,
# so remote_setup.sh can be pointed at it (COOL_PYTHON) and runtime detection can be checked.
echo "== os"; head -2 /etc/os-release; uname -m
echo "== /opt"; ls -la /opt 2>&1 | head -20
echo "== cv2 locations"; find / -xdev \( -name cv2 -type d -o -name 'cv2*.so' -o -name 'libopencv_core*' \) 2>/dev/null | head -30
echo "== interpreters that import cv2"
for py in $(ls /usr/bin/python3* /usr/local/bin/python3* /opt/*/bin/python3* /opt/*/*/bin/python3* 2>/dev/null | grep -E 'python3(\.[0-9]+)?$' | sort -u); do
  out=$("$py" -c 'import sys, cv2, numpy; print(sys.version.split()[0], "cv2", cv2.__version__, cv2.__file__, "numpy", numpy.__version__)' 2>&1 | tail -1)
  echo "$py -> $out"
done
echo "== vendor markers in build info (first interpreter that imports cv2)"
for py in $(ls /usr/bin/python3* /usr/local/bin/python3* /opt/*/bin/python3* 2>/dev/null | grep -E 'python3(\.[0-9]+)?$' | sort -u); do
  "$py" -c 'import cv2; print(cv2.getBuildInformation())' 2>/dev/null | grep -i -E 'cool|kleidi|graviton|neoverse|version string|install path|license' | head -15 && break
done
echo "== vendor docs / files"; ls -la ~ | head -30; find / -xdev -maxdepth 3 -iname '*cool*' 2>/dev/null | head -15; cat /etc/motd 2>/dev/null | head -20
