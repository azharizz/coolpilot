"""Exercise the real HTTP, Nebius, OpenCV and persistence flow. Uses inference credits.

Run inside the app container. No mock endpoints or fabricated production results.
"""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("COOLPILOT_VERIFY_URL", "http://127.0.0.1:8000")


def request(path, body=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as response:
        return json.load(response)


def wait(identifier):
    while True:
        run = request("/api/runs/" + identifier)
        if run["status"] not in ("queued", "running"):
            assert run["status"] == "completed", run.get("error")
            return run
        time.sleep(2)


def main():
    assert request("/api/health")["dataset"] == "ready"
    strict = wait(
        request(
            "/api/runs",
            {
                "name": "Verification: strict rejection",
                "strategy": "baseline",
                "frames": 60,
                "repetitions": 1,
                "goals": {"max_corner_error_px": 0.0001},
            },
        )["id"]
    )
    assert strict["recommendation"] is None
    assert not strict["experiments"][0]["gate"]["passed"]
    try:
        request(f"/api/experiments/{strict['experiments'][0]['id']}/apply", {})
    except urllib.error.HTTPError as error:
        assert error.code == 409
    else:
        raise AssertionError("An unvalidated configuration was applied")
    reference = wait(
        request(
            "/api/runs",
            {
                "name": "Verification: reference",
                "strategy": "baseline",
                "frames": 100,
                "repetitions": 2,
            },
        )["id"]
    )
    assert reference["recommendation"] is not None, (
        "Reference did not satisfy the configured quality gate"
    )
    first = reference["recommendation"]
    request(f"/api/experiments/{first}/apply", {})
    run = wait(
        request(
            "/api/runs",
            {
                "name": "Verified Nebius search",
                "strategy": "agent",
                "budget": 4,
                "frames": 300,
                "repetitions": 3,
            },
        )["id"]
    )
    assert any(
        e["kind"] == "candidate" and e["status"] == "completed"
        for e in run["experiments"]
    ), "No real agent-chosen experiment executed"
    assert any(e["kind"] == "tool_call" for e in run["events"])
    assert run["recommendation"] is not None, "No candidate passed held-out validation"
    second = run["recommendation"]
    request(f"/api/experiments/{second}/apply", {})
    assert request("/api/active")["experiment_id"] == second
    assert request("/api/active/rollback", {})["experiment_id"] == first
    request(f"/api/experiments/{second}/apply", {})
    export = request(f"/api/runs/{run['id']}/export")
    encoded = json.dumps(export)
    key = os.environ.get("NEBIUS_API_KEY")
    assert not key or key not in encoded, "Secret appeared in an export"
    assert export["dataset"]["sha256"]
    assert all(
        e.get("trace")
        for e in export["run"]["experiments"]
        if e["status"] == "completed"
    )
    cancellation = request(
        "/api/runs",
        {
            "name": "Verification: cancellation",
            "strategy": "random",
            "frames": 1000,
            "repetitions": 10,
            "budget": 20,
        },
    )["id"]
    time.sleep(1)
    assert request(f"/api/runs/{cancellation}/cancel", {})["status"] == "cancelled"
    assert request(f"/api/runs/{cancellation}")["status"] == "cancelled"
    output = Path(os.environ.get("COOLPILOT_DATA", "data")) / "live-verification.json"
    output.write_text(
        json.dumps(
            {
                "passed": True,
                "agent_run": run["id"],
                "rejection_run": strict["id"],
                "reference_run": reference["id"],
                "cancelled_run": cancellation,
                "active_experiment": second,
            },
            indent=2,
        )
    )
    print(output.read_text())


if __name__ == "__main__":
    main()
