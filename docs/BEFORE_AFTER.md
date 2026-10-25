# COOLPilot: before and after

A running record of what changed and what it measurably did. Every number comes from a stored run or an evidence file in `docs/evidence/`. Items marked **pending** are still being measured. This file is updated when they finish.

Last updated: 2026-10-25 03:25 UTC. Graviton verification and DRIVE-C evaluations complete (including a failed, reverted night fix); joint Oxford + DRIVE-C dev tuning done, validated, shipped with two choices dropped (section 6b); audited against the evidence files.

## At a glance

| | Before (start of this work) | After, so far |
|---|---|---|
| Fault checks failed, tuning camera | 4 of 6 | **0 of 6** (detector); 1 of 6 with the verifier, because the one "obstruction pass" was a sky coincidence |
| Fault checks failed, unseen cameras | 12 of 18 | **5 of 18** |
| False alarms per hour, unseen cameras (original set) | 1,099 | 283 (detector) → **10.9 with the rule verifier** |
| False alarms per hour, 42 fresh never-inspected clips | n/a | 232 (detector) → **0 with the rule verifier**: unpaced and paced real-time, on Graviton |
| OpenCV 5 features used | none beyond 4.x functions | **new DNN graph engine** (NanoDet on CPU) inside the verifier |
| Agent role | tuning settings only | tuning **plus** a runtime verifier that measures, then confirms, dismisses or escalates to a human |
| Measured on AWS Graviton (OpenCV 5.0.0) | no; all evidence from a Mac | yes: baseline, random search, three agent runs, paced held-out runs |
| Tests | 37 at the first QA check of this work (3 failing mid-change) | 61 passing locally (OpenCV 4.13) and on Graviton (OpenCV 5.0.0) |
| Independent data (DRIVE-C, no tuning) | not tested | day scenes: **78/210 (37%)** of our fault classes caught at onset (motion blur and strong under-exposure transfer; defocus 0/50); **night scenes false-alarm on darkness** (3/3) |
| Joint tuning (Oxford + DRIVE-C dev), section 6b–6c | n/a | shipped: detail at 640 px, `obstruction_s` 1.2, night policy. DRIVE-C test (seen) day **13 → 28/60**, night **0 → 29/90**; never-inspected Oxford fresh2/fresh3: 4/18 failed, **0 false alarms/h with the verifier**. Self-calibration and the diagnostic autopilot are built and tested; neither beat the shipped defaults or random search on unbiased data |
| Product surface | dashboard + replay | + **Check footage**: upload a clip → S3 → Graviton Lambda → segment report, file deleted after |

## 1. Detector (per-camera relative rules)

**Before.** Absolute thresholds that ignored what normal looks like for each camera. Run #63 failed 15 of 53 gate checks, with 1,332 false alarms per hour. Sky tiles are 58–96% clipped in clean footage, so the glare rule fired constantly.

**After.** Each camera is compared with its own learned normal. Thresholds were calibrated on the tuning (centre) camera only, then frozen.

Unpaced, every frame analysed once (`docs/evidence/calibration/`). "Before" is the original code (git HEAD before this work) run on the Mac with OpenCV 4.13:

| | Tuning, before | Tuning, after | Held-out, before | Held-out, after |
|---|---|---|---|---|
| Failed fault checks | 4/6 | 0/6 | 12/18 | **5/18** |
| False alarms per hour | 1,324 | 37 | 1,099 | **283** |
| blur | fail | pass | 0/3 | **3/3** |
| underexposure | fail | pass | 0/3 | **3/3** |
| blackout | pass | pass | 3/3 | 3/3 |
| freeze | pass | pass | 3/3 | 3/3 |
| glare | fail | pass | 0/3 | 1/3 |
| obstruction | fail | pass (sky coincidence) | 0/3 | 0/3 |

Paced at real sensor timing on **EC2 t4g.small, Graviton2, OpenCV 5.0.0**, held-out, 3 repetitions (`docs/evidence/aws/holdout-defaults-validation.summary.json`):
- Same outcome as unpaced: blackout, blur, freeze and underexposure 9/9; glare 3/9; obstruction 0/9.
- 285 false alarms/h.
- 0.25 CPU-s per camera-second; maximum result age 0.23 s.
- Results match across Mac/OpenCV 4.13 and Graviton/OpenCV 5.0.

## 2. Search by tuning (agent vs random), on AWS Graviton

All on the tuning split, same gates, budget 8, 3 repetitions (`docs/evidence/aws/run-*.json`):

| Run | Result |
|---|---|
| Baseline | Fails only the 0 false alarms/h gate (37/h) |
| Random search, 8 candidates | All worse: 9–27 failed checks, up to 667 false alarms/h |
| Agent run 1 | Tuned processing settings only; its summary miscounted its own experiments |
| Agent run 2 | Detector values rejected (the model sent them as a JSON string); **fixed** |
| Agent run 3 (fair) | Tuned detector limits; best candidates equal the baseline; none passed |

