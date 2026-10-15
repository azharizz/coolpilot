# COOLPilot Improvement Plan: Real-Time Camera-Health Engineering

Status: development roadmap only. The current application is a local replay-driven workbench; it is not a live camera monitor, an ADAS component, or a safety system. This plan targets a camera-health monitor that could support future ADAS engineering. It does not authorize vehicle use or make a safety claim.

## 1. Goal and decision

Build and evaluate a camera-health monitor that reports whether camera evidence is fresh, usable, degraded, unavailable, or uncertain. Use timestamp-paced video first to develop repeatable timing and fault tests; later validate a live camera path on the actual target hardware. A video replay that runs at 1× wall-clock pace is a real-time software exercise, not proof of camera capture latency, vehicle readiness, or hard-real-time behavior.

The monitor is **observe-and-report only**. It must not command steering, braking, acceleration, exposure, cleaning, or other vehicle functions. A healthy status is not safety authorization; a degraded, unavailable, or unknown status must remain visible to downstream consumers. Any future actuation or safety-related integration requires a separate intended-use definition, hazard analysis, safety requirements, and approval by qualified automotive safety owners before implementation.

The immediate outcome is trustworthy evidence and a bounded engineering monitor—not a production recommendation. Do not claim ADAS suitability, safety integrity, certification, accident reduction, production readiness, or generalization beyond the tested cameras, conditions, and hardware.

### Implemented: camera-only application cutover

Removed the mouse-pad optimizer, tracker, CTU downloader, tracking API contracts and tracking-only screens. Shared runtime identity, dataset hashing, camera validation, SQLite evidence, history and guarded apply/rollback remain. Historical tracking rows and downloaded files are preserved but excluded from the camera application; old camera evidence remains readable. The homepage now presents the three supplied road recordings, camera validation and actual COOL availability. Mobile history scrolls inside its table container.

**Current verification:** 32 Python tests passed; TypeScript/Vite production build passed. The local live verifier replayed all three original views concurrently in 19.137 s with balanced frame accounting and zero remote reviews. Browser verification exercised the homepage, mobile layout, runtime screen, a real baseline submission and saved evidence playback with 16 measurement regions. Run `885e9f50754145b9988bd4d0361331be`, experiment #63, completed seven development clips: analysis p95 2.4 ms, maximum arrival-to-result age 0.167 s, zero dropped frames and zero image requests. Its quality gate correctly rejected the evidence: underexposure, glare and obstruction were missed, blur recovery unresolved, and false alarms were 1,331.9053/hour over 97.3042 normal seconds. Apply stayed disabled. This verifies execution and rejection, not safety or detector suitability.

**COOL prerequisite remains:** this host reports Darwin ARM64 and ordinary OpenCV 4.13.0. A newer standard OpenCV wheel cannot turn it into the licensed COOL distribution. No licensed supported AWS Graviton environment is available here, so `cool.available` remains false; no fabricated availability, acceleration or safety claim. Use the vendor runtime on its supported target and measure matched workloads before asserting an improvement. No paid provider requests or commits were made.

### Implemented: evidence handling and isolated experiments

Completed solo and left uncommitted. This section was planned before implementation and updated afterward. Completion here means the code and checks below—not completion of this entire roadmap, validated road-safety detection, or demonstrated COOL acceleration.

