#!/usr/bin/env bash
# Terminates the recorded instance. Add --all to also delete the key pair and security group.
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
if [ -f "$STATE" ]; then
  . "$STATE"; aws ec2 terminate-instances --instance-ids "$INSTANCE_ID" >/dev/null
  aws ec2 wait instance-terminated --instance-ids "$INSTANCE_ID"; rm -f "$STATE"; echo "Terminated $INSTANCE_ID"
fi
if [ "${1:-}" = --all ]; then
  aws ec2 delete-key-pair --key-name "$KEY_NAME" || true; rm -f "$KEY_FILE"
  SG="$(aws ec2 describe-security-groups --filters Name=group-name,Values=$SG_NAME --query 'SecurityGroups[0].GroupId' --output text)"
  [ "$SG" = None ] || aws ec2 delete-security-group --group-id "$SG" || true
fi
aws ec2 describe-instances --filters Name=tag:Project,Values=coolpilot Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'Reservations[].Instances[].[InstanceId,State.Name]' --output text
