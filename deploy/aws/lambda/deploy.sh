#!/usr/bin/env bash
# Deploys the serverless edition: private S3 bucket (recordings + read-only history snapshot), an IAM role,
# one arm64 Lambda behind a streaming Function URL (open; a global per-minute budget caps replays and downloads;
# COOLPILOT_LOGIN=1 adds a generated login).
# Run build.sh first. Re-running updates in place. teardown.sh removes everything it created.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$(cd "$HERE/../../.." && pwd)"
export AWS_PROFILE="${COOLPILOT_AWS_PROFILE:-admin-azhar-freetrial}"
export AWS_REGION="${COOLPILOT_AWS_REGION:-us-east-1}" AWS_DEFAULT_REGION="${COOLPILOT_AWS_REGION:-us-east-1}"
FN=coolpilot; ROLE=coolpilot-lambda
LAYER="arn:aws:lambda:$AWS_REGION:753240598075:layer:LambdaAdapterLayerArm64:30"   # Lambda Web Adapter 1.1.0
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="coolpilot-data-$ACCOUNT-$AWS_REGION"
STATE="$HERE/.state"; mkdir -p "$STATE"; chmod 700 "$STATE"
[ -f "$HERE/build/function.zip" ] || { echo "Run build.sh first." >&2; exit 1; }

echo "== bucket $BUCKET"
if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  aws s3api create-bucket --bucket "$BUCKET" >/dev/null
  aws s3api put-public-access-block --bucket "$BUCKET" \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  aws s3api put-bucket-tagging --bucket "$BUCKET" --tagging 'TagSet=[{Key=Project,Value=coolpilot}]'
fi
python3 - "$ROOT/data/coolpilot.sqlite3" "$HERE/build/seed.sqlite3" <<'PY'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
src.backup(dst); dst.execute("PRAGMA journal_mode=DELETE"); dst.close(); src.close()   # consistent single-file snapshot
PY
aws s3 cp --only-show-errors "$HERE/build/seed.sqlite3" "s3://$BUCKET/data/coolpilot.sqlite3"
aws s3 sync --only-show-errors "$ROOT/data/oxford_robotcar/videos" "s3://$BUCKET/data/oxford_robotcar/videos" --delete
aws s3 sync --only-show-errors "$ROOT/data/oxford_robotcar/camera_health_development" "s3://$BUCKET/data/oxford_robotcar/camera_health_development" --delete
ZIPKEY="code/function-$(shasum "$HERE/build/function.zip" | cut -c1-12).zip"
aws s3 cp --only-show-errors "$HERE/build/function.zip" "s3://$BUCKET/$ZIPKEY"

echo "== rate counter table"
TABLE=coolpilot-rate
if ! aws dynamodb describe-table --table-name "$TABLE" >/dev/null 2>&1; then
  aws dynamodb create-table --table-name "$TABLE" --attribute-definitions AttributeName=k,AttributeType=S \
    --key-schema AttributeName=k,KeyType=HASH --billing-mode PAY_PER_REQUEST --tags Key=Project,Value=coolpilot >/dev/null
  aws dynamodb wait table-exists --table-name "$TABLE"
  aws dynamodb update-time-to-live --table-name "$TABLE" --time-to-live-specification Enabled=true,AttributeName=expires >/dev/null
fi