**What this proved:** no threshold setting removes the last false alarm, because it comes from a scene change, not a threshold. That led to the verifier. A record-backed summary line now leads every agent summary; in run 3 it corrected the model's claim of "33 experiments" (it ran 7).

## 3. Second-stage verifier (Recommendation 1)

**Before.** Every obstruction suspicion became an alarm.

**Change (idea C).** An obstruction suspicion **never alarms on its own**; only a verifier verdict (confirm or escalate) or a verifier failure turns it into an alarm.

**After.** A suspicion is investigated on the last second of frames:
- texture / open sky
- road users from NanoDet on OpenCV 5's new DNN engine
- optical flow

Three arms are compared. Limits were fixed on the tuning clips before any held-out run.

| Split | Arm | Failed checks | False alarms (per hour) | Notes | Where measured |
|---|---|---|---|---|---|
| Tuning (7 clips) | none | 0/6 | 1 (36.8) | | Graviton |
| | rule | 1/6 | **0 (0)** | the "obstruction pass" was the same sky tile, now correctly dismissed | Graviton |
| | agent | 1/6 | 1 (36.8) | both suspicions escalated to a human instead of dismissed; 3.2 s each | Graviton |
| Original held-out (21) | none | 5/18 | 26 (283) | | Graviton |
| | rule | 5/18 | **1 (10.9)** | remaining one is loss during an undetected glare | Graviton |
| | agent | 5/18 | 11 (119.7) | 14 dismissed, 12 escalated; median 3.8 s, max 13.4 s | Graviton |
| **Fresh held-out (42, never inspected)** | none | 11/36 | 42 (232.4) | | Graviton (Mac identical) |
| | rule | 11/36 | **0 (0)** | 43/43 suspicions dismissed; median 0.125 s, max 0.21 s each (Mac: at most 0.08 s) | Graviton (Mac identical) |
| | agent | 11/36 | 18 (99.6) | 25 dismissed, **18 escalated to a human** (each counted as a kept alarm), 0 confirmed, 0 errors; median 2.9 s, max 12.6 s. A Mac run of the same arm gave 11 (60.9): not reproducible even at temperature 0 | Graviton |
| **Fresh held-out, paced real time, 2 repetitions** | off | real faults identical across arms | **233.8 /h** | CPU 0.251 s per camera-s, max age 0.36 s | Graviton |
| | rule | (blackout/blur/freeze/underexposure 12/12; glare 2/12; obstruction 0/12) | **0.0 /h** | CPU 0.294 (+17% for verification), max age 0.25 s, 98 verdicts | Graviton |

Reading it honestly:
- The rule verifier removed every false alarm on fresh data **without losing a real detection**: real-fault results are identical in every arm.
- **41 of 43 fresh suspicions are the same sky tile of the same drive.** This shows one failure mode fixed reliably, not general robustness.
- The **LLM agent is worse than the fixed rule** here. It never errored and never confirmed on its own: every alarm it keeps is an escalation to a human. But it is about 23× slower on Graviton (median 2.9 s vs 0.125 s) and not reproducible across runs (18 vs 11 kept alarms on the same clips). Its value is cited reasons and escalation to a human. The rule stays the default.

In-app (live replay), the verifier runs on every suspicion and the UI shows the verdict, reason, tools, DNN engine and latency. On a clean replay, the sky suspicions at about 4.1–4.4 s are dismissed in about 0.08 s (QA rounds 5–5c).

### Alarm-delay curve (fresh held-out, 36 fault checks)

How many faults are caught and cleared if the allowed delay is longer, as in offline screening or CCTV:

| Arm | within 2 s | within 10 s | within 60 s | False alarms/h |
|---|---|---|---|---|
| none | 25/36 | 28/36 | 28/36 | 232.4 |
| rule | 25/36 | 27/36 | 27/36 | **0.0** |

The one check "lost" at 10 s is not a real detection. In `rear_s3301_obstruction`, the smudge is at (0.65, 0.55) and ends at 5.67 s; the alarm that "caught" it at 10 s tolerance is the sky tile at 7.45 s (top row), which the rule correctly dismisses. Which fault types gain at longer delays is not broken down yet.

## 4. OpenCV 5 depth

| | Before | After |
|---|---|---|
| OpenCV 5-specific features | none (identical code path on 4.13) | NanoDet-Plus (OpenCV model zoo, Apache-2.0) on the **new DNN graph engine** |
| Detector speed, same Mac, 1 thread | n/a | new engine **21.2 ms** vs 4.13 classic 34.4 ms, identical detections |
| Same comparison on Graviton2 (t4g.small), 1 thread | n/a | new engine **71.9 ms** vs 4.13 classic 96.0 ms (**1.34× faster**), identical detections |
| Per-stage OpenCV 4.13 vs 5.0 on Graviton, same host | n/a | total 1.09× (decode 1.11×, our OpenCV analysis 0.98×: no gain); **alarms identical**; tile statistics differ slightly (brightness ≤2 grey levels, detail ≤2.9%), consistent with the KleidiCV resize differences the OpenCV team notes |
| Found along the way | n/a | The new engine orders outputs differently (now paired by shape); one shared `Net` is not thread-safe (now locked, with a test) |

