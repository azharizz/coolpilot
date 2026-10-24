# COOLPilot: before and after

A running record of what changed and what it measurably did. Every number comes from a stored run or an evidence file in `docs/evidence/`. Items marked **pending** are still being measured. This file is updated when they finish.

Last updated: 2026-10-24 12:30 UTC. Graviton verification and DRIVE-C evaluations complete; audited against the evidence files.

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
| Tests | 37 at the first QA check of this work (3 failing mid-change) | 57 passing locally on OpenCV 4.13 (53 confirmed on Graviton before the footage and concurrency tests were added) |
| Independent data (DRIVE-C, no tuning) | not tested | day scenes: **78/210 (37%)** of our fault classes caught at onset (motion blur and strong under-exposure transfer; defocus 0/50); **night scenes false-alarm on darkness** (3/3) |
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

What it changes in the claims:
- **Night is out of scope today.** The absolute darkness fallback (mean brightness below 35, meant for a camera that starts broken) fires on normal night driving. It was never exercised on our daytime Oxford drive.
- **"Blur" means whole-frame blur.** Partial, depth-dependent defocus is missed.
- On independent daytime footage, motion blur and strong under-exposure transfer; glare transfers partly; subtle faults do not.

Evidence: `docs/evidence/aws/drivec.json` (per clip and per cell).

## 7. Deployment, operations and other changes

| | Before | After | Evidence |
|---|---|---|---|
| Public site (Lambda, arm64, OpenCV 5.0.0) | Old detector: the sky made glare fire constantly; History held Mac-measured runs | New detector + verifier + footage gate; History seeded from the **AWS-measured** database; QA round 4: no constant sky-glare alarm on a live replay; QA round 6: verifier reports "DNN engine: new" | QA rounds 4 and 6 |
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

## Pending (this file will be updated)

- [x] Fresh held-out, three arms, on Graviton
- [x] Paced fresh held-out, verifier off vs rule, on Graviton
- [x] OpenCV 4.13 vs 5.0 on Graviton: DNN timing and per-stage profile
- [x] Lambda redeployed with the verifier, model, footage upload and final history; QA round 6 passed on the live site
- [x] Recommendation 2: S3 → Lambda footage gate, alarm-delay curves in `verify_eval`
- [x] Recommendation 2: DRIVE-C evaluation (independent dataset), on Graviton
- [x] Alarm-delay curves (2 s / 10 s / 60 s), fresh held-out (`docs/evidence/delay-curves-fresh.json`; OpenCV 5.0 on Mac, whose none/rule arms matched Graviton exactly)
- [ ] Recommendation 3 (COOL): standard vs COOL on the same Graviton host, when the account is ready