echo "== role $ROLE"
if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE" --tags Key=Project,Value=coolpilot \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  sleep 12
fi
aws iam put-role-policy --role-name "$ROLE" --policy-name read-data --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[
 {\"Effect\":\"Allow\",\"Action\":\"s3:GetObject\",\"Resource\":\"arn:aws:s3:::$BUCKET/data/*\"},
 {\"Effect\":\"Allow\",\"Action\":\"s3:ListBucket\",\"Resource\":\"arn:aws:s3:::$BUCKET\",\"Condition\":{\"StringLike\":{\"s3:prefix\":\"data/*\"}}},
 {\"Effect\":\"Allow\",\"Action\":\"dynamodb:UpdateItem\",\"Resource\":\"arn:aws:dynamodb:$AWS_REGION:$ACCOUNT:table/$TABLE\"}]}"

# Open by default. COOLPILOT_LOGIN=1 adds a generated username and password (the app enforces it).
CRED="$STATE/credentials"
if [ "${COOLPILOT_LOGIN:-0}" = 1 ]; then
  [ -f "$CRED" ] || { umask 077; printf 'judge:%s\n' "$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | cut -c1-20)" > "$CRED"; }
else
  rm -f "$CRED"
fi
python3 - "$CRED" "$BUCKET" "$STATE/env.json" "$AWS_REGION" "$TABLE" <<'PY'
import json, os, sys
cred, bucket, out, region, table = sys.argv[1:]
env = {"AWS_LAMBDA_EXEC_WRAPPER": "/opt/bootstrap", "AWS_LWA_INVOKE_MODE": "response_stream", "AWS_LWA_PORT": "8080",
       "AWS_LWA_READINESS_CHECK_PATH": "/api/health", "AWS_LWA_ASYNC_INIT": "true",
       "COOLPILOT_DATA": "/tmp/coolpilot-data", "COOLPILOT_S3_BUCKET": bucket, "COOLPILOT_READONLY": "1",
       "COOLPILOT_ALLOWED_HOSTS": f"*.lambda-url.{region}.on.aws",
       "COOLPILOT_WARM": "1", "COOLPILOT_RATE_TABLE": table, "COOLPILOT_REPLAYS_PER_MIN": os.environ.get("COOLPILOT_REPLAYS_PER_MIN", "6"),
       "COOLPILOT_DOWNLOADS_PER_MIN": os.environ.get("COOLPILOT_DOWNLOADS_PER_MIN", "12"),
       "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
if os.path.exists(cred):
    env["COOLPILOT_BASIC_AUTH"] = open(cred).read().strip()
json.dump({"Variables": env}, open(out, "w"))
PY
chmod 600 "$STATE/env.json"

echo "== function $FN"
COMMON=(--function-name "$FN" --runtime python3.12 --handler run.sh --memory-size 2048 --timeout 60
        --ephemeral-storage Size=1024 --layers "$LAYER" --environment "file://$STATE/env.json")
if aws lambda get-function --function-name "$FN" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$FN" --s3-bucket "$BUCKET" --s3-key "$ZIPKEY" --architectures arm64 >/dev/null
  aws lambda wait function-updated --function-name "$FN"
  aws lambda update-function-configuration "${COMMON[@]}" >/dev/null
else
  for attempt in 1 2 3 4 5 6; do   # a new role can take a moment to become assumable
    aws lambda create-function "${COMMON[@]}" --role "arn:aws:iam::$ACCOUNT:role/$ROLE" --architectures arm64 \
      --code "S3Bucket=$BUCKET,S3Key=$ZIPKEY" --tags Project=coolpilot >/dev/null 2>"$STATE/err" && break
    grep -q "cannot be assumed" "$STATE/err" && [ "$attempt" -lt 6 ] && { sleep 8; continue; }
    cat "$STATE/err" >&2; exit 1
  done
fi
aws lambda wait function-updated --function-name "$FN"

URL="$(aws lambda get-function-url-config --function-name "$FN" --query FunctionUrl --output text 2>/dev/null || true)"
if [ -z "$URL" ] || [ "$URL" = None ]; then
  URL="$(aws lambda create-function-url-config --function-name "$FN" --auth-type NONE --invoke-mode RESPONSE_STREAM --query FunctionUrl --output text)"
fi
aws lambda add-permission --function-name "$FN" --statement-id public-url --action lambda:InvokeFunctionUrl \
  --principal '*' --function-url-auth-type NONE >/dev/null 2>&1 || true
aws lambda add-permission --function-name "$FN" --statement-id public-invoke --action lambda:InvokeFunction \
  --principal '*' --invoked-via-function-url >/dev/null 2>&1 || true
echo "$URL" > "$STATE/url"
echo "URL: $URL"; [ ! -f "$CRED" ] || echo "Login is in $CRED (user:password, mode 600)"