## 5. Footage quality gate (Recommendation 2)

| | Before | After |
|---|---|---|
| Can a user check their own recording? | No | Yes: **Footage** page → presigned S3 upload (≤50 MB, ≤60 s) → Graviton Lambda, OpenCV 5.0.0 → per-segment report with thumbnails, JSON/CSV |
| Data handling | n/a | File deleted from S3 and `/tmp` after analysis, success or failure; 1-day lifecycle backstop; CORS limited to the site; rate-limited |
| Verified on the live site (QA round 6) | n/a | Blackout clip: one segment 4.22–10.76 s, 6.4× real time. Clean clip: nothing flagged, its sky suspicion dismissed. `uploads/` empty afterwards |

## 6. Independent test: DRIVE-C (Recommendation 2)

DRIVE-C (CC BY 4.0, doi:10.5281/zenodo.19656444) is someone else's benchmark: 10 real driving scenes recorded in Michigan, 3 of them at night, 1280×720 at 30 fps, with 12 corruption types at 5 severities made by their own code. Nothing was tuned on it; COOLPilot ran with its frozen defaults and the rule verifier, on Graviton with OpenCV 5.0.0. We fetched 370 of the 610 clips (all severities of the 6 types that match our fault classes, severity 3 of the other 6) with HTTP range requests (`experiments/drivec_fetch.py`).

Protocol (`experiments/drivec_eval.py`):
- **onset:** the scene's clean clip followed by the corrupted clip, so the fault starts mid-recording. Pass = an alarm of the right class within 2 s of the join, with nothing raised before it.
- **alone:** the corrupted clip by itself, a camera that starts broken.

| | Result |
|---|---|
| Clean clips, any alarm | **4 of 10**: all 3 **night** scenes raise "underexposure" within 0.3 s; 1 day scene (S10) raises an obstruction the verifier did not dismiss |
| Our fault classes at onset, **day** scenes | **78 / 210 (37%)** |
| Our fault classes at onset, **night** scenes | **0 / 90**: every night clip already alarmed on its clean part |

Detection at onset, by type and severity (s1 = mildest … s5 = strongest; each cell is passes out of 10 scenes, 3 of which are night and fail anyway):

| DRIVE-C type → our class | s1 | s2 | s3 | s4 | s5 | Why |
|---|---|---|---|---|---|---|
| motion_blur → blur | 6 | 6 | 6 | 6 | 6 | Whole-frame blur: median tile detail falls to 5–25% of normal (measured on scene S01). Caught in 6 of the 7 day scenes |
| glare_flare → glare | 5 | 5 | 6 | 6 | 6 | Partly works |
| underexposure → underexposure | 0 | 0 | 1 | 6 | 6 | Only strong darkening crosses the 0.55× ratio |
| low_light → underexposure | 0 | 0 | 0 | 0 | 4 | Same, plus added noise |
| **defocus_blur → blur** | **0** | **0** | **0** | **0** | **0** | DRIVE-C's defocus is **depth-dependent**: much of the frame stays sharp (in scene S01 the median tile keeps 72% of its detail even at s5). Our rule needs the typical tile to lose 65% |
| lens_occlusion → obstruction | 1 | 1 | 1 | 0 | 0 | Consistent with our own smudge result |

Out-of-class corruptions at severity 3 (fog, rain, snow, sensor noise, JPEG, overexposure): 19 of 60 clips raise something after the join, mostly "blur" (10), then glare (7) and obstruction (2).

By DRIVE-C's own split (scene-level; dev = S01–S05, all daytime; test = S06–S10, which holds **all three night scenes**):

| Split | Our fault classes caught at onset | Clean clips with an alarm | Joined clips alarming before the fault |
|---|---|---|---|
| dev (5 day scenes) | 65/150 (43%) | 0/5 | 0/180 |
| test (2 day + 3 night scenes) | 13/150 (9%): day 13/60, night 0/90 | 4/5 | 144/180 (108 underexposure, 36 obstruction) |

**Night fix attempted, failed, reverted.** The idea came from a principle: alarm on absolute darkness only when the frame is also featureless, because night is dark but detailed. Order of work:
1. The failure mode was first seen on the DRIVE-C test split.
2. The rule was then written without fitting numbers to night clips.
3. It was checked on dev: every Oxford split gave identical results.
4. It was run once on the test split.

Result: **no change**. All three clean night scenes still alarm within 0.3–0.43 s, and night detection stays 0/90. At our analysis scale DRIVE-C's night footage is dark **and** low-detail, which is also exactly what a camera that starts too dark looks like. Frame statistics alone cannot separate the two when a clip starts dark. Exposure metadata, time of day or a learned model would be needed. The change gave no measured benefit and was reverted. The test split is now considered seen for night, so no further night tuning was done on it. Evidence: `docs/evidence/aws/drivec-nightfix.json`.

