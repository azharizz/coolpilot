# Isolated camera-health experiments

These commands never run through the application, upload images, change configurations or promote a detector. Run from the repository root with the intended Python/OpenCV environment. No additional dependency is required for flow, regional persistence, fixed EMA, spatial weighting or the linear SVM. `cv2.quality` and external BRISQUE files are optional prerequisites, not silently installed dependencies.

## Video comparisons

```sh
python -m experiments.camera_health data/oxford_robotcar/videos/stereo_centre.mp4 --candidate flow
python -m experiments.camera_health data/oxford_robotcar/videos/stereo_centre.mp4 --candidate persistence
python -m experiments.camera_health data/oxford_robotcar/videos/stereo_centre.mp4 --candidate ema --tau-s 0.5
```

Repeat against the left/right files and independent sessions; the three supplied views are one session, not three independent validation sets. `--sample-every 2` tests lower observation frequency; `--max-frames 100` bounds a development run. Each NDJSON output contains runtime/build identity, input video SHA-256, parameters, source PTS, baseline conditions/active alarms, candidate measurements, baseline time and extra candidate time. Only a terminal `complete` record establishes successful decoding through the requested limit/EOF. Preserve the code revision and external input files alongside output. Decoding and stdout are excluded from measured compute times; the first frame is not warmed up. This is unpaced, single-stream offline analysis, not capacity, frame-delivery or real-time evidence.

| Candidate | Actual behavior | Limits |
| --- | --- | --- |
| `flow` | Shi-Tomasi corners, pyramidal LK, forward/backward consistency, median displacement/second; reports repetition after recent motion | Fewer than eight valid tracks means unknown motion. Static scenery and frozen imagery remain ambiguous; recent motion is context, not proof of freeze. |
| `persistence` | Same flow plus continuous regional detail loss at fixed image tiles while scene motion is measured | Resets on absent motion/texture/loss. This is a coarse 4×4 lens-coordinate heuristic, not geometric contamination segmentation. Scene boundaries and camera motion can fool it. |
| `ema` | Fixed elapsed-time EMA versus raw mean severity, time constant `--tau-s` | Severity is `max(detail < 60, clipped fraction)` per tile, not probability. May delay short faults. No learned adaptive controller. |
| `spatial` | Uniform versus explicitly weighted severity | Requires `--weights` pointing to a JSON array of 16 nonnegative row-major weights with positive sum. Choose weights from a defined perception task, never presumed center importance. |
| `brisque` | Real OpenCV BRISQUE computation at fixed 320×240 | Requires `cv2.quality`, `--brisque-model` and `--brisque-range`; fails explicitly otherwise. Scores are not fault diagnoses; resizing affects them. |

Flow uses 320×240 imagery and a default 5 px/s moving-scene threshold. `--motion-px-s` and `--persistence-s` are experimental calibration knobs. Both sampling and these thresholds must be frozen before held-out evaluation. The persistence duration also sets the recent-motion context horizon. Candidate signals are not replacement alarm policies: compare them against timestamped labels before selecting thresholds/persistence and measuring missed faults, false alarms and detection/recovery delay. Missing labels cannot produce an honest accuracy report.

## Feature classifier

Prepare a CSV with columns `path,session,split,label`. Paths are relative to the CSV. `split` must be `train` or `test`; all frames from a capture session, including edits/variants, must use one split. The supplied Oxford views and synthetic variants all belong to one session and cannot alone form a valid train/test experiment. Labels are mutually exclusive `normal`, `blur`, `underexposure`, `glare`, `obstruction`, `blackout`; this single-frame classifier does not predict freeze. Human labels and capture-session IDs are prerequisites, not inferred from filenames.

```sh
python -m experiments.feature_classifier labeled-images.csv data/feature-svm-run
```

The output directory must not exist. This trains an actual linear `cv2.ml.SVM` with fixed C=1, normalizes using training statistics only and evaluates untouched test sessions. It rejects overlapping sessions, duplicate image bytes, missing splits and test classes absent from training. Duplicate-byte rejection does not discover transformed copies or wrongly declared session IDs; audit those before running.

