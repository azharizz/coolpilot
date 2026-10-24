# COOLPilot reality check: how it compares with real camera-health systems

Written 2026-10-24, mid-project (before agent run 3 finished). This is a skeptical assessment, not a pitch. Our numbers come from this repository (`docs/EVALUATION.md`, `docs/evidence/`); outside facts come from the sources listed at the end, and anything we could not confirm is marked as such.

## Bottom line

- **The detector is not a breakthrough.** It uses textbook image statistics: detail from the variance of the Laplacian (a focus measure from microscopy autofocus), brightness, clipped pixels and frame differences, per tile. The main design choice, comparing each camera with its own learned normal, is also what commercial products do.
- **It is not a gimmick either, if it's described accurately.** It reliably catches the gross failures (black screen, frozen picture, heavy blur, darkness) on cameras it was never tuned on, on AWS Graviton with OpenCV 5, at a measured CPU cost. It fails at subtle ones (translucent smudge, weak glare), and the research literature shows that learned models trained on large real datasets also struggle with these.
- **The strongest part of the project is the test bench, not the detector.** It provides:
  - real-time paced replay with freshness measurement
  - a strict split between tuning and held-out data
  - fixed gates and full provenance
  - an agent loop whose choices are measured and then frozen
  - results that reproduce across machines
- **Honest positioning:** a reproducible camera-health bench and a camera data-quality gate for recorded video, with a classical baseline and measured limits. It is **not** an ADAS safety monitor.

## What COOLPilot measured (our own numbers)

Unpaced detector evaluation; the paced AWS run (EC2 t4g.small, Graviton2, OpenCV 5.0.0) gave the same held-out result.

| | Tuning (centre camera) | Held-out (left, right, rear cameras) |
|---|---|---|
| Original detector: failed checks / false alarms per hour | 4 of 6 / 1,324 | 12 of 18 / 1,099 |
| Current detector: failed checks / false alarms per hour | 0 of 6 / 37 | **5 of 18 / about 284** |
| Blackout, freeze, blur, underexposure | all pass | **all pass on all 3 cameras** (9/9 each over 3 paced repetitions) |
| Glare | pass | 1 of 3 cameras |
| Obstruction (translucent smudge) | "pass" that is a coincidence (a sky tile) | **0 of 3**; all 26 false alarms are obstruction |
| CPU (paced, 1 camera, 640 px) | 0.23 s per camera-second | 0.25 s per camera-second |

Limits of this evidence:
- One recorded 19-second drive (Oxford RobotCar sample), filmed by four cameras at once.
- Synthetic faults (image edits), not real dirt, rain, fog, night or sun.
- Only one fault event per type per camera, so 18 held-out checks in total. That is a small sample.
- Agent search (Agentic Vision): runs 1 and 2 were limited by bugs on our side, now fixed; run 3 is in progress. So far, no configuration has passed the strict "0 false alarms per hour" gate, for the agent or for random search.

## How the real world does this

### Production cars

- **Tesla** owner's manuals describe a "camera blocked or blinded" condition: Traffic-Aware Cruise Control and Autosteer become unavailable while a front camera lacks adequate visibility. Listed causes include dirt, rain, fog, glare, low light, condensation and featureless scenery such as tunnel walls. Later software versions show which camera is affected and an image from it. The detection method is not public.
- **Patents** give a sense of industry practice. One patent family describes separate flags for solid blockage, transparent blockage (a film that cuts contrast or brightness), water drops or condensation, and low light. Another proposes comparing against reference images chosen by lighting, weather and visual range, because plain image-processing blockage detection is unreliable in some environments. A third notes that an unchanging image may be a static scene rather than a fault. **We could not confirm Mobileye's own method** from public sources; one Mobileye-assigned patent on obstruction detection exists, but we did not verify its claims.
- **Safety framing:** under ISO 21448 (SOTIF), a camera that is working but blinded by glare, darkness or an obscured view is a *performance limitation*, a hazard without any malfunction. The remedies are scenario analysis, complementary sensors and validation in the real operating context. Two identical cameras do not fix it, because they share the same weakness. A production monitor must be validated on real conditions across its operating domain, which no hackathon project can do.

