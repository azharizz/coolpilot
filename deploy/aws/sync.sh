#!/usr/bin/env bash
# Copies code, the built web UI and the ~140 MB of recordings the app needs. No .env, no history database.
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"; load_state
[ -f "$ROOT/web/dist/index.html" ] || { echo "Run 'npm run build' in web/ first." >&2; exit 1; }
cd "$ROOT"
remote 'mkdir -p ~/coolpilot/data ~/coolpilot/results && command -v rsync >/dev/null || sudo apt-get install -y -qq rsync >/dev/null'
rsync -azR --delete --exclude __pycache__ --exclude '*.pyc' -e "ssh ${SSH_OPTS[*]}" \
  coolpilot tests experiments scripts requirements.txt web/dist deploy/aws/remote_setup.sh \
  "$SSH_USER@$IP:coolpilot/"
rsync -azRH -e "ssh ${SSH_OPTS[*]}" \
  data/oxford_robotcar/videos data/oxford_robotcar/camera_health_development data/camera_health data/models \
  "$SSH_USER@$IP:coolpilot/"
echo "Synced to $SSH_USER@$IP"
