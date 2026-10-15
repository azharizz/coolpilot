# COOLPilot research and implementation plan

> Historical tracking-era research, superseded by the camera-only cutover. Commands and tracking results below are archival, not the current application contract. Use `README.md` and `IMPROVEMENT_PLAN.md`. Original datasets, old verification artifacts and the `video/` presentation remain preserved as historical material.

Date: 2026-09-19. Source brief: `../RESEARCH_AGENT_RESPONSE.MD`.

**Goal:** Build a working local browser application that uses a real Nebius agent to optimize one OpenCV tracking workload, measures every experiment, and refuses configurations that violate user quality constraints.

**Execution:** Solo in this directory. No subagents. Implement and verify in this session. The user's direct instructions override the planning skill's delegation and approval ceremony.

**Architecture:** React browser client, a small FastAPI coordinator, SQLite experiment history, and isolated Python benchmark processes. Native ARM64 Docker runs the complete application. There is no Docker socket, arbitrary command execution, fabricated dataset, canned agent decision, or cloud deployment claim.

## Research and decisions

### Two approaches considered

1. **Selected by the user:** Browser application with a real annotated tracking sequence, live experiment history, visual inspection, and a Nebius tool loop.
2. **Alternative:** CLI/API benchmark runner only. Smaller surface, but less useful for inspecting visual regressions. Keep a CLI entry point for reproducibility, not a separate product.

### OpenAI model guidance