### Security cameras (the closest commercial analogue)

**AXIS Image Health Analytics** detects blocked, redirected, blurred and underexposed images. Axis describes it as an "AI-based application that analyzes and learns the behavior of the scene". Its documentation has striking parallels with what we found:

- It learns each camera's normal scene and relearns it. A view blocked for more than 10 minutes becomes the new normal. That is the same idea as our per-camera references and re-baselining.
- It uses a validation period of seconds to minutes before raising an alarm; the manual's example is 120 s. Our gate demands detection within **2 s**, far stricter.
- It **cannot raise blocked, blurred or redirected events in low-detail scenes** (a blank wall or grass field). That is the same weakness as our sky-tile problem.
- Lighting changes, IR night-mode switching and spiders cause false events. A fully blocked view also triggers blurred and underexposed at the same time, which is the cause-and-effect overlap our suppression rules handle.

Older tamper detection (an Axis patent) compared edge images with a reference edge image. The academic methods it cites detect obstruction from per-block entropy and defocus from gradient energy on stable edges. These are the same classical family as ours.

### Research on lens soiling (the hard case)

- **SoilingNet and TiledSoilingNet (Valeo, 2019–2020):**
  - A CNN classifies soiling on surround-view cameras as opaque or transparent.
  - TiledSoilingNet uses a **4×4 tile grid, the same grid as ours**, and predicts how much of each tile is clean, transparent, semi-transparent or opaque.
  - It was trained on **105,987 annotated real images** from four cameras with a ResNet-10 encoder.
  - Tile classification accuracy: clean 0.91, opaque 0.89, semi-transparent 0.70, **transparent only 0.58**, ranging from **0.24 to 0.79 depending on the camera**.
  - Part of the data is in the public **WoodScape** dataset. The paper does not say whether it was deployed in a product.
- **DRIVE-C (Georgia Tech, 2026 preprint):**
  - 12 corruption types at five severities (fog, rain, snow, glare, motion and defocus blur, lens occlusion, low light, noise, over- and underexposure, JPEG), applied **synthetically with OpenCV to real driving clips**. This is the same method as our held-out set, at larger scale: 610 clips, 78,080 frames.
  - Its learned baseline, "PerceptionHealthNet", reaches only r = 0.34 overall: good on underexposure (0.77) and motion blur (0.73), failing on defocus (0.12) and noise (−0.16). It also rates some clean night clips as poor.
  - DRIVE-C is a robustness benchmark; the authors say it is not meant for supervised training.

**What this means for us:** our failure on the translucent smudge is not an amateur mistake. A learned model trained on about 100,000 real images still gets transparent soiling right only 58% of the time on average. Our success on gross faults is also unremarkable: classical statistics have handled those for decades.

### AI agents tuning settings

LLM-guided hyperparameter search is an active research topic. Zhang et al. (2023) report that LLMs can match or beat random search and Bayesian optimisation under small budgets, and other work combines LLMs with Bayesian optimisation. An agent that tunes OpenCV settings is therefore **not novel science**. For the Agentic Vision award, what counts is a real, measured loop: invoke the workload, evaluate it, adjust, freeze, then validate on held-out data. Whether our agent beats random search is still open; so far it has not.

### Data-quality filtering for driving datasets

Autonomous-driving data pipelines do filter bad sensor data. NVIDIA's OmniDreams pipeline discards sequences with unreliable sensor data and uses a vision-language model to remove clips with visual artifacts. The ROVR dataset rejects frames by sensor checks and sends sequences with too many rejected frames to manual review. Industry write-ups describe rule-based filters that drop frames with excessive motion blur or sensor dropouts. We found **no public, documented production tool** dedicated to camera-health screening of recorded fleet video with measured accuracy. That is a plausible niche, though not proof of demand.