| Location | Implemented behavior | Boundary / remaining prerequisite |
| --- | --- | --- |
| Main monitor | Observation descriptions separate from suspected causes; elapsed-time regional reference decay with configurable `reference_decay_s` (default 71.4 s) | Existing debounce, freshness, bounded queues and local alarm authority retained. Decay approximates the old rate at 14 observations/s; lower/higher sampling rates now have consistent elapsed-time semantics. Detector accuracy remains unvalidated. |
| Main Decisions handling | Source-age validity using the tighter local freshness limit; exact-boundary expiry; stale arrivals excluded from review coverage; expired current probabilities hidden | Historical responses and charges retained. Recorded UI advice expires at the scrub cursor, including between samples. Advice cannot establish/clear local alarms. No paid provider call exercised. |
| Main runtime | Reuses installed `cv2` and existing runtime identity/optimizer path; no competing wheel, remote COOL endpoint or experimental dependency added | Default Docker/runtime remains ordinary OpenCV. A licensed compatible COOL interpreter on supported hardware is required for actual COOL execution. The existing `/opt/cool/` path label is not license verification. No acceleration claim made. |
| `experiments/camera_health.py` | Runnable baseline comparisons for sparse LK flow, fixed-coordinate regional persistence, elapsed-time fixed EMA, explicit spatial weights and real OpenCV BRISQUE | Offline isolated commands; no production imports, uploads or automatic promotion. Spatial weights must be supplied. BRISQUE needs `cv2.quality` plus model/range files; those were unavailable locally. |
| `experiments/feature_classifier.py` | Actual linear OpenCV SVM using existing image measurements; training-only normalization, session-disjoint evaluation, duplicate-image rejection, saved model/normalization and measured report | Representative human labels and independent sessions required. Synthetic smoke is execution evidence only. The three supplied views are one capture session, not independent train/test sets. |
| Restricted neural candidates | Prerequisites and license restrictions documented in `experiments/README.md`; fixed EMA provides a runnable smoothing control | Learned adaptive EMA, WoodScape/SDSM and TiledSoilingNet inference are not implemented: verified model assets, preprocessing, applicable permission and representative evaluation data remain missing. No fake models or unverified downloads supplied. |

**Exercised checks:** 35 Python tests passed (`python3 -m unittest discover -s tests -v`), including decay-rate invariance, timestamp validation, advice expiry/cost retention, flow ambiguity, persistence reset, EMA invariance, weight validation and classifier split/scaling behavior. Four candidate CLIs processed a temporary 12-frame moving-texture video. The classifier CLI trained on eight synthetic images, evaluated four and reproduced predictions after reloading its saved model and normalization. BRISQUE's unavailable-prerequisite failure was checked, not real scoring. Final TypeScript/Vite build passed. A fixture-backed rendered UI check confirmed three valid advisory meters at cursor 0.3 s and none at exact expiry 0.5 s, while retaining historical response/cost; no browser JavaScript errors.

**Redeployment correction:** the rebuilt frontend was served alongside an older running backend lacking `visual_observations`, causing the replay renderer to crash. The stream now rejects missing observation/advice fields with a visible restart/reload instruction before retaining the frame. Verified that the old backend produces that message without removing the three camera cards. Rebuilt the frontend and restarted the local backend using its Python 3.11 interpreter; an actual three-camera original-footage replay reached `Replay complete` with all three images visible and no UI alerts. Original footage still triggered highlight-clipping/regional-detail-loss suspicions; this was not an accuracy validation.

**Remaining manual integration:** real paid Decisions responses, licensed COOL output equivalence/performance, other replay scenarios and held-out road-footage evaluation. No real provider upload was performed. `experiments/README.md` contains commands, input contracts and promotion limitations. No adaptive neural smoothing, arbitrary road-importance weights, physical camera adapter, GStreamer migration or model quantization was added.

## 2. Current implementation and evidence

The application is under `coolpilot/`. Its React UI coordinates a FastAPI service, SQLite evidence store, isolated benchmark processes, local OpenCV analysis, and an optional experiment-planning agent. Camera-health experiments use finite configuration choices and workload-scoped apply/rollback. Applying a configuration changes the workbench's stored configuration; it does not configure a physical camera.

`coolpilot/simulation/camera_benchmark.py` incrementally decodes recorded MP4s and schedules frames against a monotonic host clock. Registered benchmark datasets retain locked timestamp manifests; the comparison dashboard reads container metadata only before starting and validates PTS while decoding. The bounded drop-oldest queue and separate delivery monitoring measure source-schedule evidence age, not sensor capture-to-alert latency. The analyzer and its thresholds are local development instrumentation, not validated safety limits. No live-camera source, trustworthy capture clock, vehicle interface, or hard-real-time execution boundary is implemented.

An earlier recorded camera-health result is experiment #53: baseline-only, one repetition, one stream, seven clips / 133.8567 camera-seconds from one development session. The gate failed: underexposure, glare, and obstruction were missed; blur was not cleared; false alarms were 1,221.7052/hour over 97.2411 normal seconds. Processing p95 was 2.4929 ms; maximum scheduled-source-to-result age was 0.16569 s. The camera-only cutover result above repeats this execution check, not independent validation. These synthetic, single-host results do not establish detector accuracy, real-time capacity, live timing, or safety.

