# Shared settings for the AWS deploy scripts. Source, do not run.
set -euo pipefail
export AWS_PROFILE="${COOLPILOT_AWS_PROFILE:-admin-azhar-freetrial}"
export AWS_REGION="${COOLPILOT_AWS_REGION:-us-east-1}" AWS_DEFAULT_REGION="${COOLPILOT_AWS_REGION:-us-east-1}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
STATE="$HERE/.state/instance.env"
KEY_NAME=coolpilot-key
KEY_FILE="$HOME/.ssh/coolpilot-aws.pem"
SG_NAME=coolpilot-ssh
TAG="Project=coolpilot"
SSH_OPTS=(-i "$KEY_FILE" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o ServerAliveInterval=30)

load_state() {
  [ -f "$STATE" ] || { echo "No instance recorded. Run launch.sh first." >&2; exit 1; }
  # shellcheck disable=SC1090
  . "$STATE"
}
remote() { ssh "${SSH_OPTS[@]}" "$SSH_USER@$IP" "$@"; }