## Side-by-side

| | Production ADAS | Axis Image Health Analytics | Valeo TiledSoilingNet | DRIVE-C baseline | **COOLPilot** |
|---|---|---|---|---|---|
| Method | Not public; patents show multiple blockage types and condition-aware references | "AI-based", learns the scene | Learned CNN (ResNet-10), 4×4 tiles | Learned health index | Classical OpenCV statistics, 4×4 tiles, per-camera references |
| Training data | Proprietary fleet data | Not stated | 105,987 real images | Synthetic corruptions | **None**: about 10 thresholds tuned on 7 synthetic clips |
| Real faults | Yes | Yes (deployed) | Yes (real soiling) | No (synthetic) | **No (synthetic)** |
| Subtle soiling | Unknown | Blocked only; low-detail scenes excluded | Transparent 0.58 (0.24–0.79) | Lens occlusion included; weak overall | **Fails (0 of 3)** |
| Gross faults | Yes | Yes | Opaque 0.89 | Mixed | **Yes (all held-out)** |
| Alarm delay | Not public | Validation period, example 120 s | n/a (per frame) | n/a | **At most 2 s by gate** |
| Explainability | Not public | Event type only | Coverage per tile | Score | Reason per alarm (for example, "detail at 30% of this camera's normal") |
| Cost and hardware | Dedicated automotive SoC | On camera | Embedded target | GPU model | About 0.25 CPU-s per camera-s on t4g.small, no GPU |
| Validation discipline | ISO 26262 / 21448 processes | Vendor testing | 60/20/20 split | Severity sweeps | Tuning/held-out split, fixed gates, paced replay, provenance, reproduced on 2 platforms |

## Is "OpenCV only, no training, just tuning" a breakthrough?

No:

- **Tuning thresholds is training, with about 10 parameters.** It works when the features already separate the classes: a black frame has no detail, a frozen frame has no change. It cannot invent a signal the features don't contain. We showed this directly: a translucent smudge lowers tile detail to 0.45–0.85 of normal, while ordinary scene change moves it 10–20×.
- **The "no training" advantage is real but narrow:** no data collection, no GPU, an explanation for every alarm, and it works on a new camera immediately. That matters for cheap, explainable screening, not for safety-critical perception.
- **The path to subtle faults is data,** real soiled-lens footage such as WoodScape, and probably a small learned model. Even then, Valeo's numbers show that transparent soiling stays hard.

## What we can honestly claim, and what we can't

**We can claim:**
- Black-screen, frozen-picture, blur and darkness detection that generalised to three unseen cameras of the same drive, at real-time pacing on AWS Graviton with OpenCV 5.0.0, with measured latency and CPU.
- A root-cause analysis of why absolute thresholds fail (sky clipping, scene-relative brightness), with before/after numbers.
- A reproducible test bench that measures any camera-health method under real timing and fair splits, including an agent-in-the-loop search that is frozen and then validated.
- Honest negative results: obstruction is not solved, glare is partial, and false alarms are too high for a product.

**We cannot claim:**
- Road-safety value, ADAS readiness or ISO 26262 / SOTIF relevance.
- Performance on real dirt, rain, fog, night, low sun or other drives.
- That the agent beats random search (not shown yet).
- Any COOL speedup (not run on COOL; see `docs/COOL.md`).

## Where it is plausibly useful

1. **Camera data-quality gate for recorded fleet or robot video:** flag black, frozen, blurred or dark segments before labelling, training or incident review. It needs only the fault types we have shown to work, runs cheaply in batch on Graviton (and COOL, once available), and gives a reason for every flag. Driving-data pipelines already filter unreliable sensor data, so the need is real; demand for this specific tool is unproven.
2. **Test bench for camera-health methods:** compare a classical rule against a learned model (such as a WoodScape-trained one) under the same paced replay, splits and gates. The fair-comparison machinery is the reusable part.
3. **Monitoring for fixed cameras** (CCTV, robotics), where an alarm delay of a minute or more is acceptable. Axis's longer validation period shows how the false-alarm problem is usually handled.