The Oxford RobotCar fixture and its synthetic variants are development data from one session group. Timed interruption/backlog mechanisms exist in code, but are not established by the recorded browser run. Independent sessions, physical fault evidence, matched optimizer comparisons, sustained target-hardware capacity, live camera tests, and safety review are absent. AWS and licensed COOL execution are also unverified; neither is a substitute for testing the intended vehicle compute target.

The three-camera comparison reuses this replay for simultaneous left/centre/right streams with one shared epoch. It now decodes one frame ahead per source, preprocesses it, then passes the same edited pixels to the bounded analyzer/reviewer/preview path. It does not predecode or hash whole videos. File size/mtime and allowlisted path are recorded and checked; they are weaker provenance than a content hash. Individual PTS are checked during replay, not prevalidated for stereo synchronization. Original files remain unchanged.

Default **random** mode selects one of the 12 fault classes per camera, with a recorded seed and **schedule version 2**. Each event lasts 2–3 seconds on the supplied ~19-second clips (roughly 11–16% injected time), with at least two clean seconds before and after; short clips cap duration to preserve these boundaries. A named selection also injects once; reference adds no fault. All classes remain selectable, but one default run no longer covers all classes. Seeds are repeatable within a schedule version, not across the previous dense and current sparse algorithms. A scheduled event is not a successful detection, or proof it reached analysis: retain per-frame injection receipts, rejections, dropped and unfinished counts. Labels never enter quality inference or remote prompts.

| Injection | Implemented boundary and limits |
| --- | --- |
| Blur, underexposure, glare, obstruction, blackout, freeze | Shared synthetic pixel recipes, scaled to random windows before analysis. Freeze holds preceding source content while timestamps advance. These test quality; they do not inherently increase compute cost or reproduce sensor physics. |
| Interruption | Suppress delivery during the source-time window; independent freshness monitoring continues. |
| Jitter | Seeded per-frame 0–250 ms producer delay. This is local delivery delay, not a network model. |
| Decode failure | Replace decoded input with missing pixels, reject it, and continue. This does not exercise a corrupted codec bitstream. |
| Timestamp fault | Inject an invalid negative input timestamp, reject it, and continue. This does not cover drift, clock resets, or all reordering cases. |
| Processing delay | Artificial 700 ms worker wait, separately reported from actual analyzer compute. Tests queue/freshness behavior, not CPU saturation or COOL speed. |
| Resolution stress | Double analyzer resize/color-conversion width (4× pixels at that stage). The downstream quality grid remains calibrated at 320×240; source resolution and decoder workload do not change. |

The dashboard streams analyzed-frame JPEGs, PTS/freshness, local quality/performance measurements, report-time versus displayed-frame injections, alarm onset/recovery and bounded advisory reviews. Recorded scrubbing/export includes seed, schedule, runtime and trace evidence. Stop/disconnect requests cancellation; exclusivity remains until cleanup finishes. No ingest API, physical camera, online optimizer or vehicle control was added.

The provided videos are overlapping forward stereo views from one session, not surround-camera coverage. Historical original-only browser replay processed all 813 frames in 19.13 s wall time on local OpenCV; those results do not verify this revision. Current verification: 15 isolated checks, generator self-check, relocated CLI, frontend compilation, direct-frame core execution without simulation imports, and a temporary three-source synthetic replay with one scheduled fault per camera. Supplied-video and paid-provider integration remain for manual testing. See README for exact evidence and limitations.

Corrected contract violations include local alarm suppression in scheduled mode, stale-evidence freshness, persistence/recovery across unknown intervals, missed review-slot accounting, total HTTP deadline enforcement, unfinished-source accounting and the unknown-fraction gate. These changes support stages 1–2; independent data, physical-fault validation, target COOL execution and stages 0–5 exit approvals remain incomplete. Do not read this implementation update as completing the roadmap.

### Simulation versus reusable runtime code

Recorded-source replay, random scheduling, synthetic image recipes and artificial delays now live exclusively in `coolpilot/simulation/` (`camera_comparison.py`, `camera_effects.py`, `camera_benchmark.py`). Web routes, the experiment subprocess launcher, fixture generation and tests use the new paths; obsolete module paths are removed.

