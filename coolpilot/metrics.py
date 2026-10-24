"""CloudWatch Embedded Metric Format: one JSON line on stdout becomes metrics (Lambda log ingestion).

Off unless COOLPILOT_METRICS=1. Values are what the app already measured; nothing is sampled here.
"""
import json
import os
import time

NAMESPACE = "COOLPilot"


def emit(event: str, values: dict, units: dict | None = None):
    if os.environ.get("COOLPILOT_METRICS") != "1":
        return
    values = {k: float(v) for k, v in values.items() if isinstance(v, (int, float)) and v == v}
    if not values:
        return
    units = units or {}
    print(json.dumps({"_aws": {"Timestamp": int(time.time() * 1000), "CloudWatchMetrics": [{
        "Namespace": NAMESPACE, "Dimensions": [["Event"]],
        "Metrics": [{"Name": k, "Unit": units.get(k, "None")} for k in values]}]},
        "Event": event, **values}), flush=True)