## What would make it more reliable (in order)

1. **More held-out data:** add random seeds per camera (18 checks → 54 or more), then test on public data. DRIVE-C (synthetic, same method) and WoodScape soiling (real) are the obvious next benchmarks.
2. **Mark obstruction as experimental and turn it off by default:** it currently produces all of the held-out false alarms and catches none of the smudges.
3. **Glare:** also detect a bright bloom that does not clip, then check on fresh seeds only, so the held-out exam stays honest.
4. **Real lens soiling:** needs real data and probably a learned model; out of scope before the deadline.
5. **Alarm delay:** real products wait seconds to minutes. Reporting results at several delays (2 s, 10 s, 60 s) would show the trade-off honestly, instead of only the strict 2 s gate.

## Three recommendations for the OpenCV AI Competition 2026

### What the competition actually rewards

From the official Devpost page and opencv.org competition page (read 2026-10-24):

- **Theme:** "vision systems that see, reason, and act", with emphasis on "Physical AI and Generative AI systems in which visual understanding drives useful decisions, actions, predictions, or interactions".
- **Hard requirements:**
  - OpenCV 5 used for substantive image or video analysis, central rather than incidental
  - a meaningful component on AWS
  - a working web endpoint
  - a technical report covering the problem, users, architecture, OpenCV 5 implementation, AWS deployment, evaluation, limitations and responsible use
  - an architecture diagram
  - a video of at most 5 minutes
  - pinned dependencies and evaluation evidence *including failure cases*
- **Overall rubric:**
  - Technical execution 30% ("correctness and depth of the OpenCV 5" implementation)
  - Innovation 20%
  - Real-world impact 20% ("evidence of potential benefit")
  - UX 10%
  - Documentation 10%
  - Cloud delivery and responsible operation 10% (repeatability, observability, security)
- **Agentic Vision rubric:**
  - Substantive OpenCV 5 + agent 30%
  - Orchestration and autonomy 25%
  - Task effectiveness 20%
  - Failure handling and human control 15%
  - UX 10%
  
  Requires a perception, decision and action loop where *"the visual evidence must change what the system does next"*, an agent workflow diagram, a trace, and an evaluation of task success, failure handling, observability and human control.
- **Best Use of COOL rubric:**
  - Verified COOL on Graviton 30%
  - Architecture 25%
  - Measured performance and value 20%
  - Innovation 15%
  - Reproducibility 10%
  
  COOL must execute the claimed core workload, compared against an appropriate baseline.
- **The rules penalise overclaiming:** judges may reject an entry that "misrepresents capabilities, results, benchmarks, or the role of human review".
- **Suggested areas:**
  - "active perception for autonomous inspection with agentic orchestration or MCP"
  - "COOL-based server, serverless, container, or hybrid x86/Arm vision pipelines"
  - "developer agents that integrate COOL with tools such as Codex, Claude Code, Kiro, or MCP-compatible systems"
  - "safety" and "human-in-the-loop operations"

### Where COOLPilot is weak against that rubric today

1. **Depth of OpenCV 5 (the biggest weight) is thin.** OpenCV 5.0's headline features are a rewritten DNN engine (CPU-first, covering over 80% of ONNX operators, up from under 23%), built-in LLM and VLM components, and a new hardware abstraction layer (KleidiCV on Arm). COOLPilot uses none of the new parts. Its code runs identically on OpenCV 4.13, which we measured.
2. **The agent loop is a developer-time tuner,** which only fits the rule's "developer-agent workflow" clause. It has not beaten random search. The rubric's centre of gravity is a *runtime* perceive, decide and act loop with human control.
3. **Real-world benefit is unproven:**
   - 283 false alarms per hour on held-out cameras
   - obstruction is undetected
   - one 19-second drive
   - no user-facing outcome beyond a dashboard