What it changes in the claims:
- **Night is out of scope today.** The absolute darkness fallback (mean brightness below 35, meant for a camera that starts broken) fires on normal night driving. It was never exercised on our daytime Oxford drive.
- **"Blur" means whole-frame blur.** Partial, depth-dependent defocus is missed.
- On independent daytime footage, motion blur and strong under-exposure transfer; glare transfers partly; subtle faults do not.

Evidence: `docs/evidence/aws/drivec.json` (per clip and per cell).

## 6b. Joint tuning: Oxford + DRIVE-C dev (round-4 freeze failed validation; shipped setup drops two choices)

After section 6, the detector is being tuned on **Oxford tuning clips plus DRIVE-C dev scenes (S01–S05, all daytime)** together, in rounds (`experiments/joint_calibrate.py`, Graviton t4g.small, OpenCV 5.0.0).
- **Unpaced and detector only**, without the verifier, so obstruction is judged strictly.
- **Constraint:** Oxford tuning may not fail more checks than the defaults (0/6).
- **DRIVE-C protocol:** the onset protocol from section 6.
- **Validation only once, after the last round:** Oxford held-out cameras and DRIVE-C test scenes (S06–S10, which include all night scenes) are not read until then. The numbers below are therefore **tuning-data numbers, not generalisation**.

| Round | Change | Oxford tuning failed | Oxford false alarms | DRIVE-C dev detected | DRIVE-C dev false alarms |
|---|---|---|---|---|---|
| 0 | Baseline: current defaults | 0/6 | 1 | 39/150 | 62 |
| 1 | Values only (324 combos): `obstruction_s` 0.5 → 1.2, `dark_ratio` 0.55 → 0.75 | 0/6 | 1 | 82/150 | 0 |
| 2 | Code: detail operator (Laplacian ksize 1 / 3, Tenengrad on the KleidiCV Sobel path), aspect-preserving resize. **None helped, none adopted.** Values: `dark_ratio` → 0.8 | 0/6 | 1 | 90/150 | 0 |
| 3A | Code: obstruction tile limit made a setting (was fixed at 6), `scene_keep_ratio` in the grid. **No effect** | 0/6 | 1 | 90/150 | 0 |
| 3B | Code: detail measured at 640 px instead of 320. Defocus 0 → 7/25 | 1/6 (only `centre_obstruction`, see below) | 1 | 97/150 | 0 |
| 4 | Code: low-light rule (darker than 0.9× **and** saturation ×1.4 or noise ×1.15), so `dark_ratio` goes **back down** to 0.65; accumulated obstruction score (tried, not adopted). **Frozen** | 0/5 guarded (`centre_obstruction` excluded) | 1 | 97/150 | 0 |

Per class on DRIVE-C dev, round 0 → 2 → 4 (frozen):

| Class | Round 0 | Round 2 | Round 4 |
|---|---|---|---|
| motion blur | 15 | 25 | 25 |
| glare | 13 | 23 | 23 |
| underexposure | 6 | 21 | 18 |
| low light | 2 | 21 | 24 |
| defocus | 0 | 0 | 7 |
| lens occlusion | 3 | 0 | 0 |

Findings so far:
- **The 62 false alarms were one cause:** obstruction firing on 2 of 5 clean dev scenes before any fault. That alone failed every fault clip from those scenes. A longer `obstruction_s` removed it.
- **Two measurement problems, found by comparing each corrupted clip with its clean original frame by frame:**
  - **Defocus:** our 320-pixel detail scale hides it (s5 keeps 0.76 of clean detail). At 640 pixels it keeps 0.40, and at native 1280 pixels 0.12.
  - **Lens occlusion:** it lowers up to 7 tiles, but the obstruction rule was hard-coded to accept at most 6.
  - Round 3 tests both fixes.
- **Occlusion (round 3):** DRIVE-C's blob covers tiles only partly, so each tile's detail flickers around the limit and the "same tiles low for 1.2 s" clock keeps resetting. Round 4 tests an accumulated per-tile score instead (rises while low, leaks away otherwise), as in published soiling detectors.
- **Rule change after round 3 (user decision: one setup for all footage):** the guard no longer protects the Oxford `centre_obstruction` check, which section 1 already documents as a sky coincidence (the clean reference flags the same tile at the same moment). The other 5 Oxford checks must still pass and Oxford false alarms still count. Ties go to the candidate closest to the defaults.
- **Round 4 choice, made on purpose:** a tie (97) with `dark_ratio` 0.8 and no low-light rule. The tie-break would have picked 0.8; it was overridden because a specific rule (low light also raises saturation or noise, measured frame by frame) should fail less on unseen footage than a broad 20% darkening threshold. The cost on dev: 3 mild plain-underexposure clips that look like a cloud.
- **Occlusion stays unsolved:** settings loose enough to catch DRIVE-C's occlusion fire on the clean part first, and severe occlusion is reported as blur. Defocus s1–s3 and underexposure s1 are at the limit of the signal. Tuning stopped after round 4.
- **Frozen:** detail measured at 640 px everywhere (smaller analysis widths are raised to it), plus the round 4 values, as the `CameraThresholds` defaults. 60 tests pass on the Mac and on Graviton.
- **Overfitting risk (rounds 1–2):** `dark_ratio` 0.8 alarms on a 20% brightness drop, which clouds, shadows or tunnels can also cause. It is capped at 0.8; held-out validation decides.

