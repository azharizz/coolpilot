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

## Evidence checklist (for the Best Use of COOL award)

All items must come from the same COOL instance:

- [ ] COOL product, version and Graviton generation, plus the instance type
- [ ] `/api/system` shows `distribution: "COOL"` and `cv2.__file__` under `/opt/cool`
- [ ] `results/build-cool.txt` (full `cv2.getBuildInformation()`)
- [ ] `opencv_profile --compare` standard vs COOL, on the same host, per stage
- [ ] A completed run on `oxford-camera-holdout` with the COOL environment recorded in every experiment
- [ ] An agent run whose search includes `threads`, showing whether more threads helped under COOL
