"""Queue the evaluation runs on a COOLPilot API and wait for each (one run at a time).

    python -m experiments.evaluation_runs --api http://127.0.0.1:8769 baseline random agent

Every run uses the held-out dataset, the UI's proposed gates and the server's calibrated detector
defaults. Search strategies tune on the tuning split; the winner is frozen and validated by the app.
"""
import argparse
import json
import time
import urllib.request

FAULTS = ("blur", "underexposure", "glare", "obstruction", "blackout", "freeze")
GOALS = {"faults": {k: {"min_recall": 1, "max_detection_s": 2, "max_recovery_s": 2, "min_events": 1} for k in FAULTS},
         "max_false_alarms_per_hour": 0, "min_normal_seconds": 30, "max_age_s": 0.5,
         "max_unknown_fraction": 0.1, "max_api_failure_fraction": 0}


def call(api, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(api + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8769")
    ap.add_argument("--dataset", default="oxford-camera-holdout")
    ap.add_argument("--budget", type=int, default=8)
    ap.add_argument("--repetitions", type=int, default=3)
    ap.add_argument("strategies", nargs="+", choices=["baseline", "random", "agent"])
    args = ap.parse_args()
    catalog = call(args.api, "/api/system")["camera_datasets"]
    dataset = next(d for d in catalog if d["id"] == args.dataset)
    for strategy in args.strategies:
        body = {"workload": "camera_health", "strategy": strategy, "budget": args.budget,
                "repetitions": args.repetitions, "seed": 42, "name": f"Held-out cameras: {strategy}",
                "camera": {"dataset": dataset["id"], "dataset_sha256": dataset["sha256"], "goals": GOALS}}
        identifier = call(args.api, "/api/runs", body)["id"]
        print(f"{strategy}: run {identifier}", flush=True)
        while (run := call(args.api, f"/api/runs/{identifier}"))["status"] in ("queued", "running"):
            time.sleep(10)
        print(f"{strategy}: {run['status']}", run.get("error") or "", flush=True)


if __name__ == "__main__":
    main()
