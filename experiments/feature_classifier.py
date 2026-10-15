"""Session-held-out linear OpenCV SVM using only existing camera measurements."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

from coolpilot.runtime import environment
from coolpilot.camera_health import Monitor, analyze
from coolpilot.models import CameraThresholds

LABELS = ("normal", "blur", "underexposure", "glare", "obstruction", "blackout")


def features(measurements):
    values = []
    for region in measurements["regions"]:
        values.extend((region["mean"] / 255, np.log1p(region["detail"]), region["clipped"]))
    values.append(measurements["black_fraction"])
    result = np.asarray(values, dtype=np.float32)
    if result.shape != (49,) or not np.isfinite(result).all():
        raise ValueError("Expected 16 finite region measurements and black fraction.")
    return result


def fit_evaluate(x, labels, sessions, splits):
    x = np.asarray(x, dtype=np.float32)
    labels, sessions, splits = np.asarray(labels), np.asarray(sessions), np.asarray(splits)
    if (x.ndim != 2 or x.shape[1] != 49 or not np.isfinite(x).all()
            or any(a.shape != (len(x),) for a in (labels, sessions, splits))
            or not set(labels) <= set(LABELS) or not set(splits) <= {"train", "test"}
            or any(not str(s).strip() for s in sessions)):
        raise ValueError("Invalid features, labels, session IDs or train/test splits.")
    train, test = splits == "train", splits == "test"
    if not train.any() or not test.any() or set(sessions[train]) & set(sessions[test]):
        raise ValueError("Train and test need nonempty, disjoint capture sessions.")
    if len(set(labels[train])) < 2 or not set(labels[test]) <= set(labels[train]):
        raise ValueError("Train needs at least two classes and all held-out classes.")
    mean, scale = x[train].mean(axis=0), x[train].std(axis=0)
    scale[scale == 0] = 1
    normalized = (x - mean) / scale
    if not np.isfinite(normalized).all():
        raise ValueError("Feature normalization overflowed.")
    y = np.array([LABELS.index(label) for label in labels], dtype=np.int32)
    svm = cv2.ml.SVM_create()
    svm.setType(cv2.ml.SVM_C_SVC)
    svm.setKernel(cv2.ml.SVM_LINEAR)
    svm.setC(1.0)  # Fixed before held-out evaluation; no test-set tuning.
    if not svm.train(normalized[train], cv2.ml.ROW_SAMPLE, y[train]):
        raise ValueError("SVM training failed.")
    began = perf_counter()
    _, raw = svm.predict(normalized[test])
    inference_ms = (perf_counter() - began) * 1000
    predicted = raw.ravel().astype(int)
    confusion = np.zeros((len(LABELS), len(LABELS)), dtype=int)
    np.add.at(confusion, (y[test], predicted), 1)
    counts = confusion.sum(axis=1)
    recalls = [float(confusion[i, i] / n) if n else None for i, n in enumerate(counts)]
    report = {"labels": LABELS, "confusion_true_rows_predicted_columns": confusion.tolist(),
              "accuracy": float(np.mean(predicted == y[test])),
              "balanced_accuracy_observed_classes": float(np.mean([r for r in recalls if r is not None])),
              "recall": dict(zip(LABELS, recalls)), "test_predictions": [LABELS[i] for i in predicted],
              "train_samples": int(train.sum()), "test_samples": int(test.sum()),
              "train_sessions": sorted(set(sessions[train])), "test_sessions": sorted(set(sessions[test])),
              "batch_inference_ms": inference_ms}
    return svm, mean, scale, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="CSV: path,session,split,label; paths relative to CSV")
    parser.add_argument("output", type=Path, help="New directory; never overwrite prior results")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output directory must not exist")
    with args.manifest.open(newline="") as file:
        rows = list(csv.DictReader(file))
    if not rows or any(not {"path", "session", "split", "label"} <= row.keys() for row in rows):
        parser.error("manifest must contain path,session,split,label")
    x, baseline, hashes = [], [], {}
    extraction_ms = 0.0
    cv2.setNumThreads(1)
    for row in rows:
        path = (args.manifest.parent / row["path"]).resolve()
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest in hashes:
            raise ValueError("Duplicate image bytes in manifest; remove duplicates before evaluation.")
        hashes[digest] = row["split"]
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError(f"Cannot decode image: {path}")
        started = perf_counter()
        measured = analyze(image, 320)
        x.append(features(measured))
        extraction_ms += (perf_counter() - started) * 1000
        conditions, _ = Monitor(CameraThresholds()).appearance(measured, 0)
        baseline.append(sorted(conditions))
        row["sha256"] = digest
    svm, mean, scale, report = fit_evaluate(
        x, [r["label"] for r in rows], [r["session"] for r in rows], [r["split"] for r in rows])
    test_rows = [(r, b) for r, b in zip(rows, baseline) if r["split"] == "test"]
    report.update({"environment": environment(), "feature_schema": "row-major 16*(mean/255,log1p(detail),clipped)+black_fraction",
                   "feature_extraction_ms_all_samples": extraction_ms,
                   "baseline_exact_label_set_accuracy": sum(b == ([] if r["label"] == "normal" else [r["label"]])
                                                            for r, b in test_rows) / len(test_rows),
                   "samples": rows, "baseline_conditions": baseline,
                   "warning": "Single-frame mutually exclusive labels only. Baseline has no temporal reference; cannot assess freeze or temporal contamination. Session IDs are user assertions; no promotion or safety claim."})
    args.output.mkdir(parents=True, exist_ok=False)
    svm.save(str(args.output / "svm.xml"))
    np.savez(args.output / "normalization.npz", mean=mean, scale=scale)
    (args.output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: report[k] for k in ("accuracy", "balanced_accuracy_observed_classes", "train_samples", "test_samples")}))


if __name__ == "__main__":
    main()
