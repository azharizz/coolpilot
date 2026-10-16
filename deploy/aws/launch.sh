#!/usr/bin/env bash
# Usage: launch.sh plain|cool [instance-type=t4g.small] [ttl-minutes]
# plain = stock Ubuntu arm64 on Graviton (tests the deployment path and gives the standard-OpenCV baseline).
# cool  = licensed COOL AMI; needs an AWS Marketplace subscription to the product first.
# Every instance terminates itself after the TTL, so a forgotten one cannot keep billing.
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
MODE="${1:?plain|cool}"; TYPE="${2:-t4g.small}"  # Free Plan accounts may only launch free-tier types (t4g.micro/small); c6g needs a paid plan
case "$MODE" in plain) TTL="${3:-120}";; cool) TTL="${3:-240}";; *) echo "mode must be plain or cool" >&2; exit 2;; esac
[ ! -f "$STATE" ] || { echo "An instance is already recorded in $STATE. Run teardown.sh first." >&2; exit 1; }

if [ "$MODE" = cool ]; then
  AMI="${COOLPILOT_AMI:-$(aws ec2 describe-images --owners aws-marketplace \
    --filters "Name=name,Values=COOL-graviton2-v2-prod-*" "Name=architecture,Values=arm64" \
    --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text)}"
  DISK=()
else
  AMI="$(aws ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id --query Parameter.Value --output text)"
  DISK=(--block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=30,VolumeType=gp3,DeleteOnTermination=true}')
fi
echo "AMI $AMI ($MODE), $TYPE, self-terminates after $TTL min"

# SSH key pair (private key stays in ~/.ssh, never in the project).
if ! aws ec2 describe-key-pairs --key-names "$KEY_NAME" >/dev/null 2>&1; then
  mkdir -p "$HOME/.ssh"; rm -f "$KEY_FILE"
  aws ec2 create-key-pair --key-name "$KEY_NAME" --key-type ed25519 --query KeyMaterial --output text > "$KEY_FILE"
  chmod 400 "$KEY_FILE"
fi
[ -f "$KEY_FILE" ] || { echo "Key pair $KEY_NAME exists in AWS but $KEY_FILE is missing. Delete the key pair or restore the file." >&2; exit 1; }

# Security group: SSH from this machine's current IP only. The app itself is never exposed.
VPC="$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)"
SG="$(aws ec2 describe-security-groups --filters Name=group-name,Values=$SG_NAME Name=vpc-id,Values="$VPC" --query 'SecurityGroups[0].GroupId' --output text)"
if [ "$SG" = None ]; then
  SG="$(aws ec2 create-security-group --group-name $SG_NAME --description 'COOLPilot SSH from operator IP' --vpc-id "$VPC" \
    --tag-specifications "ResourceType=security-group,Tags=[{Key=Project,Value=coolpilot}]" --query GroupId --output text)"
fi
MYIP="$(curl -fsS -m 10 https://checkip.amazonaws.com | tr -d '[:space:]')"
aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 22 --cidr "$MYIP/32" >/dev/null 2>&1 || true

USERDATA="$(printf '#!/bin/bash\nshutdown -P +%s\n' "$TTL")"
ID="$(aws ec2 run-instances --image-id "$AMI" --instance-type "$TYPE" --key-name "$KEY_NAME" \
  --security-group-ids "$SG" --count 1 --instance-initiated-shutdown-behavior terminate \
  --metadata-options HttpTokens=required,HttpEndpoint=enabled "${DISK[@]}" --user-data "$USERDATA" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=coolpilot-$MODE},{Key=Project,Value=coolpilot},{Key=Mode,Value=$MODE}]" \
  --query 'Instances[0].InstanceId' --output text)"
echo "Launched $ID; waiting for it to run"
aws ec2 wait instance-running --instance-ids "$ID"
IP="$(aws ec2 describe-instances --instance-ids "$ID" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"
mkdir -p "$(dirname "$STATE")"
printf 'INSTANCE_ID=%s\nIP=%s\nMODE=%s\nTYPE=%s\nSSH_USER=ubuntu\nLAUNCHED=%s\nTTL_MIN=%s\n' "$ID" "$IP" "$MODE" "$TYPE" "$(date -u +%FT%TZ)" "$TTL" > "$STATE"

for user in ubuntu ec2-user admin; do
  for _ in $(seq 1 30); do
    if ssh "${SSH_OPTS[@]}" -o BatchMode=yes "$user@$IP" true 2>/dev/null; then
      sed -i.bak "s/^SSH_USER=.*/SSH_USER=$user/" "$STATE"; rm -f "$STATE.bak"
      echo "Ready: ssh -i $KEY_FILE $user@$IP"; exit 0
    fi
    sleep 6
  done
done
echo "Instance is up but SSH did not answer. Check the instance console." >&2; exit 1