`coolpilot/camera_health.py` retains the source-independent `analyze` and `Monitor` implementation and does not import simulation. Natural decoded camera frames can enter those functions directly; ordinary measurement resizing/grayscale conversion remains, but synthetic edits do not. A future real ADAS source must bypass the simulation package and supply validated frames, timestamp semantics, independent freshness monitoring and failure handling. That adapter and target safety work are not implemented here. No speculative capture framework or vehicle interface was added.


## 3. System boundary and operating architecture

### In scope

- Local camera-feed condition and evidence reporting; recorded replay must be repeatable for a fixed manifest, configuration, and runtime.
- Independent feed-freshness monitoring that does not depend on image analysis or a remote service completing.
- Explicit `healthy`, `degraded`, `unavailable`, and `unknown` semantics, with evidence age and reason. “Healthy” must never be inferred from missing, stale, incomplete, or failed analysis.
- Replay-based timing, overload, queue, interruption, recovery, and counterexample evaluation.
- Offline configuration search against fixed data, resource limits, and quality gates; human review of any workbench configuration change.

### Out of scope until separately authorized

- Vehicle control, actuation, safety authorization, lane/obstacle/driver detection, or claims that a camera is safe to use.
- Treating image-model output as the local monitor, a ground-truth label, or a safety decision.
- Automatic online learning or configuration changes on a live vehicle.
- Public camera endpoints, fleet provisioning, cloud deployment, or production operation from the current single-user workbench.

### Proposed data path

`source → timestamp/arrival validation → bounded queue → local monitor → status + evidence + uncertainty`

Remote image review, if evaluated, is optional advisory evidence outside the freshness watchdog and local alarm path. The optimizer is an offline development tool, not part of the runtime monitor. Provider timeout, refusal, missing credentials, or invalid output must not make the feed healthy, clear a local alarm, or delay the local watchdog.

## 4. Real-time contract and measurements

Use distinct timestamps for source capture, host arrival, analysis start/end, and alert publication. Keep clock domains explicit and record synchronization quality. For replay, PTS defines the intended schedule and `perf_counter` measures host execution. Replay arrival time is not physical capture time. Report capture-to-alert latency only after a live source supplies a trustworthy capture timestamp that can be compared to the alert clock; otherwise report each measured segment and name what is excluded.

For every fixed workload and target hardware, measure:

- Declared source rate, frame interval distribution, arrival jitter, late/missing frames, and schedule adherence.
- Analysis time, queue wait, queue depth/age, dropped or skipped frames, alert publication delay, deadline misses, and stale/unknown duration.
- Event onset-to-alert and recovery delay, by event type/severity, with misses reported beside detected-event latency.
- Normal-scene false alarm episodes per camera-hour, evidence coverage, and unknown intervals with denominators.
- CPU, memory, thermal/load context, decode and analysis costs, external calls, and sustained stream capacity without growing backlog.

FPS and average processing time alone do not prove real-time behavior. Declare the workload rate, run duration, resource limits, timing budget, and required coverage before a comparison. Derive acceptable limits from the intended use and safety requirements; the current 1 s feed timeout, 0.5 s backlog threshold, and other defaults are development calibration only. Do not call this hard real time without target-specific worst-case timing, scheduling, resource isolation, and fault-containment evidence.

## 5. Data, fault scenarios, and evidence integrity

Use rights-cleared, privacy-reviewed recordings. Prefer non-sensitive, consented data. Split original capture sessions before deriving synthetic variants; keep every derivative of a source session in the same split. Lock manifests, source and artifact hashes, timestamp provenance, annotations, event-matching rules, and acceptance gates before final evaluation. Do not send ground-truth labels or injection recipes to the monitor or an image model.

Cover normal counterexamples and gradual, abrupt, intermittent, and persistent faults: blur, exposure loss, glare/clipping, partial obstruction, blackout, repeated/frozen content, feed interruption, decode failure, timestamp faults, queue overload, and recovery. Report synthetic, naturally occurring, and controlled physical evidence separately. Synthetic effects are useful controls but do not reproduce sensor physics or the full range of field conditions. Physical tests must be safe, controlled, and never conducted while driving.

The existing Oxford RobotCar development clips and synthetic edits remain useful for pipeline checks, not independent validation. Respect source-data rights and attribution; local availability does not establish permission for public or commercial redistribution. Do not broaden data collection without a documented privacy, consent, retention, and access plan.

## 6. Evaluation and gates

