"""Exercise local three-camera HTTP replay. No paid requests or promotion.

Run against an idle app with the three supplied Oxford videos available.
"""

import json
import os
import urllib.request

BASE = os.environ.get("COOLPILOT_VERIFY_URL", "http://127.0.0.1:8000")


def main():
    with urllib.request.urlopen(BASE + "/api/health", timeout=10) as response:
        assert json.load(response)["status"] == "ok"
    cameras = {"left", "centre", "right"}
    payload = {"mode": "local", "faults": {camera: "reference" for camera in cameras}}
    request = urllib.request.Request(BASE + "/api/camera-comparison/analyze",
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
    seen, result = set(), None
    with urllib.request.urlopen(request, timeout=60) as response:
        for line in response:
            event = json.loads(line)
            assert event["type"] not in ("error", "camera_error"), event
            if event["type"] == "frame":
                assert event["pipeline_status"] in ("healthy", "degraded", "unknown", "unavailable")
                assert event["quality_status"] in ("no_issue_detected", "suspected", "unknown")
                if event.get("image"):
                    seen.add(event["camera"])
            elif event["type"] == "complete":
                result = event
    assert seen == cameras, seen
    assert result is not None and not result["cancelled"]
    assert len(result["profiles"]) == 3
    for profile in result["profiles"]:
        assert "error" not in profile, profile
        trace = profile["trace"]
        accounted = sum(trace[key] for key in ("processed", "skipped", "dropped", "interrupted_frames",
                                               "rejected_frames", "unfinished_frames"))
        assert trace["expected_frames"] == accounted, (trace["expected_frames"], accounted)
        assert not trace["reviews"], "Local-only verification must not request image review"
    print(json.dumps({"passed": True, "cameras": sorted(seen), "measurement": result["measurement"],
                      "cool": result["cool"]}, indent=2))


if __name__ == "__main__":
    main()
