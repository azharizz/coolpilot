# Evaluation

What was measured, on what, and what still fails. Every number here comes from a file in this repository or from a run stored by the app. Last updated 2026-10-24. Synthetic faults on one recorded drive are **not** evidence of road safety.

## Data

- **Tuning:** the Oxford RobotCar sample's stereo centre camera, a clean reference plus six synthetic faults at fixed 4–10 s (blur, underexposure, glare, obstruction, blackout, freeze). 7 clips, about 19 s each.
- **Validation (held out):** the same drive's stereo left, stereo right and mono rear cameras, each with a clean reference and the six faults at **randomized** onset, duration (2–6 s), strength (0.7–1.3×) and position. 21 clips, never used for calibration.
- Camera-held-out within one drive: different sensors, viewpoints and Bayer patterns, but the same weather, route and time. It is not an independent drive.

Reproduce: see "Held-out cameras" in the [README](../README.md).

## Why the original detector failed

Run #63 (before this work) failed 15 of 53 gate checks, with 1,332 false alarms per hour. The causes, measured on the tuning clips, were all absolute thresholds that ignored what normal looks like for a given camera:

- **Glare:** sky tiles are 58–96% clipped in clean footage, so "any tile ≥ 35% clipped" fired constantly.
- **Underexposure:** the injected fault only lowers mean brightness to about 50, never below the fixed limit of 35.
- **Blur:** median detail fell to about 9% of normal, but only 65% of tiles crossed the fixed limit (75% required).
- **Obstruction:** the translucent smudge lowers its tiles' detail to 0.45–0.85 of normal, never below the fixed 0.25 rule.

## What changed

The detector now compares each camera with **its own recent normal**: per-tile brightness, clipped fraction and detail references, learned only while the view looks healthy. The rules:

- glare = a rise in clipping on several tiles
- underexposure = brightness below a fraction of the reference
- blur = median detail ratio
- obstruction = the same tiles staying low while the rest of the view keeps its detail

Absolute rules remain for a camera that starts broken (blackout, very dark, very soft). One cause suppresses the symptoms it explains: blackout hides everything else, and darkness hides blur. Hysteresis keeps a fading fault from being declared recovered early.

Thresholds were calibrated by `experiments/calibrate.py` on the tuning clips only, then frozen as the `CameraThresholds` defaults. The sweep report is in `docs/evidence/calibration/sweep-tuning.json`.

## Detector results (unpaced, every frame analysed once)

Measured on a Mac (OpenCV 4.13), comparing the original code (git HEAD before this work) with the calibrated defaults. Pass means the exact fault type was detected within 2 s of onset and cleared within 2 s of the labelled end, with no early clear.

| | Tuning (centre), before | Tuning, after | **Held-out (left, right, rear), before** | **Held-out, after** |
|---|---|---|---|---|
| Failed fault checks | 4 / 6 | 0 / 6 | 12 / 18 | **5 / 18** |
| False alarms per hour of normal video | 1,324 | 37 | 1,099 | **283** |
| blur | fail | pass | 0 / 3 | **3 / 3** |
| underexposure | fail | pass | 0 / 3 | **3 / 3** |
| blackout | pass | pass | 3 / 3 | **3 / 3** |
| freeze | pass | pass | 3 / 3 | **3 / 3** |
| glare | fail | pass | 0 / 3 | **1 / 3** |
| obstruction | fail | pass\* | 0 / 3 | **0 / 3** |

Evidence: `docs/evidence/calibration/{tuning_old,tuning_new,holdout_old,holdout_defaults}.json`.

### What failed after calibration, before the verifier (historical; see the current list below)

