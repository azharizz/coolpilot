# AWS deployment (Graviton + COOL)

## Serverless edition (Lambda, arm64)

```sh
( cd web && npm run build )
bash deploy/aws/lambda/build.sh      # aarch64 wheels only, no Docker; ~139 MB unzipped
bash deploy/aws/lambda/deploy.sh     # private S3 bucket, IAM role, function, streaming Function URL (open to anyone)
bash deploy/aws/lambda/teardown.sh   # removes all of it
```

One Python 3.12 function on Graviton (3008 MB, behind Lambda Web Adapter with response streaming) serves the UI, the live three-camera replay, History, evidence playback and Runtime. The URL is open by default. `COOLPILOT_LOGIN=1 bash deploy/aws/lambda/deploy.sh` adds a generated username and password (saved to `deploy/aws/lambda/.state/credentials`, enforced by the app via `COOLPILOT_BASIC_AUTH`; `/api/health` stays open for the adapter's readiness probe).

Validate, Apply, Rollback and Cancel are disabled here (`COOLPILOT_READONLY=1`, HTTP 409, and the UI says so). A Lambda environment is frozen between requests and requests can land on different copies, so a background benchmark paced by the wall clock, and SQLite history, cannot be trusted. Run those on the always-on server below. History shows a snapshot seeded from S3; anything created on Lambda is discarded when the environment is recycled.

Measured on this deployment (untouched footage, three cameras, 2048 MB): a warm replay processes 271 of 271 frames per camera with freshness 0.2 to 0.5 s against the 0.5 s limit, analysis p95 3 to 5 ms, about 0.8 cores, 17 MB streamed, peak memory 564 MB. A freshly started copy can drop 2 to 5 frames on its first replay; opening any page starts a background warm-up, which helps but does not fully remove that. Cold start is about 5 to 6 s. Below 2048 MB freshness slips past the limit (1769 MB was measured).

Cost control without a login: a global per-minute budget (a tiny DynamoDB counter shared by every copy of the function) allows 6 replays and 12 video or export downloads per minute in total, then answers 429 "busy, try again in a minute". Seeks within a video, History, Runtime and the UI are never limited. Tune with `COOLPILOT_REPLAYS_PER_MIN` and `COOLPILOT_DOWNLOADS_PER_MIN` when running `deploy.sh`. The counter fails closed: if it cannot be reached, the expensive endpoints refuse rather than run unmetered. At the cap, worst-case sustained abuse is about 6 GB/h of replay traffic plus 12 downloads/min (roughly 12 GB/h), so on the order of $1/hour after the free allowances; AWS Free Plan accounts are also limited to their credits. Emergency stop: `aws lambda put-function-concurrency --function-name coolpilot --reserved-concurrent-executions 0` (undo with `delete-function-concurrency`).

## Always-on server (EC2)

Only EC2 can run COOL: it ships as a Marketplace AMI (or container image) for Graviton. Lambda, Lightsail and CloudFront cannot run an AMI. The app stays bound to `127.0.0.1` on the server and has no login, so it is reached through an SSH tunnel only.

Defaults: profile `admin-azhar-freetrial`, region `us-east-1` (`COOLPILOT_AWS_PROFILE`, `COOLPILOT_AWS_REGION`). SSH is allowed from the launching machine's current IP only. Instances stop themselves after a TTL (plain 120 min, COOL 240 min). The account is on the AWS Free Plan, which only permits `t4g.micro`/`t4g.small` (Graviton2) until upgraded to a paid plan.

```sh
bash deploy/aws/launch.sh plain          # stock Ubuntu arm64: tests the path, standard-OpenCV baseline
bash deploy/aws/sync.sh                  # code, built UI (run `npm run build` in web/ first), ~140 MB of recordings
ssh -i ~/.ssh/coolpilot-aws.pem ubuntu@IP 'bash ~/coolpilot/deploy/aws/remote_setup.sh standard'
ssh -i ~/.ssh/coolpilot-aws.pem -L 8769:127.0.0.1:8769 ubuntu@IP     # then open http://127.0.0.1:8769
bash deploy/aws/teardown.sh [--all]      # terminate (and --all also deletes the key pair and security group)
```

## Running with COOL

1. Subscribe once in AWS Marketplace to the COOL Graviton 2 product (`sku=4eb70u7a6gb5bj1ijix5jlokv`, AMI `COOL-graviton2-v2-prod-*`) in this account. This accepts the vendor's terms and pricing, so it is done by a person in the console.
2. `bash deploy/aws/teardown.sh && bash deploy/aws/launch.sh cool && bash deploy/aws/sync.sh`
3. `ssh -i ~/.ssh/coolpilot-aws.pem ubuntu@IP 'bash -s' < deploy/aws/remote_discover.sh` to find the vendor interpreter and its `cv2`.
4. `ssh ... 'COOL_PYTHON=/path/to/python bash ~/coolpilot/deploy/aws/remote_setup.sh cool'`. This builds a venv that inherits the vendor `cv2` and numpy and never installs the standard wheels over them.
5. On the same instance, run the standard build too (`remote_setup.sh standard`), then compare:
   `python -m experiments.opencv_profile --compare results/profile-standard.json results/profile-cool.json`
   It reports CPU per stage and exits non-zero unless every detection is identical.
6. `runtime.py` labels a build COOL only when `cv2.__file__` starts with `/opt/cool/`. That path is an unverified guess: compare it with the step 3 output and correct it from evidence before trusting the UI label.

Compare builds on one instance only. t4g is burstable, so absolute numbers are noisy, but a same-instance A/B is still fair.
