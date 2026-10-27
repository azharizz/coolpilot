# COOLPilot developer reference

**Submission docs:** [Technical report](TECHNICAL_REPORT.md) (architecture diagram, results, limits) · [Agent workflow and traces](AGENT_WORKFLOW.md) · [COOL on Graviton](COOL.md) · [Before/after record](BEFORE_AFTER.md) · [Evaluation](EVALUATION.md)

A local **camera-health workbench for ADAS research**: replay three recorded views, inspect delivery and image-quality evidence, and evaluate bounded OpenCV configurations. Optional Decisions image review is advisory. This is not a validated road-safety system and cannot control a vehicle.

## Run

```sh
docker compose up -d --build --wait
```

Open [COOLPilot](http://127.0.0.1:8769). For a new checkout, copy `.env.example` to `.env` and restrict it with `chmod 600 .env`. Local replay needs no provider credentials. Configure Nebius only for agent search; optional Decisions uses separate server-side credentials and explicit image-upload consent. Never commit secrets.

Startup no longer downloads the CTU tracking dataset. Supply the Oxford recordings or register your own camera dataset as described below. On Linux, create `data` with ownership matching container UID 10001. Restart after environment changes with `docker compose up -d --force-recreate --wait`.

Both app and API bind to loopback port 8769; container port 8000 is private. Change `COOLPILOT_PORT` if needed. Do not expose this single-user service without authentication, TLS and an appropriate access boundary.

## Use

1. **Overview** shows the three recorded forward views, links to replay and validation, and reports the actual COOL runtime status.
2. **Compare cameras** streams local measurements at recorded pace. Choose reference for untouched video or an explicitly labelled synthetic fault. Pipeline health and image suspicions are separate; neither authorizes driving.
3. **Validate cameras** freezes a dataset, gates and thresholds before baseline, seeded random or optional agent search. Development-only fixtures cannot authorize apply.
4. **History** retains camera experiments, failed gates, traces and exports. **Edit setup** reuses camera settings. Apply/rollback changes only the workbench configuration, never physical cameras.

Mouse-pad tracking, its optimizer, CTU preparation and tracking-only API/UI are removed. Historical database rows and original files remain on disk as archived evidence but are excluded from camera history and cannot be applied. No user recordings were deleted.

## Measurement contract

Local OpenCV measurements cover regional detail, intensity, clipping and repeated imagery; delivery monitoring covers stale, unavailable and backlogged evidence. These are unvalidated heuristics, not obstacle detection or a causal diagnosis. Full timing, scoring, configuration and limitations are documented in the camera-health contract below.

Agent and random search use the same finite camera configuration space. Selection minimizes included cost when all candidate prices are known, otherwise CPU seconds per camera-second, subject to every declared gate. Independent held-out validation governs promotion; the supplied single-session development fixture cannot produce a recommendation.

## Architecture and boundaries

```text
React browser → FastAPI coordinator → Nebius chat/completions
                       ↑                   ↓ actual tool calls
                 SQLite evidence ← isolated benchmark process
                                            ↓
                                 OpenCV worker stream replicas
```

One Uvicorn worker owns active tasks. SQLite WAL and a unique active-run constraint prevent overlapping benchmark jobs. Do not increase API workers or replicas with this coordinator. A shared job coordinator becomes necessary only when multiple independent operators or hosts are required.

The model can submit bounded configuration values and finish a search. It cannot execute shell commands, edit code or choose arbitrary data paths. Provider or tool failures remain visible; there is no canned fallback optimizer. A failed measurement does not overwrite earlier evidence. Cancel terminates the benchmark process group. On service restart, unfinished jobs become `interrupted` and preserve completed results. They are not silently retried or billed again.

Nebius receives the workload configuration, user limits, dataset metadata, hardware/build facts and aggregate measurements. Images, raw ground-truth traces and the API key are not included in the model prompt. The key is used only in the server-side authorization header and is removed from benchmark child environments. Public hypotheses and tool calls are stored; hidden reasoning fields are not.

The container runs as UID 10001 with read-only root, a `/tmp` tmpfs, dropped capabilities, no-new-privileges and no Docker socket. `.env`, results, caches and documentation are excluded from the build context. Browser mutations require a matching Origin when one is supplied; Host checking and a same-origin CSP constrain the local browser surface.

There is no model/benchmark elapsed-time timeout or implicit retry. The candidate budget is at most 30 and the model-turn ceiling is `2 × budget + 4`; each completion is limited to 8192 output tokens. Cancellation is explicit. Docker's health probe alone has a 120-second timeout, configured by `COOLPILOT_HEALTHCHECK_TIMEOUT` in `.env`, because Docker needs to terminate a stuck probe and schedule its replacement. The two-second browser refresh is a polling interval, not an execution timeout.

## Operations and checks

```sh
docker compose ps
curl --fail http://127.0.0.1:8769/api/health
docker compose logs --tail=50 app
docker compose exec -T app python -m unittest discover -s tests -v
```

Health confirms API/database availability, not dataset validity or safe imagery. Against an idle service with the supplied videos:

```sh
docker compose exec -T app python scripts/verify_live.py
```

This verifies actual three-camera original-footage streaming, split health channels and frame accounting. It makes no paid requests and does not apply configurations or add history rows. Output is a JSON receipt on stdout.

Reproduce a camera experiment with its saved request and configuration:

```sh
docker compose exec -T app python -m coolpilot.simulation.camera_benchmark \
  --request /app/data/runs/RUN_ID/request.json \
  --config /app/data/runs/RUN_ID/EXPERIMENT_ID-config.json --split tuning
```

Use real recorded identifiers. Runtime evidence includes OpenCV build identity, dataset fingerprint, architecture and a recursive `coolpilot/**/*.py` source hash. Older records predate this contract; do not compare unlike versions as controlled evidence.

`data/coolpilot.sqlite3` owns camera history and applied configuration; `data/runs/` holds artifacts. `data/oxford_robotcar/` and registered camera datasets hold recordings. Retired tracking files are archival only. For a consistent backup, stop the service and copy the entire data directory; keep `.env` separately in secret storage. No automatic pruning discards evidence.

```sh
docker compose stop
# Copy data/ to your chosen backup destination while the service is stopped.
docker compose up -d --wait
```

If a run fails, inspect its UI error first. Benchmark stderr is retained in `data/runs/<run>/<experiment>-error.log`. Correct the dependency, dataset or provider issue and start a new run. A failed archive hash is an integrity failure; do not substitute a new expected hash without verifying the publisher source. Treat extracted dataset files as immutable; the manifest is reused on restart, not rehashed on every read.

## COOL and Graviton migration

Two deployment approaches have different evidence requirements:

1. **Native ARM Docker, implemented here:** package and execute the workload on ARM. Re-run on a target Graviton host to measure that host. ARM compatibility alone predicts neither performance nor cost.
2. **Licensed COOL on supported Graviton:** use the vendor-supported Marketplace image and its supplied Python environment. Check the current [OpenCV COOL requirements](https://opencv.org/cloud/) and Marketplace entitlement. A newer ordinary OpenCV wheel is not COOL; macOS ARM64 is not an entitled AWS Graviton runtime.

Transfer the same package, verified dataset, request and configuration to that host. Use the vendor interpreter that imports its supplied `cv2`; preserve its NumPy ABI and do not install the standard OpenCV wheel over it. Install the remaining compatible app dependencies and run the same `python -m coolpilot.simulation.camera_benchmark` command. Repeat with ordinary OpenCV in a separate environment on the same host. Match source/data hashes, configurations and repetitions; retain both build reports and output differences. The `/opt/cool/` Linux ARM64 detection is a runtime-location hint, not license validation or proof of acceleration.

The web app does not provision EC2, accept Marketplace terms, upload to S3, discover prices or deploy a cloud fleet. These are explicit remaining integrations, not simulated buttons. The evaluation runs in [docs/EVALUATION.md](EVALUATION.md) were measured on EC2 t4g.small (Graviton2) with standard OpenCV 5.0.0. No licensed COOL environment has been used yet; [docs/COOL.md](COOL.md) is the migration guide and evidence checklist. Operator scripts in [deploy/aws](deploy/aws/README.md) launch a self-terminating Graviton instance and deploy this app over SSH; they were exercised on a stock Ubuntu Graviton2 host with ordinary OpenCV 5.0.0, not on COOL. `deploy/aws/lambda` deploys a read-only serverless edition (UI, live replay, history) to Lambda on Graviton with ordinary OpenCV 5.0.0, also not COOL.

## Camera-health development videos

**Validate cameras** opens the camera experiment workbench. Retired tracking records are preserved on disk, not shown in the active app. The supplied Oxford fixture remains development-only, with no independent held-out recommendation or apply.

Oxford RobotCar source frames are under `data/oxford_robotcar/`. Its `videos/` directory holds the original colour stereo conversions. `data/oxford_robotcar/camera_health_development/` holds a matched centre reference plus six synthetic variants: blur, underexposure, localized glare, camera-fixed translucent obstruction, blackout, and frozen image content. Each is 1280x960 with 271 frames over approximately 19.06 seconds. Edits are scheduled for 4-10 seconds; original imagery resumes afterward. Source timestamps, including existing gaps, are preserved. Raw images and original stereo videos are untouched.

Each MP4 has an evaluator-only JSON recipe/event timeline, source and output hashes, per-frame edit records, and development-session ownership. `manifest.json` groups the fixture; `preview.jpg` shows before/during/after frames; `verification.json` reports edit and recovery checks, not detector performance. Do not send these labels or the inspection sheet to an inference model.

Requires Python with OpenCV/NumPy plus `ffmpeg` and `ffprobe` on PATH. Run from the repository root:

```sh
python3 scripts/generate_camera_health_variants.py --self-check
python3 scripts/generate_camera_health_variants.py \
  --output data/oxford_robotcar/camera_health_development_rerender
```

The generator refuses an existing output directory. It uses temporary lossless colour PNGs, so allow about 1 GB of temporary working space plus final videos. Encoder/runtime identity is recorded; byte-identical outputs across different encoder builds are not promised.

This is one development session, not independent tuning/held-out evidence. No physical-fault realism, broad detector accuracy, repair, live freshness, agent advantage or cloud savings is established. Timed interruption/backlog scenarios are supported by the replay code but were not exercised in the recorded browser run. Retain Oxford RobotCar attribution and applicable noncommercial/ShareAlike terms; local generation does not establish public or commercial distribution permission. See [camera-health improvement plan](IMPROVEMENT_PLAN.md) for remaining evaluation work.

## Held-out cameras (`oxford-camera-holdout`)

To check that calibration generalises, the same drive's other cameras get randomized faults: stereo left and right (GBRG Bayer) and mono rear (RGGB). Each clip draws its own onset, a 2-6 s duration, a strength of 0.7-1.3x and, for glare and obstruction, a position, all from a fixed seed and all recorded in the sidecar. The centre clips become the **tuning** split; the other cameras are the **validation** split. This is a camera-held-out split **within one recorded drive**, not an independent drive, and the manifest says so.

```sh
python3 scripts/generate_camera_health_variants.py --camera stereo/left  --split validation --seed 101 --output data/camera_health_build/left
python3 scripts/generate_camera_health_variants.py --camera stereo/right --split validation --seed 202 --output data/camera_health_build/right
python3 scripts/generate_camera_health_variants.py --camera mono_rear    --split validation --seed 303 --output data/camera_health_build/rear
python3 scripts/build_holdout_dataset.py                       # hard-links tuning + validation, verifies hashes
python3 -m experiments.calibrate --out calib.json             # sweep detector thresholds on development/tuning clips only
python3 -m experiments.calibrate --dataset oxford-camera-holdout --split validation --defaults   # frozen defaults on held-out
```

`experiments/calibrate.py` refuses to sweep the validation split.

Independent clips: `experiments/drivec_fetch.py` pulls selected DRIVE-C clips (CC BY 4.0, doi:10.5281/zenodo.19656444) from the 9 GB zip using HTTP range requests, and `experiments/drivec_eval.py` scores them with the frozen defaults on DRIVE-C's own dev/test split. For local testing, `scripts/generate_drivec_sample.py` turns DRIVE-C clean clips in `data/drivec_sample/original/` into `drivec-sample`: each original (hard-linked) plus six randomized faults. Clips under 10 s get 1–2 s faults after a 1.3 s warm-up. Results, including what still fails, are in [docs/EVALUATION.md](EVALUATION.md).

### Joint tuning, self-calibration and the diagnostic autopilot

```bash
python -m experiments.joint_calibrate --drivec ~/drivec/drivec_core_v1 --detail-width 640 --ignore-oxford-clip centre_obstruction \
    --cache ~/cache.pkl --grid grid.json --out round.json      # Oxford tuning + DRIVE-C dev only; validation splits are never read
python -m experiments.autopilot --cache ~/cache.pkl --arm tools --budget 16 --out autopilot.json   # needs NEBIUS_* in the environment
python -m experiments.autopilot --approve autopilot.json      # a human approves before a proposal is validated or applied
python3 scripts/build_holdout_dataset.py --name oxford-camera-holdout-fresh3 --validation data/camera_health_build_fresh3/*   # new never-inspected seeds
```

- `joint_calibrate` sweeps the detector on Oxford tuning clips plus DRIVE-C dev scenes.
- `autopilot` gives an LLM agent OpenCV-measured diagnostic tools:
  - `evaluate`: scores a setting on the tuning data
  - `explain_failure`: a per-frame rule trace
  - `paired_compare`: a fault clip against the same clean frames
  - `ablate`: varies one setting at a time
  - `propose`: writes a proposal that waits for human approval

  The script also runs an `evaluate`-only arm and seeded random search at the same budget.
- **Shipped from this work:**
  - detail measured at 640 px (defocus becomes visible)
  - obstruction must hold for 1.2 s
  - the night policy (`dark_at_start_alarm` off: a camera dark since its first frame is its own normal, with "verify" shown in footage reports)
- **Built and tested but not shipped:** self-calibrating limits (`adaptive_k`, off). They tied the defaults on never-inspected Oxford clips.
- **The autopilot did not beat random search.** Its best proposal on tuning data failed unbiased validation, and the approval gate kept it out.
- Full record: [docs/BEFORE_AFTER.md](BEFORE_AFTER.md) section 6b–6c and `docs/evidence/{tuning,autopilot}/`.
- Agent workflow diagram and step-by-step traces (verifier and autopilot): [docs/AGENT_WORKFLOW.md](AGENT_WORKFLOW.md).

## Second-stage verification (active perception, OpenCV 5 DNN)

The always-on monitor is cheap and only says "these tiles lost detail while the rest of the view kept it". That is also what open sky, a featureless surface or a passing vehicle look like. So an **obstruction suspicion never alarms on its own**: the last second of frames goes to `coolpilot/verify.py`, which measures the scene causes on that moment only:

- `texture`: was the tile ever detailed, and does it show open sky now (upper half, bright, unsaturated)?
- `objects`: road users covering the tiles, from **NanoDet-Plus (OpenCV model zoo, Apache-2.0) on OpenCV 5's new DNN graph engine** (`coolpilot/objects.py`; outputs are paired by shape because the new engine orders them differently from the classic one)
- `motion`: optical flow in the tiles against the rest of the view, as reviewer context

Three arms are measured on the same suspicions (`experiments/verify_eval.py`): `none`, `rule` (fixed thresholds over the tools; the default) and `agent`. In the `agent` arm the Nebius model calls the same tools, then must **confirm, dismiss or escalate to a human**, citing measurements (`coolpilot/verify_agent.py`).

Guardrails:
- It cannot decide before measuring.
- Any provider or tool error, or an exhausted turn budget, keeps the alarm.
- A dismissed real fault counts as a miss.

The live replay shows each verdict, its reason, the tools used and the latency. Escalations get operator buttons, which are browser-only on the read-only deployment. `CameraSettings.verifier` and `COOLPILOT_VERIFIER` select the mode. Benchmark subprocesses never receive the Nebius keys, so measured runs use `rule`. Limits were fixed on the tuning clips before any held-out evaluation; results are in [docs/EVALUATION.md](EVALUATION.md).

To get the model: download `object_detection_nanodet_2022nov.onnx` and its `LICENSE` from https://huggingface.co/opencv/object_detection_nanodet into `data/models/`. Without it, the `objects` tool reports itself unavailable and the rule decides on texture alone.

## Check footage (camera-data quality gate)

**Check footage** screens one short recording (at most 50 MB and 60 s) for camera-side problems: black, frozen, blurred, dark, glare, and verified obstruction. It returns segments with a thumbnail and reason for each, plus JSON/CSV downloads. The intended use is screening recorded fleet or robot video before labelling, training or incident review.

- **On AWS:**
  1. The browser posts the file straight to a private S3 prefix through a 5-minute presigned POST. The bucket allows browser uploads from the site's own origin only (CORS).
  2. The Graviton Lambda (OpenCV 5.0.0) downloads it, analyses every frame once, and **deletes it from S3 and `/tmp` whether or not the analysis succeeds**.
  3. A 1-day lifecycle rule removes anything left over, uploads are rate-limited per minute, and a `footage` EMF metric records duration and processing time.
- **Locally:** the same flow uses a capped `PUT` to `data/uploads/`, deleted after analysis.

The screen uses rules calibrated on one Oxford drive plus DRIVE-C dev scenes. Night footage is treated as the camera's normal: footage that is dark from its first frame is not raised as a fault, and the report says "dark since the first frame, verify". So a camera that is dark from power-on is not flagged. Rain and real lens dirt are unvalidated, and a report is never a safety judgement.

## Live camera (monitor only, untested on real hardware)

`COOLPILOT_LIVE_SOURCES="dashcam=rtsp://host/stream,usb=0"` lets the server analyse operator-configured OpenCV `VideoCapture` sources. Clients choose a name and never a URL, so a public endpoint cannot be made to fetch arbitrary addresses. `POST /api/live/analyze` (at most 120 s; refused on the read-only deployment) streams pipeline and image health with wall-clock timing, reconnecting with backoff. The Live replay page shows a "Live camera" panel only when sources are configured. With no labels there is no recall or false-alarm score. Only file-backed tests exist (`tests/test_live.py`).

## Metrics

With `COOLPILOT_METRICS=1` (set on Lambda), each finished replay, live session and experiment prints one CloudWatch Embedded Metric Format line in namespace `COOLPilot`. `deploy/aws/lambda/deploy.sh` creates a `coolpilot` dashboard from them, alongside Lambda duration and errors.

## Camera-health workbench contract

Use **Validate cameras**, select a registered dataset, review the proposed gates, then run baseline, seeded random search or the existing Nebius agent. No image requests are enabled by default. The supplied Oxford session is development-only: no recommendation or apply is allowed, even if its gates pass.

- `camera_dataset.py` locks the manifest, sidecars and MP4 hashes and rejects sessions/source hashes spanning tuning and validation. Register additional local sets in `data/camera_health/<id>/manifest.json`, using schema version 1 and the Oxford artifact/sidecar structure. Each artifact names its MP4, annotation JSON and SHA-256. Each sidecar supplies `split`, `split_group`, `session_id`, `camera`, `source_frames_sha256`, increasing `relative_frame_timestamps_us`, and events with `type`, `provenance`, `first_affected_pts_us`, `first_recovered_pts_us`. Use `tuning` and `validation` only for genuinely independent sessions. Physical annotations use `human_labelled_physical`; retain rights and severity metadata.
- `camera_health.py` measures a 4×4 region grid, intensity, detail, clipping and repeated imagery, with persistence/recovery. Obstruction and freeze are suspicions, not causal diagnoses. Defaults in `CameraThresholds` are development calibration, not validated safety limits. Threshold overrides are frozen before a run.
- `simulation/camera_benchmark.py` replays original timestamps with bounded drop-oldest queues. Separate delivery timers continue during image analysis and model calls. Optional per-clip delivery interruptions and processing-delay windows test different failure paths. A processing-delay window is a load injection, not automatically ground truth for backlog: freshness gates evaluate measured age.
- Local visual alarms remain active in local, scheduled-review, and hybrid modes. Remote outputs are advisory only and cannot establish or clear local alarms. Freshness uses the source PTS, not analysis completion time; stale results cannot establish visual persistence/recovery. Unknown intervals reset pending visual evidence, and the configured unknown-fraction gate is enforced. Observation `arrival_age_s` is arrival-to-result; `source_age_s` includes source-schedule lateness. Older run exports predate these corrections and must not be treated as revalidated evidence.
- `camera_health.assess_health` separates `pipeline_status` (delivery/processing) from `quality_status` (`suspected`, `no_issue_detected`, or `unknown`) in streamed frames and transitions, replacing the ambiguous aggregate `status`/`conditions`. Pipeline healthy is not usable imagery or driving safety. Stale/unavailable evidence makes image quality unknown while retaining last visual suspicions. The shared core accepts no simulation labels. This fixes classification semantics, not detector accuracy: sky/scene changes can still trigger glare/obstruction; thresholds and benchmark penalties remain unchanged. Verified with 17 focused checks, a direct-frame core smoke without simulation imports, and frontend build.
- The comparison dashboard presents separate **Pipeline** and **Image** panels with live sampled status timelines. Green means on-time processing or no visual flag—not safety; red means an alarm/suspicion, stripes mean unknown, and future time is blank. Three selectable metric charts per camera cover 19 delivery, timing and image measurements with shared camera scales, gap-aware lines and hover values. Freshness/source-cadence guides are references, not safety limits. Regional brightness/detail/clipping uses 4×4 heatmaps; optional Decisions scores use advisory meters. Event tables remain collapsed. Backend detection is unchanged. Verification covered all 19 chart selections, empty/scrubbed history, zero-wait values, regional percentages and a 390 px layout without overflow; TypeScript/Vite build passed. One automated browser stream ended with a network error at 30 seconds after drawing the footage; an independent server stream completed in 19.51 seconds. No paid review was exercised.
- Remote review uses fixed replay-clock slots starting at zero. Scheduled mode counts every slot; hybrid mode counts slots with fresh local suspicions. Busy, missing-evidence, budget-exhausted and unserviced end-of-replay slots remain uncovered, not successful reviews. Only `attempted: true` records contribute to API attempt/failure and charge accounting. At most one review is outstanding per stream. Results collected after replay ends are unavailable; their probabilities are removed and reported charges retained.
- Evidence-handling revision: `visual_observations` describes measured patterns separately from suspected causes. Regional reference decay uses elapsed source time (`reference_decay_s`, default 71.4 s), not frame count. `review_result` retains history/cost; `review_current` expires at `source PTS + min(feed_timeout_s, backlog_s)`, and stale arrivals do not count as covered reviews. The UI hides expired probabilities, including between recorded samples. These changes reuse the installed `cv2`; they do not install or establish licensed COOL execution.
- Isolated candidates and commands live in [experiments/README.md](experiments/README.md): sparse flow, regional persistence, fixed EMA, explicit spatial weighting, optional BRISQUE and a session-split OpenCV SVM. No candidate is imported by the application. This revision passed 35 Python tests, final frontend build, synthetic CLI execution/model reload checks and a fixture-backed rendered advisory-expiry check. Real provider, supplied-video application and licensed-COOL integration remain manual; no road-safety accuracy claim.
- The existing HTTPX dependency uses asynchronous I/O internally with one cancellation deadline covering connection, headers, body streaming and the single 404 retry. Encoding time is deducted from the remaining request budget. Replay cleanup can still wait for the outstanding request's remaining budget; this is not a hard-real-time guarantee. Frame accounting reconciles `expected_frames = processed + skipped + dropped + interrupted_frames + rejected_frames + unfinished_frames`; unfinished includes source frames not yet delivered or still decoding, not just queue contents.
- All comparisons preserve dataset, source timing, scenarios, thresholds, stream count, gates and repetitions. Agent and random search share the finite camera configuration space. Selection prefers included cost when all candidate prices are known; otherwise CPU seconds per camera-second. Selection freezes before validation. Apply/rollback are workload-scoped and reject changed dataset or runtime identity.
- Scoring uses exact-class, one-to-one alarm onset inside the labelled interval. Early and duplicate alarms remain false alarms; missed events and premature/uncleared recovery remain failures. Export retains every stream/repetition, event provenance/severity, local observations, model probabilities, queue/coverage measurements and denominator. A short zero-alarm clip is not reliable hourly-rate evidence.
- Concurrent replicas measure only the selected stream count, not maximum or heterogeneous fleet capacity. Source arrival lateness is separate from arrival-to-result age; neither establishes capture-to-result latency. Cost includes declared host/software prices and reported image charges, excluding storage, network, optimizer charges and operator time. Missing costs remain unknown. Optimizer token usage is exported separately.

### Three-camera comparison

Simulation is isolated under `coolpilot/simulation/`: `camera_comparison.py` owns recorded sources and random schedules, `camera_effects.py` owns synthetic pixel edits, and `camera_benchmark.py` owns paced replay, artificial delivery/work delays and experiment execution. The web API and fixture generator import this package; benchmark subprocesses use `python -m coolpilot.simulation.camera_benchmark`. Old module paths were removed, not kept as compatibility shims.

The reusable core remains `coolpilot/camera_health.py`: `analyze(frame, width)`, `Monitor.appearance(measurements, time_s)` and `Monitor.update(conditions, time_s, evidence)` have no simulation dependency. A future real-data adapter can supply decoded BGR frames and comparable timestamps directly, without synthetic preprocessing. Real capture, input validation, timestamp synchronization, freshness orchestration and failure containment still require a dedicated adapter and target validation; moving files does not implement or certify an ADAS runtime.

**Compare cameras** uses the supplied left, centre and right Oxford stereo recordings: overlapping forward-facing views, not front/side/rear ADAS coverage. **Start local three-camera replay** runs them concurrently at recorded PTS pace with a shared monotonic epoch. Preflight reads only container metadata; pixels decode one frame ahead per source during replay, then undergo preprocessing before the bounded analysis queue. No full-video decode/hash or browser video preload occurs. PTS are validated incrementally per camera, not prevalidated for cross-camera synchronization. No physical camera or ingest API is used.

Default **random** mode now selects **one fault per camera per replay**, from the same 12 classes: blur, underexposure, glare, obstruction, blackout, freeze, interruption, jitter, decode failure, timestamp fault, processing delay and resolution stress. On the supplied ~19-second clips, each fault lasts 2–3 seconds, leaving approximately 84–89% of each feed uninjected, with at least two clean seconds before/after. Cameras can overlap. The numeric seed repeats the schedule; **New seed** changes it. Reference adds no fault; a named selection injects that fault once. Short clips cap event duration to preserve clean intervals. Schedule version is now **2**; a seed from version 1 does not reproduce version 2. All 12 classes remain available, but a single default run no longer exercises all of them. Original files remain untouched.

Visual effects reuse the development generator's recipes, scaled to each window. Interruption suppresses delivery; jitter delays it by seeded 0–250 ms; mocked decode failure and negative timestamps reject input without killing the source. These are input-boundary simulations, not corrupted-bitstream or clock-drift validation. Processing delay injects a 700 ms worker wait, reported separately from compute. Resolution stress doubles initial analyzer resize/color-conversion width (4× pixels at that stage); the quality grid remains 320×240 and source/decoder resolution is unchanged. Neither synthetic waits nor visual degradation establish COOL slowdown or speedup.

Labels never enter quality analysis or model prompts. JPEG previews show the actual analyzed pixels with PTS, report time, freshness, alarm state, regional measurements, processing pace, dropped/interrupted/rejected counts and decode/worker/compute/edit timings. Report-time and displayed-frame injections are labelled separately when evidence lags. A slow client receives the latest sample rather than blocking analysis; preview updates are capped near 10 Hz. Display omissions are not analyzer drops.

The slider/playback controls replay received historical samples, not current camera health. Fault schedules and local alarm onset/clearance remain visible without hiding misses or unrelated alarms. Final JSON includes seed/schedule/version, per-frame injection receipts, rejected-input reasons, observations, reviews, runtime and frame accounting. Scheduled or producer-received faults may be dropped before analysis; do not count them as detections. Preview history is browser-session-only. Source provenance records allowlisted path identity and size/mtime checked after replay, not content hashes; do not treat this demo export as a locked evaluation manifest.

Scheduled and local-suspicion review modes require explicit image-upload consent. Each camera has one outstanding review and a bounded per-run attempt budget. Pending, busy, stale, missing, budget-exhausted and failed reviews remain visible; final tables include late results and reported charges. Single-frame model scores cannot establish freeze or delivery loss and never clear local alarms. The request deadline covers encoding plus HTTP connection, headers, body and one optional 404 retry; cancellation stops replay but coordinator release waits for outstanding work to exit. Another run is rejected until then.

Metadata preflight is outside the measured interval. Wall/process CPU include synthetic edits, previews, API-process activity and review cleanup; worker latency includes artificial waits while `compute_ms` excludes them. Replay duration uses container frame count/FPS plus one cadence to cover the last PTS; invalid timing metadata or out-of-range/non-increasing decoded PTS fail explicitly. `source_seconds` and `replay_seconds` remain separate. This paced demo is not a maximum-capacity or isolated COOL benchmark. See [research and fault limitations](IMPROVEMENT_PLAN.md#research-applied-to-this-revision) for OpenCV/AWS and NHTSA references.

Historical original-only replay (before streaming/fault controls): 271/271 frames per view, zero dropped/unfinished frames, 19.13 s wall / 9.54 s process CPU on local arm64 OpenCV. Analysis p95 was left 4.68 ms, centre 4.32 ms, right 4.36 ms; maximum source-evidence age was 0.151 / 0.154 / 0.155 s. All three ended degraded with glare/obstruction suspicions. These unvalidated heuristics can react to ordinary scene content. Those numbers and older screenshots do not verify the new streaming revision.

Optional image review uses server-side `AGENT_PROVIDER_API_KEY` and `AGENT_PROVIDER_MODEL=openai/gpt-6-luna-decisions`. The adapter sends only to OpenAI through `https://openrouter.ai/api/alpha/decisions`, with `data_collection: "allow"`, `zdr: false`, and no fallback. A first HTTP 404 is retried once after 250 ms within the original timeout; other statuses are not retried. Final provider error detail is capped at 512 characters. The exact user-provided text-only request returned HTTP 200; repeating it with the same provider preferences also returned HTTP 200. The original image HTTP 404 body was discarded before this bounded error reporting was added. An authorized same-frame retry using `centre_reference.mp4` requested at 4.0 s returned HTTP 200; OpenCV decoded PTS 4.187 s. A fresh run through the retry-enabled code also returned HTTP 200, in one request after 2.94 s, so the live retry branch was not exercised. Both successful image responses produced `blackout: 0`, `blur: 0.43`, `glare: 0.66`, `obstruction: 0.06`, and `underexposure: 0.05`; the fresh response used 1,540 input tokens, 0 output tokens, and cost $0.000154. The retry branch is covered by a unit test for 404 then 200, and a separate assertion confirms HTTP 400 is not retried. These are advisory appearance scores from one source scene, not detector-accuracy evidence. Non-ZDR routes may permit upstream retention or use; these request settings do not themselves enable training.

On host source runs, `api.py` loads the repository-root `.env` first, then fills only missing `AGENT_PROVIDER_API_KEY` and `AGENT_PROVIDER_MODEL` values from the parent-directory `.env`. Docker Compose passes the repository-root `.env` as environment variables; the parent file is not copied into the image or passed to the container. Set optional variables in the repository-root `.env` or container environment. Never commit credentials.

Open a completed camera run for rejected gates, per-fault results, recorded playback, regional measurements, annotations and full JSON export. Playback is recorded evidence, not live status. **Runtime** links the active camera configuration to its validated run; camera apply does not control hardware.

### Verification boundary

Latest sparse-simulation/package-separation revision: **15 isolated checks passed** (`python3.11 -m unittest discover -s tests -p test_camera_stream.py -v`, `-p test_camera.py -v`, plus `test_camera_health.py -k fake_io` and `-k cancelled_replay`). Schedule checks verify one event per non-reference camera, 2–3 second duration, clean boundaries, repeatability, short-clip behavior and class coverage across seeds. Existing checks cover incremental pacing, rejected inputs, waits, accounting, consent and review deadlines. Generator `--self-check`, the relocated benchmark CLI `--help`, and TypeScript/Vite build passed.

A direct-frame core smoke detected blackout without importing `coolpilot.simulation`. A separate temporary three-source synthetic MP4 replay exercised real decoding, threads, effects, analysis and JPEGs after relocation. Seed 42 scheduled processing delay at 3.215–5.247 s, underexposure at 9.686–11.919 s and blur at 10.906–13.468 s. Each stream decoded 190 frames; processed left/centre/right: 173/190/190; dropped: 17/0/0; no rejected, interrupted or unfinished frames. Wall time was 19.104 s and process CPU 1.256 s. These are synthetic pipeline observations, not supplied-video results, accuracy or COOL evidence. Temporary files were removed; no provider calls were made. The earlier dense-schedule smoke exercised all 12 classes but is historical, not evidence of current default frequency.

Supplied-video replay and paid-provider integration remain for the user's manual test. The loopback dashboard is redeployed after this change; it retains seed controls, local-only defaults and consent-gated paid review, without preloading video elements.

Manual check: open `http://127.0.0.1:8769/#/camera-comparison`, reload, keep all three scenarios on **Randomized fault mix**, record the seed, then start local replay. Watch the per-camera schedule, edited frames, source PTS, freshness, rejections, queue/drops, separate compute/injected-wait timing and alarm/recovery timeline. Scrub and download evidence afterward; repeat the same seed for schedule reproducibility, or choose **New seed** for different timing. Host execution timing is not deterministic. Set all cameras to reference for a no-injection counterexample. Do not assume injected faults will be correctly classified. For remote integration, choose scheduled or suspicion review, bound requests, and authorize uploads only if acceptable. Exercise pending/error states, stop/restart, stale updates and final coverage/charges. No licensed COOL target is configured on this host.

Previous revision verification (not rerun after the latest fixes): `python3.11 -m unittest discover -s tests -v` (**21 passed**; one upstream Starlette deprecation warning); frontend: `cd web && npm run build` (TypeScript and Vite passed). Actual three-video browser replays verified selected timestamps and all 813 analyzed frames; overlapping requests returned 409 while source requests remained responsive. Negative, out-of-range, null and non-finite sample times returned 422. A controlled delivery interruption exercised healthy → unknown → unavailable → recovery → healthy. Regression checks covered scheduled-review blackout detection without a provider, delayed analysis remaining unknown, unknown-fraction rejection, and malformed provider output remaining unavailable.
The baseline-only browser replay on run #53 exercised seven development clips over 133.8567 camera-seconds, one repetition and one stream. It failed its configured gates: underexposure, glare and obstruction were missed; blur was not cleared; blackout and freeze were detected and cleared; false alarms measured 1,221.7052/hour over 97.2411 normal seconds. Measured p95 was 2.4929 ms, CPU was 0.15086 s/camera-second, peak RSS was 179.66 MB, and maximum scheduled-source-to-result age was 0.16569 s. These same-session synthetic results verify the local pipeline and evidence UI, not detector accuracy or capacity.
Historical browser evidence: [`camera-health-run-53.png`](verification/camera-health-run-53.png), [`camera-health-blackout-53.png`](verification/camera-health-blackout-53.png), [`camera-comparison-local-results.png`](verification/camera-comparison-local-results.png), and [`camera-comparison-end-boundary.png`](verification/camera-comparison-end-boundary.png). Run #53 and the provider checks above predate the current corrections. No new footage was uploaded or paid model call made for this revision; current live-provider behavior remains unverified. The Luna outputs above are single-scene advisory scores, not independently validated visual-usability judgments. No independent recordings, physical faults, sustained capacity, AWS deployment, or licensed COOL execution has been verified. No cloud provisioning was performed.


## Dataset attribution

- **Oxford RobotCar Dataset** (sample): W. Maddern, G. Pascoe, C. Linegar and P. Newman, *1 Year, 1000 km: The Oxford RobotCar Dataset*, IJRR 36(1), 2017. Licensed CC BY-NC-SA 4.0 (non-commercial, share-alike). Raw Bayer frames are demosaiced and given synthetic faults by `scripts/generate_camera_health_variants.py`. The faults are ours, not the dataset's.
- **DRIVE-C core v1**: Shiva Aher, Georgia Institute of Technology, doi:10.5281/zenodo.19656444, CC BY 4.0. Used unmodified for independent evaluation, plus a small local sample with our synthetic faults (`scripts/generate_drivec_sample.py`).
- **NanoDet-Plus** (`object_detection_nanodet_2022nov.onnx`): from the OpenCV model zoo, Apache-2.0, licence file in `data/models/`.
- **Videos in `video/`**: the screen recordings show COOLPilot running on AWS. The road imagery in them comes from the datasets above, and is credited on screen.

## Desktop redesign

The OpenCV-inspired interface uses self-hosted Poppins and a custom COOLPilot RGB mark. See the verification boundary above for current versus historical checks, and [desktop revision scope and review](UX_REVAMP.md). AWS and COOL execution remain unverified.