**Validation of the round-4 freeze (run once, data never used in tuning): failed on DRIVE-C test.**

| Data | Before tuning | Round-4 freeze |
|---|---|---|
| Oxford held-out (21 clips): failed checks, false alarms/h detector, with verifier | 5/18, 283, 10.9 | 5/18, 272, 10.9 |
| Oxford fresh (42 clips) | 11/36, 232, 0 | 10/36, 221, 0 |
| **DRIVE-C test, day scenes** | **13/60** | **0/60** |
| DRIVE-C test, night scenes | 0/90 | 0/90 |
| DRIVE-C test, clean day scenes with an alarm | 1/2 | **2/2** |

It overfit to the 5 dev scenes. An alarm on a clean scene fails every fault clip of that scene, so two new false alarms cost all 60 day test clips. One change at a time on the clean test scenes:
- **S09:** "blur" comes from `blur_ratio` 0.5 at the 640 scale. With 0.35 there is no alarm.
- **S10:** "underexposure" comes from the low-light rule, the round-4 choice made over the tie-break. With the rule off there is no alarm.

**Decision (user):** drop exactly those two choices: the low-light rule goes off (the code stays, off by default) and `blur_ratio` returns to 0.35. Detail at 640 and `obstruction_s` 1.2 stay. Nothing is re-tuned on dev. Because this was decided after looking at DRIVE-C test, **DRIVE-C test is now seen**: its next number is reported as "after seeing test", not as independent evidence.

**Re-validation of the shipped setup (round-4 freeze minus the two failed choices):**

| Data | Before tuning | Round-4 freeze | **Shipped** |
|---|---|---|---|
| Oxford held-out, **unbiased**: failed checks, false alarms/h (detector / verifier) | 5/18, 283 / 10.9 | 5/18, 272 / 10.9 | **5/18, 272 / 10.9** |
| Oxford fresh, **unbiased** | 11/36, 232 / 0 | 10/36, 221 / 0 | **10/36, 221 / 0** |
| DRIVE-C dev (tuning data, with verifier) | 65/150 | 97/150 | **77/150** |
| DRIVE-C test, day (**seen**) | 13/60 | 0/60 | **28/60** |
| DRIVE-C test, night | 0/90 | 0/90 | 0/90 |
| DRIVE-C test, clean day scenes with an alarm | 1/2 | 2/2 | **0/2** |

DRIVE-C test day by class, before → shipped:

| Class | Before | Shipped |
|---|---|---|
| motion blur | 5 | 10 |
| glare | 5 | 7 |
| underexposure | 2 | 6 |
| low light | 1 | 5 |
| defocus | 0 | 0 |
| occlusion | 0 | 0 |

What this supports:
- **On unbiased data (Oxford), the gain is small but real:** one more passed check on fresh, and about 5% fewer detector false alarms. With the verifier, the false-alarm rates are unchanged.
- **DRIVE-C test improved, but it is seen data**, so it is not independent evidence. The clearest mechanism: `obstruction_s` 1.2 removed the clean-scene obstruction alarm on S10.
- **Unchanged:** night (normal night driving still alarms as underexposure), defocus on test, and occlusion.

**Cost of measuring detail at 640 px** (Graviton t4g.small, one thread, OpenCV 5.0.0): analysis goes from 1.46 to 3.38 ms per frame on a 1280×960 Oxford frame, and from 1.91 to 3.62 ms on a 1280×720 DRIVE-C frame. That is about 1.8 ms more per frame, roughly 2.5% of one core per camera at the replay's ~14 frames per second.

**Lesson:** five daytime dev scenes are too few to select rule changes. Choices without a measured mechanism (the low-light rule, a looser blur ratio) fit dev and broke on test. The defaults now shipped are this setup.


Evidence: `docs/evidence/tuning/rounds.json` (one entry per round) and `round*.json` (per-clip results).

## 6c. Plan: self-calibrating detector + diagnostic autopilot (Ideas 2 + 1)

**Why:** tonight's real gains came from diagnosis, not search: the frame-by-frame paired comparison found the detail-scale problem, one-change ablation found the S09/S10 causes, and per-frame traces explained the occlusion misses. Those were done by hand. Both validation failures came from fixed values meeting a scene with a different normal.

**Idea 2: self-calibrating thresholds (pattern-based).**
- Each camera learns the normal **spread** of its brightness ratio and its detail ratio while healthy: an exponentially weighted mean absolute deviation of the log ratio.
- Underexposure and blur fire when the ratio drops by more than `adaptive_k` × spread, and by at least a minimum effect (`adaptive_floor_dark`, `adaptive_floor_blur`). A busy scene widens its own band; a calm scene narrows it.
- `adaptive_k` = 0 keeps today's fixed ratios.
- **Night regime:** night clips alarmed at 0.3 s from the absolute darkness rule. New setting `dark_at_start_alarm`: when false, a camera that has been dark since its first frame is treated as its own normal, and the relative rules still apply after warm-up. Cost, stated up front: a camera that is broken-dark from power-on is not flagged.
- **Not planned:** CUSUM for occlusion. Round 4 showed that settings loose enough to accumulate DRIVE-C's flicker fire on clean scenes first.