4. **COOL is unverified** (account limitation), which caps the COOL award at zero.

None of the three recommendations below changes the honest core. Each targets one of these gaps with something that can be measured, and each says how it could fail.

### Recommendation 1: Active-perception verifier, a runtime agent that investigates each suspicion with OpenCV 5 tools before acting

**What it is.** Keep the cheap always-on monitor (classical statistics, about 0.25 CPU-s per camera-second) as the *trigger*. When it raises a suspicion, a runtime agent investigates with more expensive OpenCV 5 tools, run only on that moment and region. Then it acts:
- **confirm** with evidence
- **dismiss** with a stated reason
- **escalate to a human** for approval of a costly action, such as quarantining a footage segment or requesting a camera cleaning check

This is the cascade design long used in detection (cheap first stage, expensive second stage), and it is what the competition calls "active perception".

**Why this is real and not a gimmick.** Our measured false alarms have concrete, checkable causes:
- a low-texture sky tile
- a scene change behind a tile
- the same kinds of causes Axis documents (a parked truck "blocks" a camera; lighting changes cause false events)

Each cause has a verification tool that can *measure* it:

| Tool (OpenCV 5) | What it checks | Uses OpenCV 5 depth |
|---|---|---|
| Object detection with a permissively licensed ONNX model (for example YOLOX or NanoDet from the OpenCV model zoo; verify the license) through `cv2.dnn` on the new engine, CPU, Graviton | Is a vehicle or person occupying the suspected tiles? If so, the loss of detail is the scene, not the lens | **Yes: new DNN engine** |
| Low-texture check on the camera's own reference | Was this tile ever detailed (sky, blank wall)? Axis also refuses to judge such scenes | Classical |
| Motion persistence (dense optical flow over 1–2 s on the suspected tiles vs the rest) | A lens smudge stays put while the scene moves; a passing object moves | Classical (`calcOpticalFlowFarneback` / DIS) |
| Reference comparison crops | A before/now evidence image for the human reviewer | Classical |
| Optional VLM look (only with the existing image-upload consent and budget) | A second opinion on a frame | External model; OpenCV 5's own VLM path is too slow on CPU (over a minute per caption), so the existing remote review is used |

The tools can be exposed through **MCP** as well as the in-app API. Then any MCP agent (Claude Code, Kiro) can drive the same investigation, which matches a suggested project area.

**What to implement, replace or change:**
- **Implement:** a `verify(suspicion)` tool layer; an agent loop that calls these tools and returns confirm, dismiss or escalate with a cited reason; a human-approval queue in the UI; a trace view (perception → tool calls → decision → action) and an agent workflow diagram.
- **Change:** an alarm stays "suspected" until verified. If the agent errors, times out or is unavailable, the suspicion **stays raised** (fail-safe): an unavailable verifier can never silence an alarm.
- **Change the scoring:** add "verified" metrics next to the raw ones: false alarms per hour after verification, recall after verification (a wrongly dismissed real fault counts as a miss), added latency per suspicion, and tool CPU per suspicion.
- **Keep:** the developer-time tuning agent, as a second, smaller loop.

**How to prove it (task effectiveness, 20% of the Agentic rubric):**
- Run on held-out cameras with **fresh seeds** that were never inspected.
- Compare three arms:
  - (a) no verification
  - (b) a **deterministic verifier** (fixed rules over the same tools)
  - (c) the LLM agent
- Report confirm and dismiss accuracy against the labels, false alarms per hour, recall, latency and cost.
- If (c) is not better than (b), say so. The deterministic verifier is still a valid result, and the agent's value then lies in human-readable reasoning and escalation, not accuracy.