Read the [official latest-model guide](https://developers.openai.com/api/docs/guides/latest-model). Apply its guidance on explicit success criteria, autonomous follow-through, scoped verification, and transparent limitations. The implementation uses the user's configured Nebius model. Reading documentation cannot change this coding session's selected model or reasoning setting. OpenAI-specific request parameters must not be copied onto a different provider without compatibility evidence.

### COOL and ARM reality

[OpenCV describes COOL](https://opencv.org/cool/) as its optimized distribution for Graviton and ARM computer vision workloads. The [published Graviton 5 package](https://aws.amazon.com/marketplace/pp/prodview-igdweaoo6prb6) uses OpenCV 5.1.0, KleidiCV 0.7.0, and a custom hardware acceleration layer. That package requires Graviton 5 hardware and verifies Marketplace entitlement through EC2 metadata. Its Python environments live under `/opt/cool/venvs/`.

**Consequence:** Apple ARM Docker is not equivalent to Graviton and does not satisfy that package's documented hardware or entitlement requirements. Run real vanilla OpenCV locally. Record build information and machine architecture. Show COOL as unavailable here. Do not rename KleidiCV or a pip wheel as COOL. The same benchmark CLI can be executed with the licensed COOL Python interpreter on AWS later; comparable reports require the same dataset hash, configurations, repetitions, and hardware. Do not bypass licensing.

[OpenCV's HAL documentation](https://docs.opencv.org/doc/doxygen/html/da/d8e/api_hal.html) explains dispatch to vendor kernels. Stage timing is necessary because improvements to image preprocessing need not accelerate optical flow or geometric estimation. [Docker's platform guide](https://docs.docker.com/build/building/multi-platform/) distinguishes architecture selection from hardware performance. Build and verify `linux/arm64` natively.

### Actual workload and evidence

Use the public [CTU/LinTrack mouse-pad sequence](https://cmp.felk.cvut.cz/cmp/demos/Tracking/linTrack/data/index.html), recorded at 100 fps, with manually annotated four-corner ground truth. Cite K. Zimmermann, J. Matas, and T. Svoboda, *Tracking by an Optimal Sequence of Linear Predictors*, IEEE TPAMI 31(4), 2009. Download original frames and annotations, retain archive SHA-256 values and a manifest, and never generate evaluation truth from the tracker. The original MATLAB-style row/column coordinates are converted to zero-based x/y coordinates.

The pipeline uses resize, grayscale, Gaussian blur, Shi-Tomasi features, pyramidal Lucas-Kanade flow, and RANSAC homography. [OpenCV optical-flow documentation](https://docs.opencv.org/4.x/d4/dee/tutorial_optical_flow.html) provides the tracking primitives. [Homography documentation](https://docs.opencv.org/4.x/d1/de0/tutorial_py_feature_homography.html) defines the geometric fit and inlier mask. Only the initial polygon of each clip reaches the tracker. Subsequent ground truth belongs exclusively to the evaluator.

### Real agent behavior

[Nebius function-calling documentation](https://docs.tokenfactory.nebius.com/ai-models-inference/function-calling) specifies the OpenAI-compatible conversation and tool-result protocol. Load `NEBIUS_MODEL`, `NEBIUS_API_KEY`, and `NEBIUS_BASE_URL` from `.env`. The authenticated model catalog was checked successfully. The configured model is `nvidia/Nemotron-3_5-Lightning`.

The model receives measured baseline results, quality constraints, hardware facts, and parameter bounds. It can run experiments and finish with an evidence-based summary. Real measurements are returned as tool messages. Invalid arguments are tool errors, not silently replaced with a preset. Provider failures stop the run visibly; they never activate a rule-based optimizer. A separately named seeded random-search mode supplies a coarse comparison baseline with a recorded finite search set. The quality gate is deterministic because it enforces the user's contract, not because it chooses experiments.

## Product contract

- One real planar tracking dataset and one workload, with native ARM64 execution.
- Tunable resolution, feature count, frame stride, OpenCV threads, worker replicas, and optical-flow pyramid depth.
- Separate tuning and held-out clips. Freeze all search decisions before held-out evaluation. A failed held-out result is not recommended.
- Score every source frame, including held predictions on skipped frames. Exclude initialization from quality and latency statistics. Failed tracks incur the frame diagonal as error; they cannot disappear from aggregates.
- Tracking success means polygon IoU at least 0.5. Report mean corner error in original-image pixels and hard failures. Evaluate requested minimum success, maximum corner error, and maximum processed-frame p95 latency.
- Per-stage timings, source-frame throughput, processed-frame p95, CPU time, and aggregate worker peak RSS. Report full per-repetition results. Worker replicas are concurrent independent streams of the same clip, not frame-parallel temporal tracking.
- Warm up separately. Run candidates sequentially so they do not compete with one another. Keep all experiments, invalid results, dataset hashes, build details, model usage, and tool decisions in durable storage.
- Objective: maximize throughput locally. Only compute cost per video-hour when the user supplies the actual total hourly host price; label it an estimate and exclude unprovided storage/network/inference charges.
- A recommendation must have passed held-out checks. Applying it updates the local workload's active configuration. Rollback restores a previously applied configuration; this is not EC2 deployment.
- No arbitrary workloads, uploads, S3, AWS provisioning, instance search, billing API, memory-bandwidth counters, ROI restructuring, or multi-tenant authentication in this version. These need separate real integrations and evidence. Bind the service to loopback only.
- No imposed model or benchmark timeout. Users can cancel a run; cancellation terminates its subprocess group. HTTP clients disable library-default timeouts. Budget candidates and model turns explicitly to bound spending, not elapsed time.
- React state and event handlers, with a small external store for polling via `useSyncExternalStore`; no `useEffect` or DOM mutation.
- No em dashes in authored copy. Secrets remain outside Git, build context, client bundles, exports, and logs.

## File and delivery plan

| Files | Responsibility | Verifiable deliverable |
| --- | --- | --- |
| `coolpilot/dataset.py`, `coolpilot/tracking.py` | Original dataset preparation, tracking, source-pixel quality | Downloaded manifest and measured real baseline |
| `coolpilot/benchmark.py`, `coolpilot/models.py` | Isolated repeated experiments, metrics, schemas, gates, frontier | Runnable benchmark JSON and integrity checks |
| `coolpilot/store.py`, `coolpilot/agent.py`, `coolpilot/api.py` | Persistence, provider/tool loop, job lifecycle, promotion | Live agent run, cancellation, restart recovery, API contract checks |
| `web/src/*`, `web/package.json` | Operable React UI and actual tracking overlays | Build, browser workflow, keyboard and responsive inspection |
| `Dockerfile`, `compose.yaml`, lockfiles | Reproducible non-root ARM64 runtime | Healthy local Docker application |
| `tests/test_core.py`, `scripts/verify_live.py` | Small runnable checks at measurement/security boundaries | Unit/API tests and real provider end-to-end verification |
| `README.md`, `PRODUCT.md`, `DESIGN.md` | Operating instructions and product/design truth | Reproducible start, evidence, honest migration boundary |

## Implementation sequence

- [x] Download original data and verify frame/annotation alignment; retain hashes.
- [x] Implement and run actual tracking, measurements, and quality checks.
- [x] Implement durable experiment lifecycle and the Nebius tool loop.
- [x] Build the React UI around real results and empty/error states.
- [x] Build/start Docker ARM64 and run a real agent search plus random comparison.
- [x] Verify rejection, held-out evaluation, apply/rollback, cancellation, restart persistence, and secret isolation.
- [x] Inspect desktop/mobile UI, apply the available Impeccable catalog and detector, and record results.
- [x] Save exact outcomes and limitations below, with commands for reproduction.

## Acceptance commands

```sh
docker compose build
docker compose up -d --wait
docker compose exec app python -m unittest discover -s tests -v
docker compose exec app python scripts/verify_live.py
curl --fail http://127.0.0.1:8769/api/health
```

The live verifier calls the configured provider and incurs inference usage. No cloud resources will be created. Performance on this shared laptop is observational, not an AWS production certification.

## Verification record

Completed the selected local scope on 2026-09-19. The original brief's AWS/COOL integration remains outside this local implementation because no entitled Graviton runtime was available. All code is under the requested `project_testing` directory. Work was solo.

### Runtime and data

- Healthy app: `http://127.0.0.1:8769`, Docker service `coolpilot-app-1`, native `linux/arm64`, Python 3.12, OpenCV 5.0.0, 8 available CPUs, UID 10001.
- 6,946 original aligned frames/annotations. Dataset SHA-256: `e182b24bc9478308d1c9597b667aaeea3f33f793708f0cffc41a649a4c8ee322`.
- Final runner source SHA-256: `14d045f9e44e02b0da6cf6c598d9e1ffab3d946fc7ca7e48d5ae7a576a66d25c`.
- No host price was supplied, so cost remains unknown. No COOL, AWS or cloud savings were fabricated.

### Real measured outcomes

Both searches used 4 candidate experiments, 300 frames per clip, 3 measured repetitions, success at least 95%, mean corner error at most 4 px and processed-frame p95 at most 40 ms.

| Search / experiment | Clip | Source fps | p95 ms | Error px | Success | Decision |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Nebius reference #25 | Tuning | 42.829 | 29.658 | 2.056 | 100% | Pass |
| Nebius fastest passing candidate #28 | Tuning | 141.318 | 37.903 | 3.200 | 100% | Validate |
| Same candidate #31 | Held-out | 150.702 | 33.944 | 7.614 | 100% | Reject |
| Nebius reference check #30 | Held-out | 44.324 | 27.762 | 2.761 | 100% | Reference retained |
| Random reference #38 | Held-out | 45.332 | 26.418 | 2.761 | 100% | Pass |
| Random selected candidate #39 | Held-out | 70.972 | 15.625 | 2.743 | 100% | Validated and applied |

The random candidate uses width 640, 100 features, stride 1, one worker, one thread, and pyramid level 2. It achieved about 56.6% more throughput than its held-out reference in this run. A 1203.6 aggregate-fps random candidate was rejected for 5.36 px tuning error. Speed cannot bypass the quality contract.

The agent did **not** beat the comparator in this observed session. This is not a statistical study: random search uses a finite subset, the model chooses from full schema bounds, and the laptop is shared hardware. Agent evidence predates final prompt/metadata edits, so the cross-strategy result is descriptive, not a controlled source-identical comparison. Both modes genuinely execute the same tracking algorithm; results are not scripted to make the model win.

### Verification receipts

- Python: 8 contract tests passed, including geometry penalties, threshold rejection, pending Pareto rows, provider argument schema, HTTP boundaries, failure recovery, promotion/rollback and restart state. `verification/unit-tests.log`.
- TypeScript compilation and production Vite build passed in the final Docker image. Python Ruff checks passed. Frontend dependency audit: 0 reported vulnerabilities. `verification/compose-build.log`, `verification/python-lint.log`, `verification/npm-audit.json`.
- Real Nebius tool loop and HTTP verifier passed: run `99a35088bdf44a0d899e197badbf2d8a`. It verified unvalidated-apply rejection, real candidate execution, held-out evaluation, apply/rollback, complete evidence export, key absence and cancellation. `data/live-verification.json` and `verification/agent-evidence.json`.
- Browser-created random run: `8d147b5ae21d468b9d3d06c5b10baacc`. Original result in `verification/random-evidence.json` and SQLite.
- Real SIGKILL/recreate test: `e215e7f3477f4912bcf9056f7ae64e65` became interrupted. Previous completed run and active experiment survived. `verification/restart-check.json`.
- Browser apply #39, rollback to #30, reapply #39 and Run active workload succeeded. Actual execution `3c406af84feb40f98560fddf3bf7640c` used 100 features and pyramid level 2 and passed both clips. `verification/active-workload.json`.
- Secret scans found no API key in source, client bundle or experiment artifacts. `.env` is mode 0600, excluded from Git and Docker context, and absent inside the image filesystem. Benchmarks receive no Nebius environment variables.
- Browser: real run submission, saved-run selection, frame scrubbing, overlay toggles, exact small-limit display, apply/rollback, runtime facts, dataset fingerprint, keyboard chart selection and horizontal ledger scrolling checked. No application console errors observed. Temporary API disconnections during intentional restart are expected.
- Impeccable: 67-pattern catalog reviewed; automated detector returned `[]`. Solo final disposition: **ship** for the selected operating UI. Captures: `.impeccable/review/desktop.png`, `mobile.png`, `desktop-inspector.png`, `mobile-inspector.png`, `mobile-form.png`. Full-page capture stitching was malformed, so it was replaced with verified viewport captures. Representative text contrast ratios: primary action 5.47:1, secondary body text 5.34:1, main text 12.90:1. The mobile table intentionally scrolls horizontally inside a keyboard-focusable region.

### Findings fixed during verification

The configured provider stringified an early nested tool configuration. Flattening the published schema enabled real tool execution; the historical unsuccessful run remains labelled failed. Pending experiments initially caused a frontier API error; the shared frontier now excludes records without a gate. Benchmark barriers now prevent quality evaluation from competing with another worker's timed interval. SQLite connections close explicitly, failed jobs release the run slot, and rollback follows actual application history. UI limits no longer round tiny values to zero. The ledger is keyboard-scrollable and chart point buttons are exposed as an accessible group.

One model summary misstated clip length and recommended production before validation. The measured gate correctly rejected that candidate. Public model text is retained as commentary, labelled fallible; the prompt now requests concise prose and distinguishes measured length from dataset capacity. There is no claim that prompting makes model prose infallible.

### Remaining platform limits

Licensed COOL versus vanilla on the same Graviton hardware, S3, EC2 provisioning, AWS pricing, infrastructure search, encoded-video ingest, arbitrary workloads, multi-operator access and broad dataset generalization remain unimplemented. The README documents the real vendor-interpreter migration route and its prerequisites. This delivery is a tested single-operator local application, not certification of an AWS production deployment.

Docker requires a deadline for health probes; the sole added timeout is `COOLPILOT_HEALTHCHECK_TIMEOUT=120s` in `.env`. It allows a stuck probe to be replaced and does not terminate inference or benchmarks. No model/benchmark timeout was added.

## Desktop UX revision, 2026-09-20

The earlier verification receipts above are historical and do not certify this revision. The new desktop implementation replaces the rail and long stacked ledger with one-click optimization, optional setup, a result-first layout, reusable run requests, stable run URLs and paginated history/experiments/reasoning. It follows the user's OpenCV visual reference with locally served Poppins and a custom RGB COOLPilot mark.

The ARM Docker production build passes TypeScript compilation and Vite bundling. The container is running on loopback port 8769. Desktop screenshots were inspected using existing evidence. Unit, integration and live benchmark tests were deliberately not run for this revision, following the user's instruction. A runnable history pagination and API-boundary test was added to the existing suite for the later test phase.

See [revision scope and screenshots](UX_REVAMP.md). The supported workload remains annotated CTU planar tracking; arbitrary workload uploads and AWS execution are outside this desktop revision. New backend source changes also change the runner-source hash attached to future benchmarks, so the historical source hash above must not be presented as the current revision's hash.
