# COOLPilot

A local experiment workbench for planar tracking, camera-feed health, and camera-view comparison. A real Nebius model proposes bounded configurations, sees actual measurements, and chooses the next experiment. Quality gates reject regressions; held-out recommendations require human apply.

Camera health adds timestamped local replay, OpenCV measurements, event scoring and workload-scoped promotion. **Compare cameras** provides per-camera synthetic faults, streamed analyzed-frame previews and local measurements, optional bounded Decisions review, and recorded evidence playback. This is an engineering workbench, not a validated ADAS monitor. Verification scope is recorded below; local results are not proof of AWS or COOL acceleration.

## Run

```sh
docker compose up -d --build --wait
```

Open [COOLPilot](http://127.0.0.1:8769). The existing `.env` supplies the three Nebius settings. For a new checkout, copy `.env.example` to `.env`, fill in your own credentials and model, and restrict it with `chmod 600 .env`. Never commit it. Restart with `docker compose up -d --force-recreate --wait` after changing environment settings.

The first start downloads about 185 MB of original publisher archives, verifies pinned SHA-256 values, extracts 6,946 frames and annotations, and records a dataset manifest. The interface shows preparation and enables runs when ready. Existing data is reused. Allow roughly 1 GB for data and experiment artifacts plus Docker images. On a Linux host, create `data` with ownership matching container UID 10001 before starting; Docker Desktop on this Mac handles the bind mount.

Both app and API are bound to `127.0.0.1`, port 8769. Port 8000 inside the container is private. Change `COOLPILOT_PORT` in `.env` if needed. Do not publish this single-user service to a network without adding authentication, TLS and an appropriate access boundary.

## Use

1. Open **Optimize** and click **Optimize tracking**. No setup is required. **Customize run** exposes quality limits, budget, search method and the reference configuration. Agent mode uses your configured Nebius account.
2. The run opens with live status, then its validation outcome and a before/after comparison on the same held-out clip. **Result** shows source images and tracking quality; **Experiments** and **Agent notes** hold the supporting detail.
3. **Apply configuration** persists the validated recommendation. **Runtime → Run active workload** executes that configuration. **Roll back** restores the preceding application. This controls the local benchmark runner, not EC2 or a camera service.
4. **History** supports name search, status filters and eight-row pages. Open a saved run, use **Run again** to reuse its complete request, or **Edit setup** to prefill the optional controls. Run URLs are bookmarkable.
5. **Export evidence** downloads the full measured record: repetitions, polygons, ground truth, decisions, token usage, dataset hashes and build facts. All completed evidence, including rejected experiments, remains available.

**Baseline only** runs the reference and held-out check without the model. **Random-search comparison** samples a documented finite parameter set with a recorded seed. It is explicitly separate from the agent. Random mode samples widths 240/320/480/640, features 100/300/600/1000, strides 1/2/3, threads 1/2/4, workers 1/2/4 and pyramid levels 2/3/4. The agent has the full published schema bounds. Equal budgets, frames, repetitions and gates support a coarse comparison; this different search space and a single search cannot establish general agent superiority.

## Measurement contract

The tracker executes JPEG decode, resize, grayscale, Gaussian blur, Shi-Tomasi feature extraction, pyramidal Lucas-Kanade flow and RANSAC homography. Features are reseeded inside the predicted polygon. Only the initial ground-truth polygon is supplied to tracking. There is no ground-truth correction after initialization and no hidden recovery that resets a lost track.

| Measurement | Definition |
| --- | --- |
| Source throughput | All source frames covered across concurrent independent stream replicas, divided by measured wall time. Includes initialization and decode of processed JPEGs. Excludes warm-up, quality evaluation, process startup and artifact writes. |
| Processed-frame p95 | Pooled wall-clock latency across all processed, non-initial frames and repetitions. Skipped frames do not dilute it. |
| Success | Fraction of all non-initial source frames with predicted polygon IoU at least 0.5. Lowest value across worker replicas and repetitions. |
| Corner error | Mean corresponding four-corner distance in original 640 × 480 pixels. Highest mean across replicas and repetitions. Missing predictions incur the 800 px image diagonal; errors are capped at that diagonal. |
| Frame stride | Intervening frames hold the last polygon and are still scored. Processing fewer JPEGs saves decode time; an encoded video decoder may still need intervening frames. |
| CPU | Worker process CPU seconds divided by measured wall time and available logical CPUs. Coordinator overhead is excluded. |
| Memory | Sum of worker peak RSS values, an upper bound rather than simultaneous resident memory. Coordinator memory is excluded. |
| Stage profiles | Mean measured milliseconds per processed frame. Small Python overhead outside the named stages is included in latency but not attributed to a stage. |
| Cost | Supplied total host USD/hour × 100 source fps ÷ aggregate measured throughput. No estimate is shown without a host price. Storage, transfer and model fees are excluded. |

Each worker warms up on 20 frames, resets tracking, then measures 1 to 10 repetitions. Workers rendezvous before and after each timed interval so quality evaluation does not contend with tracking. Experiments are serialized. OpenCV uses the requested thread count; OpenCL is disabled and its RNG seed is fixed for reproducibility.

Tuning starts at sequence index 0; held-out validation starts at 3473. Each clip is 30 to 1000 frames, default 300. This is a validation split within one sequence, not proof of generalization to other objects, cameras or production video. Laptop thermal state, other processes and Docker VM resources affect timing. Four streams at 200 aggregate fps do not mean one stream tracks at 200 fps.

The frontier contains non-dominated tuning configurations that pass every gate, using throughput, error and p95. Final selection maximizes measured throughput subject to the explicit gates. With a fixed supplied host price, that also minimizes the reported host cost. The user must still choose to apply a recommendation. Model summaries describe tuning evidence; held-out measurements govern promotion.

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

Health confirms the API/database; its `dataset` field separately reports `preparing`, `ready` or `failed`. Wait for `ready` before the live verifier. In a separate terminal after the complete build:

```sh
docker compose exec -T app python scripts/verify_live.py
```

This executes real baseline and Nebius experiments, strict rejection, export secret checks, apply/rollback and cancellation. It consumes inference credits and adds named verification runs to history. The report is `data/live-verification.json`. Do not run it while another run is active. Unit tests use isolated temporary databases and synthetic geometric fixtures only to test contracts; those fixtures never populate the app.

Portable benchmark reproduction using an exported experiment's configuration file:

```sh
docker compose exec -T app python -m coolpilot.benchmark \
  --config /app/data/runs/RUN_ID/EXPERIMENT_ID-config.json \
  --split tuning --frames 300 --repetitions 3
```

Replace the identifiers with a real recorded run. The output includes OpenCV build identity, runner-source SHA-256, dataset fingerprint, architecture and raw measurements. The source hash covers `coolpilot/*.py`. Earlier development measurements predate this field. Never compare unlike source or dataset versions as a controlled experiment.

`data/coolpilot.sqlite3` owns run history and applied configuration. `data/runs/` contains configuration/result/error artifacts; `data/mouse_pad/` and `data/downloads/` contain the source dataset. For a simple consistent backup, stop the app, copy the entire `data` directory, then start it again. Keep `.env` separately in your secret storage. Restore the whole directory while stopped. No automatic pruning discards evidence.

```sh
docker compose stop
# Copy data/ to your chosen backup destination while the service is stopped.
docker compose up -d --wait
```

If a run fails, inspect its UI error first. Benchmark stderr is retained in `data/runs/<run>/<experiment>-error.log`. Correct the dependency, dataset or provider issue and start a new run. A failed archive hash is an integrity failure; do not substitute a new expected hash without verifying the publisher source. Treat extracted dataset files as immutable; the manifest is reused on restart, not rehashed on every read.

## COOL and Graviton migration

Two deployment approaches have different evidence requirements:

1. **Native ARM Docker, implemented here:** package and execute the workload on ARM. Re-run on a target Graviton host to measure that host. ARM compatibility alone predicts neither performance nor cost.
2. **Licensed COOL on matching Graviton, future execution:** use the vendor's supported Marketplace image and Python environment. The currently researched Graviton 5 offering checks EC2 entitlement and is not a distributable local pip substitute. It must be benchmarked on actual licensed hardware.

For the second approach, transfer the same `coolpilot` package, verified dataset and configuration to the entitled machine. Confirm the vendor interpreter imports its supplied `cv2`, preserve that package and NumPy ABI, and install the compatible Pydantic dependency without replacing the vendor OpenCV build. Then run the same `python -m coolpilot.benchmark` command with the vendor interpreter. Repeat with vanilla OpenCV in a separate environment on the same instance. Match source/data hashes, frame counts, configurations and repetitions; retain both full build reports and differences. COOL and vanilla may bundle different OpenCV versions, so the measured delta reflects the distributions, not proof of one kernel's contribution.

The web app does not provision EC2, accept Marketplace terms, upload to S3, discover prices or deploy a cloud fleet. These are explicit remaining integrations, not simulated buttons. No AWS account access or licensed COOL environment was supplied or used.

## Camera-health development videos

The Camera health navigation opens the replay workbench. Existing tracking records remain readable. The local UI and recorded-evidence playback were verified; the supplied Oxford fixture remains development-only, with no independent held-out recommendation or apply.

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

## Camera-health workbench contract

Use **Camera health**, select a registered dataset, review the proposed gates, then run baseline, seeded random search or the existing Nebius agent. No image requests are enabled by default. The supplied Oxford session is development-only: no recommendation or apply is allowed, even if its gates pass.

- `camera_dataset.py` locks the manifest, sidecars and MP4 hashes and rejects sessions/source hashes spanning tuning and validation. Register additional local sets in `data/camera_health/<id>/manifest.json`, using schema version 1 and the Oxford artifact/sidecar structure. Each artifact names its MP4, annotation JSON and SHA-256. Each sidecar supplies `split`, `split_group`, `session_id`, `camera`, `source_frames_sha256`, increasing `relative_frame_timestamps_us`, and events with `type`, `provenance`, `first_affected_pts_us`, `first_recovered_pts_us`. Use `tuning` and `validation` only for genuinely independent sessions. Physical annotations use `human_labelled_physical`; retain rights and severity metadata.
- `camera_health.py` measures a 4×4 region grid, intensity, detail, clipping and repeated imagery, with persistence/recovery. Obstruction and freeze are suspicions, not causal diagnoses. Defaults in `CameraThresholds` are development calibration, not validated safety limits. Threshold overrides are frozen before a run.
- `simulation/camera_benchmark.py` replays original timestamps with bounded drop-oldest queues. Separate delivery timers continue during image analysis and model calls. Optional per-clip delivery interruptions and processing-delay windows test different failure paths. A processing-delay window is a load injection, not automatically ground truth for backlog: freshness gates evaluate measured age.
- Local visual alarms remain active in local, scheduled-review, and hybrid modes. Remote outputs are advisory only and cannot establish or clear local alarms. Freshness uses the source PTS, not analysis completion time; stale results cannot establish visual persistence/recovery. Unknown intervals reset pending visual evidence, and the configured unknown-fraction gate is enforced. Observation `arrival_age_s` is arrival-to-result; `source_age_s` includes source-schedule lateness. Older run exports predate these corrections and must not be treated as revalidated evidence.
- `camera_health.assess_health` separates `pipeline_status` (delivery/processing) from `quality_status` (`suspected`, `no_issue_detected`, or `unknown`) in streamed frames and transitions, replacing the ambiguous aggregate `status`/`conditions`. Pipeline healthy is not usable imagery or driving safety. Stale/unavailable evidence makes image quality unknown while retaining last visual suspicions. The shared core accepts no simulation labels. This fixes classification semantics, not detector accuracy: sky/scene changes can still trigger glare/obstruction; thresholds and benchmark penalties remain unchanged. Verified with 17 focused checks, a direct-frame core smoke without simulation imports, and frontend build.
- The comparison dashboard presents separate **Pipeline** and **Image** panels with live sampled status timelines. Green means on-time processing or no visual flag—not safety; red means an alarm/suspicion, stripes mean unknown, and future time is blank. Three selectable metric charts per camera cover 19 delivery, timing and image measurements with shared camera scales, gap-aware lines and hover values. Freshness/source-cadence guides are references, not safety limits. Regional brightness/detail/clipping uses 4×4 heatmaps; optional Decisions scores use advisory meters. Event tables remain collapsed. Backend detection is unchanged. Verification covered all 19 chart selections, empty/scrubbed history, zero-wait values, regional percentages and a 390 px layout without overflow; TypeScript/Vite build passed. One automated browser stream ended with a network error at 30 seconds after drawing the footage; an independent server stream completed in 19.51 seconds. No paid review was exercised.
- Remote review uses fixed replay-clock slots starting at zero. Scheduled mode counts every slot; hybrid mode counts slots with fresh local suspicions. Busy, missing-evidence, budget-exhausted and unserviced end-of-replay slots remain uncovered, not successful reviews. Only `attempted: true` records contribute to API attempt/failure and charge accounting. At most one review is outstanding per stream. Results collected after replay ends are unavailable; their probabilities are removed and reported charges retained.
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

Original [CTU/LinTrack tracking dataset](https://cmp.felk.cvut.cz/cmp/demos/Tracking/linTrack/data/index.html): K. Zimmermann, J. Matas and T. Svoboda, *Tracking by an Optimal Sequence of Linear Predictors*, IEEE TPAMI 31(4), 2009. The manifest records the original download URLs and archive hashes. The app downloads from the publisher instead of bundling their imagery into the image. Public download availability is not a claim of an unrestricted redistribution license; retain attribution and establish usage rights for any broader distribution.

## Desktop redesign

The OpenCV-inspired interface uses self-hosted Poppins and a custom COOLPilot RGB mark. See the verification boundary above for current versus historical checks, and [desktop revision scope and review](UX_REVAMP.md). AWS and COOL execution remain unverified.