Freeze the intended use, workload, event definitions, matching windows, episode-collapsing rule, thresholds, data splits, and resource budget before final evaluation. Report at least:

| Measure | Required reporting |
| --- | --- |
| Event detection | Recall/miss rate by type and severity; unknown or unresolved labelled events count as misses for detection claims. |
| False alarms | Unmatched alarm episodes per camera-hour, with normal-scene duration and event counts. |
| Detection/recovery delay | Onset-to-first-qualifying alert and fault-end-to-correct-clear; report misses, premature clears, and uncleared events. |
| Freshness and availability | Capture-to-result only with comparable trusted clocks; otherwise arrival-to-result with upstream delay excluded. Include stale, unavailable, and unknown time. |
| Runtime behavior | Per-frame latency distribution, deadline misses, queue age/depth, drops, jitter, sustained capacity, and test duration. |
| Resources and cost | CPU, memory, thermal context, decode/analysis split, API use, and included/excluded cost assumptions. |

Set limits per fault class and timing objective; averages must not hide a missed critical event. Report sample counts, denominators, variability, and uncertainty. A short run with zero false alarms is not evidence of a low hourly rate. Preserve failed runs and all repetitions. No numeric limit is a safety limit until derived, approved, and validated for the defined intended use.

## 7. Optimization and remote review

Keep optimization offline. Compare the reference, seeded random search, and agent search on the same permitted configuration space, data, gates, resource budget, and repetitions. Preserve rejected candidates and their reasons. Freeze any selected candidate before untouched validation; recommend nothing if neither reference nor candidate passes. A faster configuration that violates a quality or freshness gate is rejected. Human apply/rollback remains a workbench operation and is not a live vehicle update.

Image-capable Decisions may be evaluated as optional, bounded advisory review against local-only and hybrid modes. Measure trigger coverage, end-to-end delay, misses, false alarms, failure behavior, and request cost on the same independent events. A single image cannot establish interruption, freeze, or capture latency. Provider responses are not calibrated safety guarantees. Review image privacy, permission, retention, timeout, and data-transfer policy before sending any footage.

## 8. Staged roadmap and exit criteria

| Stage | Work | Exit evidence |
| --- | --- | --- |
| 0 — Intended use and safety boundary | Name the camera, target compute, environment/ODD, users, output consumer, foreseeable misuse, hazards, and prohibited actions. Assign a safety owner and independent reviewer. Identify applicable functional-safety and intended-functionality processes before safety-related integration. | Approved monitor-only scope; hazard analysis and traceable requirements; defined timing/quality/resource limits and evidence plan. Do not begin live-source integration or call any limit safety-validated before this exit. |
| 1 — Replay contract | Lock independent development/tuning/validation sessions and event labels. Define clock semantics and a 1× paced-replay workload. Exercise interruption, timestamp/decode failure, overload, backlog, recovery, and normal counterexamples. | Reproducible runs show source schedule, timing, drops, queue behavior, and failure transitions; replay results are explicitly labeled simulation evidence. |
| 2 — Local monitor baseline | Verify and fix the existing local status transitions and independent freshness watchdog. Confirm failed or stale input yields unavailable/unknown, not healthy. Measure fault and normal performance under fixed gates. | Per-class event, false-alarm, timing, coverage, and resource results with failures retained; no remote model required for local status. |
| 3 — Independent and physical validation | Evaluate the frozen monitor on untouched capture sessions and safely controlled physical faults; assess camera, scene, lighting, motion, and fault-severity variation. | Independent review of representativeness, misses, false alarms, uncertainty, and limits; revise claims/data splits if validation informed changes. |
| 4 — Target live-source and runtime validation | Only after stages 0–3, integrate the named camera/driver on the intended target compute in a controlled non-driving setup. Validate timestamp provenance, disconnect/reconnect, resource contention, thermal behavior, worst-case timing, endurance, and failure containment. | Reproducible target-hardware evidence against approved requirements; explicit differences from replay; no vehicle-control connection. A live bench test alone is not road validation or safety approval. |
| 5 — Independent safety review | If the intended use becomes safety-related, complete the organization’s applicable lifecycle, safety case, verification, cybersecurity/privacy, and release approvals with qualified owners. | Formal authorization for the precisely defined use and environment. Until then, retain engineering-tool status and prohibit operational ADAS use. |