**Idea 1: diagnostic autopilot.** An LLM agent (Nebius, temperature 0) works on the tuning data only (Oxford tuning + DRIVE-C dev), with OpenCV 5 tools:
- `evaluate(settings)`: per class and per scene, with the failing clips listed.
- `explain_failure(clip, settings)`: a per-frame trace around onset showing which rule fired or was blocked.
- `paired_compare(fault)`: per-tile change in detail, brightness, saturation and noise against the clean original, same frames.
- `ablate(settings, name, values)`: one change at a time.
- `propose(settings, rationale)`: written as a **pending proposal**. It is applied only after explicit human approval (`--approve`).

Every tool result and decision goes into a trace file.

**Fair comparison, same evaluation budget:** agent with diagnostic tools, agent with only `evaluate`, and seeded random search.

**Validation, once, after both:**
- a **new Oxford holdout** (new seeds, never inspected)
- Oxford fresh
- DRIVE-C test (seen since section 6b, so labelled that way)

The shipped defaults change only if the agent-approved settings beat the current defaults on the unseen Oxford holdout without losing DRIVE-C test.

**Reporting:** a before/after table per step in this section and in `docs/evidence/tuning/rounds.json`.

### 6c results so far: comparison on tuning data (budget 16 evaluations per arm)

| Arm | DRIVE-C dev caught | False alarms | Oxford failed | Settings found |
|---|---|---|---|---|
| Baseline (shipped defaults) | 77/150 | 0 | 0 | `adaptive_k` 0 (fixed ratios) |
| Agent + diagnostic tools | 101/150 | 0 | 0 | `adaptive_k` 3, floors 0.20 / 0.40 |
| Agent, `evaluate` only | 102/150 | 0 | 0 | `adaptive_k` 3, floors 0.17 / 0.37 |
| Random search, seeds 1 / 2 / 3 | 103 / 100 / 83 (mean 95) | 0 | 0 | seed 1: `adaptive_k` 2.15 |

- **The self-calibrating detector (Idea 2) is the lever:** every arm found that it lifts DRIVE-C dev from 77 to about 101.
- **The diagnostic tools (Idea 1) did not beat `evaluate` only or random search at this budget.**
  - The tools agent's trace shows the intended loop: it called `paired_compare` on 4 fault types, then ablated `adaptive_k` and found that 3 works.
  - It then repeated calls after its budget ran out.
- **Fragility:** the `evaluate`-only floors sit on a knife edge. A dark floor of 0.17 gives 0 false alarms; 0.16 gives 31. The tools proposal has more margin: 0.15 gives 31, and 0.25 gives 95 caught.
- **Run 1 had two bugs of ours**, kept as `docs/evidence/autopilot/*-run1.json`:
  - the `evaluate`-only arm could call tools it was not offered
  - settings had no descriptions, so neither agent tried `adaptive_k`, and both proposed the defaults
  
  Both bugs were fixed before the rerun above.

Evidence: `docs/evidence/autopilot/` (full traces).

### 6c validation (run once)

| Candidate | Oxford fresh2 (**unbiased**): failed, detector FA/h, verifier FA/h | DRIVE-C test day (seen) | DRIVE-C test night | Clean night scenes alarming |
|---|---|---|---|---|
| **Shipped defaults** | 4/18, 238, **0.0** | **28/60** | 0/90 | 3/3 |
| Shipped + night policy | 4/18, 238, n/a (identical detector) | 28/60 | **29/90** | **1/3** |
| Agent proposal (`adaptive_k` 3) | 4/18, 271, **32.5** | 18/60 | 0/90 | 3/3 |
| Agent proposal + night policy | n/a | 18/60 | 26/90 | 1/3 |
| Random seed 1 | 5/18, 282, 10.8 | n/a | n/a | n/a |

- **Self-calibration, as the agents tuned it, is rejected.** It catches nothing extra on unseen Oxford clips and adds verifier-checked false alarms (0 → 32.5/h). On DRIVE-C test, day footage drops from 28 to 18.
  - **Mechanism:** the self-calibrated blur floor (about 33% detail loss) fires on the washed-out detail of glare. The fixed rule needs 65%.
  - It overfit DRIVE-C dev, the same pattern as round 4. The code stays, off by default.
- **The autopilot is a safety loop here, not an optimiser.** It found a change that looked better on tuning data (77 → 101). Validation exposed it, and the human-approval gate kept it out of the defaults. It did not beat random search.
- **The night policy helps at night, with a stated cost.**
  - Night: 0 → 29/90 caught, and clean night scenes alarming drop from 3 to 1.
  - Oxford is unchanged.
  - Cost: a camera dark from power-on (DRIVE-C "alone" protocol, underexposure + low light) is caught 4/100 times instead of 32/100.
  - Shipping it is a product decision, left to the user.

