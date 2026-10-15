"""Original CTU data, downloaded once and identified by content hashes."""

import hashlib
import json
import os
import shutil
import urllib.request
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np

DATA = Path(os.environ.get("COOLPILOT_DATA", "data"))
SOURCE = "https://cmp.felk.cvut.cz/cmp/demos/Tracking/linTrack/data/"
DATASET = DATA / "mouse_pad"
ARCHIVE_HASHES = {
    "mouse_pad_img.zip": "901f4fb10e4e430bbc7bb966b6ff95e8925ea3e0db6b54a1c182769b23c18d22",
    "mouse_pad_gt.zip": "532e0091d649f26d2158261ce1b42e4775fc91bb73c3502d23ed9744b67dba7a",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare() -> dict:
    """Download only from the named publisher; never extract archive paths."""
    manifest_path = DATASET / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    downloads = DATA / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    DATASET.mkdir(parents=True, exist_ok=True)
    archives = {}
    for suffix in ("img", "gt"):
        name = f"mouse_pad_{suffix}.zip"
        path = downloads / name
        url = f"{SOURCE}mouse_pad/{name}"
        if not path.exists():
            temporary = path.with_suffix(".part")
            with (
                urllib.request.urlopen(url) as response,
                temporary.open("wb") as output,
            ):
                shutil.copyfileobj(response, output)
            temporary.replace(path)
        digest = sha256(path)
        if digest != ARCHIVE_HASHES[name]:
            raise ValueError(f"Publisher archive integrity check failed: {name}")
        archives[name] = {"url": url, "sha256": digest}
        destination = DATASET / suffix
        destination.mkdir(exist_ok=True)
        with ZipFile(path) as archive:
            for member in archive.infolist():
                filename = Path(member.filename).name
                if not member.is_dir() and filename.lower().endswith((".jpg", ".txt")):
                    with (
                        archive.open(member) as source,
                        (destination / filename).open("wb") as output,
                    ):
                        shutil.copyfileobj(source, output)
    images = sorted((DATASET / "img").glob("*.jpg"))
    if len(images) < 2000:
        raise ValueError(
            "The publisher dataset is incomplete: need at least 2000 frames."
        )
    fingerprint = hashlib.sha256()
    for path in images:
        annotation = DATASET / "gt" / (path.stem + ".txt")
        coordinates = np.loadtxt(annotation)
        if coordinates.shape != (2, 4) or not np.isfinite(coordinates).all():
            raise ValueError(f"Invalid four-corner annotation: {annotation.name}")
        fingerprint.update(path.name.encode())
        fingerprint.update(bytes.fromhex(sha256(path)))
        fingerprint.update(annotation.read_bytes())
    frame = cv2.imread(str(images[0]))
    if frame is None:
        raise ValueError("The first dataset frame could not be decoded.")
    manifest = {
        "id": "ctu-mouse-pad",
        "name": "CTU · Mouse pad",
        "source": SOURCE + "index.html",
        "citation": "Zimmermann, Matas and Svoboda. Tracking by an Optimal Sequence of Linear Predictors. TPAMI 31(4), 2009.",
        "fps": 100,
        "frame_count": len(images),
        "width": frame.shape[1],
        "height": frame.shape[0],
        "sha256": fingerprint.hexdigest(),
        "archives": archives,
        "annotation": "Manually annotated corners; MATLAB row/column converted to zero-based x/y.",
        "splits": {
            "tuning": {"start": 0, "max_frames": 1000},
            "validation": {"start": len(images) // 2, "max_frames": 1000},
        },
    }
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2))
    temporary.replace(manifest_path)
    return manifest


def manifest() -> dict | None:
    path = DATASET / "manifest.json"
    return json.loads(path.read_text()) if path.exists() else None


def clip(split: str, count: int) -> tuple[list[str], np.ndarray]:
    info = manifest()
    if info is None:
        raise ValueError("Prepare the dataset before starting a benchmark.")
    start = info["splits"][split]["start"]
    paths = sorted((DATASET / "img").glob("*.jpg"))[start : start + count]
    if len(paths) != count:
        raise ValueError("Requested clip exceeds the available dataset.")
    truth = np.array(
        [np.loadtxt(DATASET / "gt" / (p.stem + ".txt"))[[1, 0]].T - 1 for p in paths],
        dtype=np.float32,
    )
    return [str(p) for p in paths], truth


if __name__ == "__main__":
    print(json.dumps(prepare(), indent=2))