AWS/Graviton and licensed COOL are separate performance experiments, not safety milestones. Run them only if they are relevant to the chosen target; preserve runtime, hardware, dataset, and configuration provenance. A cloud result does not substitute for the target camera/compute validation above.

### Research applied to this revision

OpenCV describes COOL as **Cloud-Optimized OpenCV** for AWS Graviton, not an ADAS perception model. The publisher's AWS Marketplace listing describes a Graviton4 Arm64 Ubuntu 24.04 image, COOL 3.1/OpenCV 5.0, KleidiCV and parallelism. Vendor aggregate speedup claims are not guarantees for this workload or this local macOS build. Compare licensed COOL and a matched baseline on the same supported hardware, thread settings and inputs before making an acceleration claim; no licensing, cloud provisioning or target execution occurred here.

NHTSA's *Automated Driving Systems 2.0* discusses fallback and validation using simulation, track and road testing. Its *Framework for Automated Driving System Testable Cases and Scenarios* discusses software/hardware-in-the-loop and sensor-fault simulation. These support testing missing/stale evidence and recovery rather than judging only image appearance; they do not validate our thresholds, detector, mock realism or ADAS suitability. NHTSA material concerns ADS and is context, not a compliance checklist for this monitor. Full PDF fetches returned HTTP 403 in this research pass; relevant indexed excerpts were available. ISO 26262 and ISO 21448 remain process references requiring qualified applicability review, not claims of conformance.

Consequently, the runtime remains offline-capable and monitor-only; remote Decisions is optional advisory evidence. “Unknown/unavailable” is a report, not an implemented vehicle fallback. This revision exercises a bounded set of synthetic fault mechanisms, not all automotive hazards. Safety milestones and independent/physical/target validation remain open.


## 9. Demonstration and release evidence

A credible development demonstration shows paced input and its explicit simulation status; a normal counterexample; a labelled fault with measured alert/recovery timing; an interruption or overload that transitions to unavailable/unknown; complete failed as well as passing gates; and source, workload, hardware, and clock provenance. It must not imply a live camera, independent accuracy, hard-real-time guarantee, vehicle integration, or safety approval unless each is actually demonstrated.

Before an engineering release, provide reproducible setup and test instructions, pinned dependencies, architecture and trust boundaries, data rights/privacy notes, machine-readable measurements, failure cases, and a review record. Keep live vehicle operation, actuation, and safety claims blocked until stage 5 exit evidence exists.

### Deferred scope

No steering/braking/exposure control, lane detection, driver monitoring, arbitrary public URLs, fleet management, online adaptation, safety certification claims, or production deployment in this roadmap. Add only after a separately approved intended use and safety process.

## 10. References

- [Current implementation and evidence](README.md), [product principles](PRODUCT.md), and [historical research/evidence](RESEARCH_AND_PLAN.md).
- [ISO 26262 — Road vehicles, functional safety](https://www.iso.org/publication/PUB200262.html) and [ISO 21448:2022 — Road vehicles, safety of the intended functionality](https://www.iso.org/standard/77490.html). These are engineering-process references, not evidence of COOLPilot compliance or certification; applicability and implementation require qualified review.
- [OpenCV video I/O properties](https://docs.opencv.org/4.x/d4/d15/group__videoio__flags__base.html): timestamp and capture behavior depend on the device and backend.
- [Euro NCAP sensor-blocking protocol](https://cdn.euroncap.com/cars/assets/ad_001_ad_sensor_blocking_47d61e8ea8.pdf): context for sensor-blocking evaluation, not validation or certification of this application.
- [OpenCV COOL documentation/product overview](https://opencv.org/cloud/) and [publisher AWS Marketplace listing](https://aws.amazon.com/marketplace/pp/prodview-fdvbfiewzuehs): runtime target and optimization scope; vendor performance claims require matched independent measurement.
- [NHTSA Automated Driving Systems 2.0](https://www.nhtsa.gov/sites/nhtsa.dot.gov/files/documents/13069a-ads2.0_090617_v9a_tag.pdf), printed pp. 8–9: fallback and validation methods.
- [NHTSA Framework for Automated Driving System Testable Cases and Scenarios](https://www.nhtsa.gov/sites/nhtsa.gov/files/documents/13882-automateddrivingsystems_092618_v1a_tag.pdf), printed pp. 70, 112–113: simulation and SIL/HIL sensor-fault testing context.
