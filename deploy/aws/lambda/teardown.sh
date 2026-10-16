#!/usr/bin/env bash
# Removes the Function URL, function, role and bucket created by deploy.sh.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export AWS_PROFILE="${COOLPILOT_AWS_PROFILE:-admin-azhar-freetrial}"
export AWS_REGION="${COOLPILOT_AWS_REGION:-us-east-1}" AWS_DEFAULT_REGION="${COOLPILOT_AWS_REGION:-us-east-1}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"; BUCKET="coolpilot-data-$ACCOUNT-$AWS_REGION"
aws lambda delete-function-url-config --function-name coolpilot 2>/dev/null
aws lambda delete-function --function-name coolpilot 2>/dev/null
aws dynamodb delete-table --table-name coolpilot-rate >/dev/null 2>&1
aws iam delete-role-policy --role-name coolpilot-lambda --policy-name read-data 2>/dev/null
aws iam detach-role-policy --role-name coolpilot-lambda --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole 2>/dev/null
aws iam delete-role --role-name coolpilot-lambda 2>/dev/null
aws s3 rb "s3://$BUCKET" --force 2>/dev/null
aws logs delete-log-group --log-group-name /aws/lambda/coolpilot 2>/dev/null
rm -rf "$HERE/.state"; echo "Removed."