**Decisions after 6c validation:**
- **Cleanup:** code that was tried and not adopted was removed: the Tenengrad and Laplacian ksize 3 operators, the aspect option, the accumulated obstruction score, and the low-light rule with its per-frame saturation and noise measurements. Recomputed measurements match the pre-cleanup cache exactly (maximum difference 0 over 40 frames on Graviton). The evidence files still record each attempt.
- **Night policy: shipped (user decision).** `dark_at_start_alarm` is now off by default. Footage reports carry `dark_since_start`, and the UI tells the operator to verify the camera if the footage is not night.
- **Targeted self-calibration attempt.** Validation put the failure in the blur half only; the brightness half added no false alarms on fresh2. Candidate:
  - **Brightness:** self-calibrating (`adaptive_k` 3, darkness floor 0.2).
  - **Blur:** never looser than the validated fixed rule (floor 1.05, the log of 1/0.35), so it can only get stricter on busy scenes.
  - **Tuning data:** 95/150 (shipped 77); low light 11 → 24, underexposure 15 → 20.
  - **Next:** validated once on **fresh3**, new Oxford seeds never inspected, plus DRIVE-C test (seen). It ships only if it beats the shipped defaults on fresh3.

**Result of the targeted attempt.** The fresh3 numbers were measured on the Mac with the same OpenCV 5.0.0, because the upload to EC2 fell to 25 KB/s; earlier runs gave identical alarms on Mac and Graviton for this detector. DRIVE-C was measured on Graviton.

| | Oxford fresh3 (**unbiased**): failed, detector FA/h, verifier FA/h | DRIVE-C dev | DRIVE-C test day (seen) | DRIVE-C test night (seen) |
|---|---|---|---|---|
| Shipped defaults (night policy on) | 4/18, 244, 0.0 | 77/150 | 28/60 | 29/90 |
| Self-calibrating brightness, blur never looser | 4/18, 244, 0.0 (identical) | 95/150 | 35/60 | 15/90 |

- **Not shipped.** The rule set beforehand required beating the shipped defaults on fresh3, and the candidate ties. Self-calibration stays in the code, off by default.
- **"Blur never looser" removed the new false alarms**, so the failure mechanism found in 6c was the right one.
- **Oxford's synthetic faults are strong enough** that the fixed rules already catch them, so self-calibration has nothing to add there.
- **On DRIVE-C test the result is mixed.** Day footage gains 7 clips. Night loses 14, because a clean night scene (S08) raises a false obstruction alarm before the fault starts.
- **Honest conclusion:** per-camera self-calibration is the right idea for varied real footage, but our data cannot show it helps. Showing that needs more, and more varied, real recordings.

## 7. Deployment, operations and other changes

| | Before | After | Evidence |
|---|---|---|---|
| Public site (Lambda, arm64, OpenCV 5.0.0) | Old detector: the sky made glare fire constantly; History held Mac-measured runs | New detector + verifier + footage gate; History seeded from the **AWS-measured** database; QA round 4: no constant sky-glare alarm on a live replay; QA round 6: verifier reports "DNN engine: new" | QA rounds 4 and 6 |
| Public site after joint tuning (2026-10-25) | Detail at 320 px, darkness alarm on night footage | Redeployed with detail at 640 px, `obstruction_s` 1.2, the night policy and the footage "dark since the first frame" note. The package was built on EC2 and uploaded to S3 with a one-object presigned URL, because the operator's uplink was about 29 KB/s. Data and History are unchanged. Lambda reports OpenCV 5.0.0 on aarch64, read-only. **QA round 8 (real uploads):**<br>- clean night S07: no alarm, with the "dark since the first frame" note<br>- clean night S06: one brief low-brightness alarm at 3.7 s. This is the documented remaining clean-night false alarm; S06 is not dark from its first frame<br>- clean day S02: no alarm<br>- blur fault clip: blur segment at 2.2–3.7 s<br>- live replay: no constant sky glare, glare only on the glare clip, sky obstruction dismissed in about 2 s<br>- History intact, no console errors, no em dashes<br>The stale "one recorded drive" text QA surfaced was fixed and redeployed | QA round 8 |
| Observability | None | CloudWatch EMF metrics (`COOLPILOT_METRICS=1`) for replays, live sessions, experiments and footage, plus a `coolpilot` dashboard; first replay metrics confirmed in CloudWatch | QA round 4 |
| Live camera input | None | Operator-configured `VideoCapture` sources (names only, never client URLs), reconnect with backoff, files paced to their frame rate. **Not tested on a real camera** | `tests/test_live.py` |
| COOL | Not prepared | `docs/COOL.md` (facts, paths, evidence checklist), COOL-mode `remote_setup.sh`, generation-aware `launch.sh`, runtime detection with a test. **Not run on COOL** (account limitation) | `docs/COOL.md` |
| Data | Centre camera only (7 clips) | `oxford-camera-holdout` (21 held-out clips; hash `9ae2465c` kept byte-identical for its runs) and `oxford-camera-holdout-fresh` (42 never-inspected clips, seeds 1101/1102, 2201/2202, 3301/3302; hash `2000c5f8`); the fresh clips stay on the EC2 evaluation host and are not on the public site, to keep Lambda cold starts lean | `scripts/build_holdout_dataset.py` |