- **Obstruction is not solved.** All 26 remaining held-out false alarms are obstruction, and no held-out obstruction was detected. \*Its tuning "pass" is a coincidence: the flagged tile is sky (tile 1), which the clean reference clip flags at the same moment. Measured on the tuning clips, the translucent smudge lowers its tiles' detail to only 0.45–0.85 of normal, while ordinary scene change moves a tile's detail 10–20×. We also tried frame-to-frame change per cell (4×4 and 8×8, normalised by the frame median): the obstructed and clean clips gave practically identical statistics. Cheap per-tile statistics cannot separate this smudge from a moving scene in this footage. A credible obstruction detector likely needs longer temporal integration or a learned model, validated on real lens contamination.
- **Glare** generalises to one of three held-out cameras: right clears late, and rear is missed (its randomized glare is weaker, 0.82×, on a different sky).
- **37 false alarms per hour on tuning** still fails the strict 0 per hour gate the UI proposes. We kept that gate rather than loosening it.

## Measured on AWS Graviton (OpenCV 5.0.0)

All on EC2 t4g.small (Graviton2, 2 vCPU, unlimited credits, so no throttling) with the standard `opencv-python-headless` 5.0.0 wheel. The full before/after record, with every number tied to an evidence file, is in [BEFORE_AFTER.md](BEFORE_AFTER.md). Summary:

| Measurement | Result |
|---|---|
| Paced held-out (21 clips × 3 repetitions), detector alone | blackout, blur, freeze, underexposure 9/9; glare 3/9; obstruction 0/9; 285 false alarms/h; 0.25 CPU-s per camera-s; max age 0.23 s. Same outcome as the unpaced Mac run |
| Tuning search: baseline, random (8), agent runs 1–3 | No configuration passes the 0 false alarms/h gate; the agent did not beat random. The last false alarm is a scene change, not a threshold |
| **Second-stage verifier**, fresh held-out (42 never-inspected clips), paced, 2 repetitions | false alarms **233.8/h → 0.0/h** with the rule verifier; real-fault results identical; +17% CPU; max age 0.25 s |
| Verifier arms, fresh held-out, unpaced | none 232/h · rule **0/h** · LLM agent 99.6/h (25 dismissed, 18 escalated to a human, median 2.9 s) |
| OpenCV 5 new DNN engine vs 4.13 classic, NanoDet, same host | 71.9 ms vs 96.0 ms (1.34×), identical detections |
| OpenCV 4.13 vs 5.0, our classic analysis, same host | 0.98× (no gain); decode 1.11×; alarms identical |
| **DRIVE-C** (independent, no tuning) | day scenes 78/210 (37%) detected at onset; night scenes false-alarm on darkness (3/3 clean); defocus 0/50 |

## What the verifier does and does not show

- It removes the dominant false-alarm cause on this drive (open sky replacing a detailed tile) **without losing any real detection**, in paced real time on Graviton.
- 41 of 43 fresh suspicions are that same cause. It is one failure mode fixed reliably, not proven general robustness. On DRIVE-C, one clean day scene still raised an obstruction the verifier did not dismiss.
- The LLM agent arm is worse than the fixed rule: more kept alarms (all of them escalations to a human), about 23× slower, and not reproducible across runs even at temperature 0. The fixed rule is the default; the agent's value is cited reasons and human escalation.

## What still fails, plainly (current)

- **Lens obstruction (translucent smudge):** 0 of 6 on fresh held-out and 0–1 of 10 on DRIVE-C. The trigger does not fire on real smudges, so verification cannot help. Cheap per-tile statistics cannot separate this smudge from scene change; a learned model on real soiled-lens data would be the next step.
- **Glare:** 1 of 6 on fresh held-out, about half on DRIVE-C daytime.
- **Night:** the darkness fallback fires on normal night driving (DRIVE-C, 3 of 3 night scenes). Night is out of scope today.
- **Partial defocus:** DRIVE-C's depth-dependent defocus is missed at every severity; "blur" means whole-frame blur.
- **Mild under-exposure and low light:** caught only at the strongest DRIVE-C severities.
- **Strict gate:** the 0 false alarms/h gate is met on fresh held-out only with the verifier, and no candidate passes every tuning gate, because the tuning "obstruction pass" was itself a sky coincidence.
- **Evidence limits:** synthetic faults only; one Oxford drive plus DRIVE-C's ten scenes; no real lens dirt; never a road-safety claim.