**Expected outcome (honest):**
- It should remove a large share of the sky and scene false alarms, because those causes are measurable.
- It will **not** create obstruction recall the features can't see. A smudge that the trigger never flags cannot be verified. The motion-persistence tool might help, but that is unproven.
- The win is a *trustworthy* alarm stream, which is exactly what the industry and CCTV sources say limits real deployments.

**Rubric fit:**
- Agentic Vision: a runtime loop where visual evidence changes the next action, plus human control, failure handling and a trace. This is its strongest possible fit.
- Technical execution: OpenCV 5 DNN engine, optical flow and an MCP tool interface.
- Innovation: a cascade with agentic verification on Graviton CPU.
- UX: an approval queue with evidence crops.

**Effort and risk:**
- About 1–1.5 days.
- Risks:
  - LLM latency (a few seconds per suspicion; acceptable for "suspected → verified", not for the first alarm)
  - model licensing (use Apache- or MIT-licensed zoo models and record the licenses)
  - Nebius tool-calling quirks (already seen; the JSON-string fix covers one)

### Recommendation 2: Turn it into a measurable camera-data quality gate on AWS, with more and better evidence

**What it is.** Reposition the product around the use case our evidence actually supports: **screening recorded camera footage** before it is used for labelling, training or incident review. It flags black, frozen, blurred, dark and glare segments with reasons and evidence thumbnails, and is honest about what it cannot see. Driving-data pipelines already discard unreliable sensor data (NVIDIA OmniDreams, the ROVR dataset); we found no public tool that specifically screens fleet video for camera health with measured accuracy.

**What to implement, replace or change:**
- **AWS pipeline:**
  - Upload to S3.
  - An event triggers an arm64 Lambda (OpenCV 5, Graviton) or an EC2/Batch worker for long files.
  - The output is a per-segment health report (JSON, CSV, thumbnails) plus CloudWatch metrics: throughput, cost per camera-hour processed, flags per hour.
  - This reuses the existing analyzer, monitor, EMF metrics and Lambda deployment.
- **Judge-facing upload:**
  - The judge uploads a short clip (size and duration limits, rate-limited, deleted after processing, no retention), then gets the report.
  - This turns "trust our dashboard" into "try your own video", for UX and real-world impact.
  - It needs an explicit privacy notice and must not keep faces or plates (responsible use).
- **Better evidence:**
  - Add random seeds per camera (18 → 54+ held-out checks) and report confidence intervals.
  - Evaluate on **DRIVE-C**: 610 clips of real driving with 12 OpenCV corruption types at 5 severities, made with the same method as ours but independent of us. Check its license first.
  - If licensing allows, add a **real** soiling check from WoodScape.
  - Report results **per severity**, so the boundary of what works is visible.
- **Replace the single 2-second gate** for this use case with alarm-delay curves (2 s, 10 s, 60 s). Offline screening can wait; a CCTV product waits up to minutes. This shows the trade-off instead of hiding it.
- **Mark obstruction experimental and turn it off by default.** It currently produces all held-out false alarms and catches nothing. Keep it measurable behind a switch.

**How to prove it:**
- Per-fault, per-severity recall and precision on data we did not create (DRIVE-C), plus fresh seeds on ours.
- Cost and throughput per camera-hour on Graviton.
- One end-to-end demo: upload → report → flagged segments match the injected faults.

**Expected outcome (honest):**
- Strong results on gross faults, measured on independent data.
- Weaker or failing results on subtle ones, now quantified by severity.
- That is exactly the "evidence of potential benefit, including failure cases" that the rubric and the rules ask for.

**Rubric fit:**
- Real-world impact: a concrete user (data teams) and measured benefit.
- Technical execution: correctness on independent data.
- Cloud delivery: an event-driven, observable, rate-limited, privacy-aware pipeline.
- UX: try-your-own-clip.
- Documentation: a clear, honest scope.

**Effort and risk:**
- About 1 day.
- Risks:
  - DRIVE-C download size and license
  - the cost of public uploads (rate limits and size caps exist already)
  - Lambda's 15-minute limit (long files go to EC2/Batch)