Agent guardrails added after measured failures:
- detector values sent as a JSON string are decoded, then still bounded by the schema (run 2 failure)
- a failure of only the closing summary no longer fails a completed search (run 2 failure)
- every summary leads with the recorded counts (run 1 and run 3 miscounts)
- the verifier agent cannot decide before measuring (observed hallucinated tool use)
- an overlong reason is truncated rather than rejected
- any provider or tool error keeps the alarm
- temperature 0

Bugs found and fixed during this work (most by the QA agent):
- three replay threads shared one DNN `Net` and corrupted detections (now locked, with a test)
- the footage screen re-verified the same suspicion every frame (now one verdict per suspicion)
- a CSS class collision broke the verdict layout on mobile
- file live sources looped with "reconnects" (now paced)
- em-dash placeholders in UI copy
- three tests broken mid-change, then repaired

## 8. Tried and dropped (with reasons)

| Idea | Outcome |
|---|---|
| B. Glare "bloom" rule | Dropped: in clean footage tiles brighten by up to 0.68 of headroom; real glare is about 0.80. Too little margin |
| D. Dedicated smudge detector | Skipped: two earlier cue tests (4×4 and 8×8 temporal change) showed no separation |
| Tuning harder (agent or random) | No configuration passed every gate; see section 2 |

## 9. Still failing (unchanged by this work)

- **Glare:** 1 of 6 on fresh held-out cameras.
- **Lens obstruction (translucent smudge):** 0 of 6. The trigger never fires on the real smudge, so the verifier cannot help.
- **Night driving:** the darkness fallback raises false underexposure alarms (DRIVE-C, 3 of 3 night scenes).
- **Partial (depth-dependent) defocus:** 0 of 50 on DRIVE-C.
- **Mild under-exposure and low light:** caught only at the strongest severities on DRIVE-C.
- **No real lens dirt** anywhere in the evidence; all faults are synthetic.

## Evidence index

| Claim | File |
|---|---|
| Starting point: run #63 (15/53 gate checks failed, Mac/OpenCV 4.13) | `docs/evidence/run63-before.json` |
| Detector before/after (unpaced) | `docs/evidence/calibration/{tuning_old,tuning_new,holdout_old,holdout_defaults}.json`, sweep `sweep-tuning.json` |
| Paced held-out on Graviton | `docs/evidence/aws/holdout-defaults-validation.summary.json`, `calibrate-*.json` |
| Tuning search runs (baseline, random, agent 1–3) | `docs/evidence/aws/run-*.json` |
| Verifier, three arms × three splits, Graviton | `docs/evidence/aws/verify-oxford-camera-holdout-*.json`, log `verify-job.log` |
| Paced fresh held-out, verifier off vs rule | `docs/evidence/aws/paced-fresh-{off,rule}.summary.json` |
| Alarm-delay curves | `docs/evidence/delay-curves-fresh.json` |
| OpenCV 4.13 vs 5.0 on Graviton | `docs/evidence/aws/dnn-4x.json`, `dnn-standard.json`, `profile-4x-vs-5x.txt` |
| Build and tests on Graviton | `docs/evidence/aws/build-standard.txt`, `tests-standard.txt` |
| DRIVE-C (independent) | `docs/evidence/aws/drivec.json` |
| Night-fix attempt (no effect, reverted) | `docs/evidence/aws/drivec-nightfix.json` |
| Joint tuning rounds (Oxford + DRIVE-C dev) | `docs/evidence/tuning/rounds.json`, `round*.json`, grids `grid*.json` |
| Local DRIVE-C sample + randomized faults | `data/drivec_sample/`, `data/camera_health/drivec-sample/` (gitignored; rebuild with `scripts/generate_drivec_sample.py`) |

## Pending (this file will be updated)

- [x] Fresh held-out, three arms, on Graviton
- [x] Paced fresh held-out, verifier off vs rule, on Graviton
- [x] OpenCV 4.13 vs 5.0 on Graviton: DNN timing and per-stage profile
- [x] Lambda redeployed with the verifier, model, footage upload and final history; QA round 6 passed on the live site
- [x] Recommendation 2: S3 → Lambda footage gate, alarm-delay curves in `verify_eval`
- [x] Recommendation 2: DRIVE-C evaluation (independent dataset), on Graviton
- [x] Alarm-delay curves (2 s / 10 s / 60 s), fresh held-out (`docs/evidence/delay-curves-fresh.json`; OpenCV 5.0 on Mac, whose none/rule arms matched Graviton exactly)
- [x] Joint tuning rounds 0–4, validation (failed on DRIVE-C test), shipped setup re-validated (section 6b)
- [x] Section 6c: self-calibrating detector + diagnostic autopilot, comparison, validation (night policy shipped; self-calibration not shipped)
- [ ] Recommendation 3 (COOL): standard vs COOL on the same Graviton host, when the account is ready
