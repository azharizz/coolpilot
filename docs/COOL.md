# Running COOLPilot on COOL (migration guide)

Status: **not run on COOL yet.** The code and deploy scripts are prepared, but this account's AWS Free Plan cannot subscribe to paid Marketplace products. Upgrading the account (or using another one) and subscribing are the operator's steps. Nothing in this repository claims a COOL measurement until the checklist at the end has been completed.

## What COOL is (from the AWS Marketplace listings)

- OpenCV's Cloud Optimized OpenCV Library: OpenCV 5 built for AWS Graviton with KleidiCV plus additional parallelization tuning. The Graviton4 Docker edition also links Arm Performance Libraries (ARMPL), for ECS/EKS.
- Delivered as Ubuntu 24.04 AMIs, one product per Graviton generation (G2, G3, G4).
- 7-day free trial, then a usage-based software fee of about $0.01–$0.04 per hour on top of EC2 (for example, G2 on c6g.2xlarge $0.02/h; G4 on c8g.xlarge $0.01/h and m8g.4xlarge $0.04/h). Check the listing for current prices.
- Recommended instances: G2 c6g.2xlarge or larger; G4 m8g.4xlarge or larger. c8g, m8g and r8g are compatible.
- Vendor support: support@opencv.org.

Layout on the AMI:

| What | Path |
|---|---|
| Python environments | `/opt/cool/venvs/python_3.10`, `python_3.11`, `python_3.12` (activate with `source /opt/cool/venvs/python_3.12/bin/activate`) |
| Python packages | `PYTHONPATH=/opt/cool/python_3.12/site-packages/` |
| Shared libraries | `LD_LIBRARY_PATH=/opt/cool/cpp_sdk/lib` |
| C++ CMake config | `OpenCV_DIR=/opt/cool/cpp_sdk/lib/cmake/opencv4` |

## How COOLPilot uses it

- `deploy/aws/remote_setup.sh cool` runs the app with the vendor interpreter (`$COOL_VENV/bin/python`, default `/opt/cool/venvs/python_3.12`). Our other dependencies are installed with `pip --target ~/deps-cool` from `requirements.txt` **minus opencv and numpy**, so the standard wheels can never shadow the vendor `cv2`. The systemd unit exports `PYTHONPATH`, `LD_LIBRARY_PATH=/opt/cool/cpp_sdk/lib` and `COOLPILOT_COOL_ROOT`.
- `coolpilot/runtime.py` reports `distribution: "COOL"` only when the loaded `cv2` module lives under `COOLPILOT_COOL_ROOT` (default `/opt/cool`) on Linux ARM64. It also records which acceleration layers `cv2.getBuildInformation()` mentions (KleidiCV, Carotene, ARMPL, NEON). Every experiment stores this environment, so a COOL result can be told apart from a standard one.
- `threads` (1, 2, 4) is part of the agent's search space, so the agent can find where COOL's parallel tuning pays off on a given instance size instead of assuming it does.

## What to expect (measured facts, before COOL)

Measured on EC2 t4g.small (Graviton2, 2 vCPU) with the standard `opencv-python-headless` 5.0.0 wheel (`results/profile-standard.json` from `remote_setup.sh`), CPU seconds per 271-frame clip:

| Stage | CPU s |
|---|---|
| Video decode | ~1.9 |
| OpenCV analysis (resize, cvtColor, Laplacian, meanStdDev, compare, countNonZero) | ~0.7 |
| Python alarm logic | ~0.2 |

Two consequences:

1. **The standard aarch64 wheel already reports KleidiCV.** KleidiCV in the build information is therefore not evidence of COOL; the module path and the AMI are.
2. **COOL can only speed up part of our workload.** Analysis is about a quarter of the per-frame CPU. Decoding dominates, and it runs in FFmpeg, which COOL is not documented to change. Even an infinitely fast analysis stage would save at most about 25% of CPU here. A COOL speedup claim for COOLPilot must be stated per stage, not as a headline number.

## Migration steps (operator)

1. Use an AWS account on a paid plan, then subscribe to the COOL product for the chosen generation in AWS Marketplace and accept its terms.
2. Launch: `COOLPILOT_COOL_GEN=2 bash deploy/aws/launch.sh cool` (G2 → c6g.xlarge; `3` → c7g.xlarge; `4` → c8g.xlarge; pass an instance type as the second argument to override). The instance terminates itself after its TTL.
3. `bash deploy/aws/sync.sh`, then run `remote_setup.sh cool` on the instance. It prints the runtime identity, runs the test suite, profiles OpenCV and starts the service.
4. On the **same instance**, also run `remote_setup.sh standard` (a separate venv) to get a same-host baseline, then compare: `python -m experiments.opencv_profile --compare results/profile-standard.json results/profile-cool.json`.
5. Run the evaluation sequence against the COOL service: `python -m experiments.evaluation_runs --api http://127.0.0.1:8769 baseline random agent`.

## Measured on COOL (2026-10-27)

**Deployment:**
- **COOL Graviton2 AMI:** `ami-009ab0cb3e3e0acc1` (`COOL-graviton2-v2-prod`, us-east-1), on a **c6g.2xlarge** (Neoverse-N1, 8 vCPU, Ubuntu 24.04), in a separate paid AWS account with the 7-day COOL trial.
- **COOL build:** OpenCV **4.12.0** ("4.12.0-dirty"), Custom HAL **KleidiCV 0.5.0 + Carotene**, linked against **Arm Performance Libraries 25.07**, **TBB** parallel framework, NumPy 1.26.4, at `/opt/cool/python_3.12/site-packages`.
- The same instance ran two baselines: the standard `opencv-python-headless` **4.12.0.88** wheel (same version, isolates what COOL adds) and our shipped **5.0.0.93** wheel.
- Method: `experiments/cool_benchmark.sh` (setup, tests, per-stage profiles at 1 and 8 threads, NanoDet timing, comparisons). Inputs: the three Oxford stereo clips (3 × 271 frames). Evidence: `docs/evidence/cool/`. Cost of the run: about 12 instance-minutes.