### Recommendation 3: Verified COOL, with a cost-per-camera-hour benchmark and the agent choosing the cheapest configuration

**What it is.** On an AWS account that can subscribe to COOL (your other account), run the *same* workload on the *same* Graviton instance with standard OpenCV 5 and with COOL. Also run it on one x86 instance as the "appropriate baseline" (for example c7i), and report **cost per camera-hour at a fixed latency target**. Then let the developer-time agent search threads, streams per instance and resolution under COOL to find the cheapest configuration that still meets every freshness gate. This matches the suggested area "developer agents that integrate COOL" through the existing tool loop (and MCP, if Recommendation 1 adds it).

**What to implement, replace or change:**
- **Already prepared:** `remote_setup.sh cool`, `launch.sh cool` with generations, runtime detection and an evidence checklist (`docs/COOL.md`).
- **Implement:**
  - A multi-stream throughput benchmark (N concurrent cameras per instance until a latency gate breaks). This exists in part as `concurrent_streams`.
  - An x86 run.
  - A same-host `opencv_profile --compare` table, per stage.
- **Change the workload so COOL can matter, honestly:**
  - Today decoding (FFmpeg) is about 70% of CPU and COOL is not documented to speed it up. So report per stage, and use `grab()` without `retrieve()` for skipped frames, so the decode cost of sampling is cut.
  - Recommendation 1's verification stage (DNN inference, optical flow) and higher analysis resolutions also shift more of the work into OpenCV, where COOL's tuning applies.
  - Never present a whole-pipeline speedup that is really a decode artefact.

**How to prove it:**
- COOL version, instance type, `cv2.__file__` under `/opt/cool`, and a build-information dump.
- Standard vs COOL vs x86 per stage, and the cost per camera-hour.
- An agent trace showing that a measured COOL result changed its next configuration, for example more streams per instance.
- All reproducible from scripts in the repository.

**Expected outcome (honest):**
- A measured speedup on the OpenCV stages (size unknown until run) and a smaller one end to end, because decode dominates.
- A possible cost-per-camera-hour advantage of Graviton over x86 regardless of COOL.
- Report whatever the numbers are; a small but verified result is eligible, an unverified claim is not.

**Rubric fit:**
- Best Use of COOL: verification (30%) and measured value (20%) are impossible without this; architecture and reproducibility are already mostly in place.
- Cloud delivery: repeatable infrastructure scripts.
- Technical execution: a per-stage performance analysis.

**Effort and risk:**
- About 0.5 day once the other account is subscribed.
- Cost: a few dollars (instance hours at roughly $0.15/h, plus a COOL software fee of about $0.01–0.04/h after the 7-day trial).
- Risks:
  - Marketplace subscription or AMI availability
  - vendor environment quirks (the vendor Python path, NumPy ABI)

### Priority and timing

Time left: about 2.5 days until 2026-10-26, 23:59 PT. The submission also needs the technical report, the architecture diagram and the video of at most 5 minutes.

| Order | Work | Why first |
|---|---|---|
| 1 | Recommendation 2's evidence pieces (fresh seeds, obstruction experimental, delay curves) | Cheap; makes every later number trustworthy; fresh seeds are needed to judge Recommendation 1 fairly |
| 2 | Recommendation 1 (verifier agent with OpenCV 5 DNN, fail-safe, approval queue, trace) | Biggest gain on the three largest criteria and the Agentic award; fixes the real false-alarm problem |
| 3 | Recommendation 3 (COOL) | Only when the subscribed account is ready; a self-contained half day |
| 4 | Recommendation 2's upload pipeline and DRIVE-C evaluation | Strong for impact and UX if time remains |

### What not to do (it would read as a gimmick, or break the rules)

