"""Identity of the interpreter and OpenCV used by camera-health measurements."""

import hashlib
import os
import platform
from pathlib import Path

import cv2


COOL_ROOT = os.environ.get("COOLPILOT_COOL_ROOT", "/opt/cool")


def distribution(system: str, machine: str, module_path: str) -> str:
    """COOL ships as Graviton AMIs that install OpenCV under /opt/cool (venvs and site-packages)."""
    root = COOL_ROOT.rstrip("/") + "/"
    return "COOL" if system == "Linux" and machine in ("aarch64", "arm64") and module_path.startswith(root) else "OpenCV"


def accelerators(build: str) -> list[str]:
    """Hardware-acceleration layers this cv2 build reports (evidence, not a speed claim)."""
    found = []
    for name, marker in (("KleidiCV", "kleidicv"), ("Carotene", "carotene"), ("ARMPL", "armpl"), ("NEON", "neon")):
        if marker in build.lower():
            found.append(name)
    return found


def environment() -> dict:
    build = cv2.getBuildInformation()
    source = hashlib.sha256()
    root = Path(__file__).parent
    for path in sorted(root.rglob("*.py")):
        source.update(path.relative_to(root).as_posix().encode())
        source.update(path.read_bytes())
    return {
        "runner_sha256": source.hexdigest(),
        "architecture": platform.machine(),
        "system": platform.system(),
        "cpu_count": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count(),
        "opencv_version": cv2.__version__,
        "opencv_path": cv2.__file__,
        "build_sha256": hashlib.sha256(build.encode()).hexdigest(),
        "opencv_build": build,
        # Vendor module location is a detection hint, not license or speedup verification.
        "distribution": distribution(platform.system(), platform.machine(), str(cv2.__file__)),
        "accelerators": accelerators(build),
        "hardware_note": "Measured on this host. Architecture alone does not establish Graviton performance.",
    }
