#!/bin/bash
# Lambda start command (the function handler). Lambda Web Adapter proxies each request to this server.
export PYTHONPATH=/var/task PYTHONDONTWRITEBYTECODE=1
cd /var/task
python3 /var/task/fetch_data.py || exit 1
exec python3 -m uvicorn coolpilot.api:app --host 0.0.0.0 --port 8080 --workers 1 --no-access-log