Features reuse the existing analyzer: 16 row-major triples of brightness/255, log(1+detail variance), clipping, followed by black fraction. Outputs are `svm.xml`, `normalization.npz` and `report.json` (sample hashes, confusion matrix, per-class recall, accuracy, observed-class balanced accuracy, baseline flags, runtime and timing). Baseline exact-label-set accuracy is a strict multi-flag comparison on independent frames without temporal history, not an equivalent temporal detector benchmark. Inference timing excludes feature extraction, which is reported separately. No tuning against the test set; create a session-disjoint development split before tuning. Loading requires the same feature order and saved normalization; NumPy loading must keep `allow_pickle=False`.

## OpenCV / COOL boundary

Both production and experiments import the same installed `cv2`; there is no remote COOL endpoint or second analyzer. Eligible OpenCV work can use a compatible licensed COOL build when that interpreter is selected. Python state logic, NumPy reductions, HTTP requests and remote model latency are not COOL acceleration targets. Exact operation support and output equivalence must be verified on that build; no automatic speedup is claimed for optical flow, SVM or BRISQUE.

```sh
python -c 'from coolpilot.runtime import environment; import json; print(json.dumps(environment(), indent=2))'
python -m unittest discover -s tests -v
```

### Same-host build comparison

`experiments.opencv_profile` runs the analyzer, alarm logic and optionally the flow candidate unpaced over the three Oxford views, once per interpreter, then compares the two profiles. It reports CPU per stage (decode, OpenCV analysis, Python alarms, flow) and fails (exit 1) unless every per-frame condition and alarm episode is identical.

```sh
python -m experiments.opencv_profile --flow --out standard.json
/path/to/cool/python -m experiments.opencv_profile --flow --out cool.json
python -m experiments.opencv_profile --compare standard.json cool.json
```

Run both on the same host with the same `--width` and `--threads`; video hashes must match. The first pass is a discarded warm-up. Totals are exact process CPU; small stage splits are approximate because decoder threads can charge a neighbouring stage. Analyzer tile statistics use `cv2.meanStdDev`, `cv2.mean` and `cv2.countNonZero`, so an accelerated build covers them; measured on Darwin/arm64 with OpenCV 4.13, this cut analysis CPU 1.5× versus the former NumPy reductions, with identical alarms.

The default Docker image installs ordinary `opencv-python-headless`, not licensed COOL. Do not install the default OpenCV wheel or contrib wheel over a vendor COOL environment. Use a separate environment for BRISQUE if the vendor build lacks `cv2.quality`. The existing runtime distribution label uses the `/opt/cool/` module path convention; it is not license verification. Retain actual module path, build hash, hardware and license provenance. Run matched workloads with fixed gates on the intended licensed hardware before asserting acceleration.

## Research-only candidates, not implemented models

- **Adaptive learned EMA / WoodScape SDSM:** no verified checkpoint/preprocessing package or license clearance is supplied. Fixed EMA is the runnable control; a learned controller is not invented or replaced by a fake model.
- **WoodScape / TiledSoilingNet:** no automatic download or production model integration. [Official WoodScape repository](https://github.com/valeoai/WoodScape) distinguishes code and dataset licenses; the dataset terms restrict commercial and vehicle-operation/assistance uses, including certain derived models. Obtain applicable permission, exact model assets and domain-representative held-out data before implementation. Forward road images are not the fisheye training domain.
- **Arbitrary task-region weighting:** intentionally absent; the spatial candidate requires supplied weights. No vehicle task has been specified.

## Exercised verification

35 Python tests passed, including elapsed-time decay, advice expiry, flow/static/textureless cases, fixed-coordinate loss reset, EMA rate invariance, invalid weights, train/test leakage rejection and normalization. Four candidate CLIs each processed a temporary 12-frame moving-texture video. The classifier CLI trained on eight synthetic images, evaluated four, and its saved SVM/normalization reproduced `[normal, blackout, normal, blackout]`. This only proves execution/serialization, not accuracy on road footage. Local `cv2.quality` was absent; the BRISQUE prerequisite failure was checked, but real BRISQUE scoring was not exercised. No supplied-video, paid-provider, licensed-COOL or end-to-end application integration was run for this revision.