- Do not claim ADAS or road-safety readiness, or SOTIF compliance.
- Do not train a soiling CNN in two days on synthetic smudges and present it as solving lens soiling. Valeo's 106k real images still reach 0.58 on transparent soiling.
- Do not let an LLM silence alarms without fail-safe behaviour and measured accuracy.
- Do not use OpenCV 5's VLM on CPU in the loop. Over a minute per caption is not a runtime component.
- Do not report a COOL speedup without the same-host comparison, or one that is really a decode effect.
- Do not tune on held-out cameras that have already been inspected; generate fresh seeds.

## Sources

Competition
- OpenCV AI Competition 2026 on Devpost: https://opencv26.devpost.com/
- OpenCV AI Competition 2026, official page with rubrics: https://opencv.org/opencv-ai-competition-2026/

OpenCV 5
- Phoronix, OpenCV 5.0 released: https://www.phoronix.com/news/OpenCV-5.0-Released
- Better Stack, what's new in OpenCV 5: https://betterstack.com/community/guides/ai/opencv-5-new-features/
- Linuxiac, rewritten DNN engine: https://linuxiac.com/opencv-5-0-computer-vision-library-released-with-rewritten-dnn-engine/
- heise, OpenCV 5.0 with LLM support: https://heise.de/-11326252

Production and patents
- Tesla owner's manual, Troubleshooting Alerts: https://www.tesla.com/ownersmanual/modely/en_gb/GUID-9A3F0F72-71F4-433D-B68B-0A472A9359DF.html
- Tesla owner's manual, Limitations and Warnings: https://tesla.com/ownersmanual/models/en_gb/GUID-E5FF5E84-6AAC-43E6-B7ED-EC1E9AEB17B7.html
- Not a Tesla App, obstructed-camera UI: https://www.notateslaapp.com/news/2374/tesla-adds-new-ui-when-fsd-camera-view-is-obstructed and https://www.notateslaapp.com/news/3942/tesla-improves-camera-visibility-alerts-with-larger-ui-in-fsd-v143
- "Vehicle vision system with object detection failsafe" (US 10936884, 11657620, 11978263): https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/10936884
- "Method for detecting an optical blockage of a camera of a vehicle" (US 12136241): https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/12136241
- Blockage reaction / static-scene note (US 2021/0370938): https://patents.justia.com/patent/20210370938
- Mobileye, "Systems and methods for detecting obstructions in a camera field of view" (US 10967793; claims not verified): https://patents.google.com/patent/US10967793
- SOTIF overviews: https://www.itemis.com/en/glossary/sotif/ and https://www.ansys.com/zh-cn/simulation-topics/what-is-sotif

Security cameras
- AXIS Image Health Analytics user manual: https://help.axis.com/axis-image-health-analytics
- Axis camera tampering detection patent (US 2008/0152232): https://patents.justia.com/patent/20080152232
- Survey of feature types for camera tampering detection (2023): https://arxiv.org/abs/2310.07886

Research
- SoilingNet: https://arxiv.org/abs/1905.01492
- TiledSoilingNet: https://arxiv.org/abs/2007.00801
- WoodScape dataset: https://arxiv.org/abs/1905.01489
- GAN-based soiling augmentation: https://arxiv.org/abs/1912.02249
- DRIVE-C: https://arxiv.org/abs/2605.09774
- Variance-of-Laplacian focus measure, background: https://opencv.org/autofocus-using-opencv-a-comparative-study-of-focus-measures-for-sharpness-assessment/

Agents and data pipelines
- Zhang et al., Using Large Language Models for Hyperparameter Optimization (2023): https://arxiv.org/abs/2312.04528
- SLLMBO, LLM + Bayesian optimisation: https://arxiv.org/abs/2410.20302
- NVIDIA OmniDreams (data filtering): https://arxiv.org/abs/2606.03159
- ROVR open dataset (frame rejection): https://arxiv.org/abs/2508.13977
- iMerit, sensor data triage: https://imerit.ai/resources/blog/sensor-data-triage-strategies-for-scalable-autonomous-vehicle-training/
