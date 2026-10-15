"""Shared camera-data location and streamed file integrity checks."""

import hashlib
import os
from pathlib import Path

DATA = Path(os.environ.get("COOLPILOT_DATA", "data"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