**COOL executes the core workload.**
- COOLPilot's own runtime check reported `distribution: COOL`, with accelerators KleidiCV, Carotene, ARMPL and NEON.
- **All 62 tests passed** under COOL.
- The full service ran under it (`/api/system` → `cool: true`).
- COOL and the 4.12 wheel gave **identical measurements and alarms** (0 differences).

**Per-stage CPU, same host (A/B > 1 means B is faster):**

| Comparison | 1 OpenCV thread | 8 OpenCV threads |
|---|---|---|
| 4.12 wheel (A) vs **COOL** (B) | total 1.01×; OpenCV analysis 1.01×; decode 0.97× | total **0.90×**; analysis **0.84×** (TBB overhead on our small images) |
| Standard **5.0.0** (A) vs COOL (B) | total 0.90× (5.0 faster); decode 0.43× (5.0's decoder 2.3× faster) | total 0.82× |
| NanoDet median ms per frame | 4.12 wheel 94.5 · COOL 98.0 · **5.0 new engine 68.9** | 4.12 wheel 56.0 · COOL 76.5 · **5.0 new engine 14.7** |

**Capacity and cost (MEASURED, 2026-10-27).** Method: `experiments/cool_capacity.sh`.
- **Workload:** 8 camera streams at once, one per vCPU, each with 1 OpenCV thread. Each stream runs the production pipeline (decode, OpenCV analysis, alarm logic; no optional optical flow) on the three Oxford stereo clips, unpaced.
- **Capacity:** real-time cameras = total frames/s ÷ the sample's 14.26 fps.
- **Prices:** on-demand, us-east-1, from the AWS Pricing API. The COOL software fee is $0 during the trial.

| Instance and build | Total frames/s | Real-time cameras | CPU use | Analysis p95 under load | $/h | **Cost per 1,000 camera-hours** |
|---|---|---|---|---|---|---|
| c6g.2xlarge (Graviton2, Arm), **COOL 4.12** | 387.0 | 27 | 98.9% | 18.5 ms | 0.272 | **$10.07** |
| c6g.2xlarge (Graviton2, Arm), **standard OpenCV 5.0.0** | 439.9 | 30 | 98.8% | 21.6 ms | 0.272 | **$9.07** |
| c7i.2xlarge (Intel Xeon 8488C, x86), standard OpenCV 5.0.0 | 483.6 | 33 | 98.6% | 20.0 ms | 0.357 | **$10.82** |

- **Arm wins on cost.** Standard OpenCV 5 on Graviton2 is 16% cheaper per camera than on x86. COOL on Graviton2 is 7% cheaper than x86, but 11% dearer than standard OpenCV 5 on the same Arm host.
- **COOL had the lowest analysis p95 under load** (18.5 ms), but lower total throughput: decode dominates, and COOL's build decodes more slowly.
- Tests passed on all three: 62 on each Graviton stack, plus the x86 run (`docs/evidence/cool/capacity-*/`).
- An earlier single-stream estimate (`capacity-estimate.json`: about 42, 42 and 60 cameras) was **too optimistic**. With all 8 cores busy, throughput per stream drops (memory bandwidth and decode contention). The measured numbers above replace it.

**The autopilot decision for this workload: standard OpenCV 5.0.0 on Graviton2, one thread per camera stream, about 30 cameras per c6g.2xlarge at $9.07 per 1,000 camera-hours.** It beats COOL on the same host and x86 on cost. COOL runs it correctly but brings no gain, for three reasons:
- **Decoding** (23–44% of CPU) is outside COOL's scope.
- Our heaviest calls (`Laplacian`, grey `cvtColor`, `meanStdDev`, `countNonZero`) are not on the KleidiCV HAL list. Only the 0.5× `INTER_AREA` resize and `absdiff` are.
- This COOL image is OpenCV 4.12, so it has no OpenCV 5 DNN engine.

**Architecture:**
- The public endpoint is an **arm64 Lambda** with the standard OpenCV 5.0.0 wheel. It is serverless, read-only, and serves uploads through S3.
- COOL runs on **EC2 Graviton**, because COOL ships as a Marketplace AMI and Lambda cannot use one.
- Evaluation and benchmarking ran on EC2 Graviton (t4g.small, standard wheel; c6g.2xlarge, COOL).
- **x86 appears only as a measured baseline** (c7i.2xlarge). Nothing in the deployed system runs on x86. Arm handles both serving (Lambda) and the camera fleet tier (EC2 Graviton).

**Bug found and fixed:** `remote_setup.sh cool` put only our own dependencies on `PYTHONPATH`, so the vendor `cv2` was not found. It now adds `/opt/cool/python_3.x/site-packages`, the layout measured on the AMI.

## Evidence checklist (for the Best Use of COOL award)

All items must come from the same COOL instance:

- [ ] COOL product, version and Graviton generation, plus the instance type
- [ ] `/api/system` shows `distribution: "COOL"` and `cv2.__file__` under `/opt/cool`
- [ ] `results/build-cool.txt` (full `cv2.getBuildInformation()`)
- [ ] `opencv_profile --compare` standard vs COOL, on the same host, per stage
- [ ] A completed run on `oxford-camera-holdout` with the COOL environment recorded in every experiment
- [ ] An agent run whose search includes `threads`, showing whether more threads helped under COOL
