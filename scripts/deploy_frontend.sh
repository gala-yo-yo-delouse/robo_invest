#!/usr/bin/env bash
# Build the dashboard and publish it to Amplify Hosting (manual deploy, no Git).
#
#   bash scripts/deploy_frontend.sh [dev|prod]   (default dev)
#
# Each env is a separate hosting app (robotrade-dashboard / robotrade-dashboard-prod)
# built against that env's backend config (web/amplify_outputs.<env>.json, written
# by `npm run deploy:<env>`). First run per env creates the app + 'main' branch.
# Login is the Cognito Authenticator (SRP) — no OAuth callback config needed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export AWS_PROFILE="${AWS_PROFILE:-robotrade-admin}"
export AWS_REGION="${AWS_REGION:-us-east-1}"

ENV="${1:-dev}"
[ "$ENV" = "dev" ] && SFX="" || SFX="-$ENV"
APP_NAME="robotrade-dashboard${SFX}"
OUT="$ROOT/web/amplify_outputs.${ENV}.json"

# Point the build at this env's backend config.
if [ -f "$OUT" ]; then
  cp "$OUT" "$ROOT/web/amplify_outputs.json"
else
  echo "WARN: $OUT not found — building against current web/amplify_outputs.json"
fi

# Find or create the Amplify Hosting app for this env.
APP_ID="${APP_ID:-$(aws amplify list-apps --query "apps[?name=='$APP_NAME'].appId | [0]" --output text)}"
if [ "$APP_ID" = "None" ] || [ -z "$APP_ID" ]; then
  APP_ID=$(aws amplify create-app --name "$APP_NAME" \
    --custom-rules '[{"source":"/<*>","target":"/index.html","status":"200"}]' \
    --query 'app.appId' --output text)
  aws amplify create-branch --app-id "$APP_ID" --branch-name main >/dev/null
  echo "Created Amplify app $APP_NAME ($APP_ID)"
fi

# Build the SPA and deploy the static output.
( cd "$ROOT/web" && npm run build )
( cd "$ROOT/web/dist" && rm -f ../dist.zip && zip -qr ../dist.zip . )
read -r JOB_ID UPLOAD_URL < <(aws amplify create-deployment \
  --app-id "$APP_ID" --branch-name main \
  --query '[jobId,zipUploadUrl]' --output text)
curl -s -T "$ROOT/web/dist.zip" "$UPLOAD_URL"
aws amplify start-deployment --app-id "$APP_ID" --branch-name main --job-id "$JOB_ID" >/dev/null
rm -f "$ROOT/web/dist.zip"

# Restore dev outputs as the default for the local dev server.
[ -f "$ROOT/web/amplify_outputs.dev.json" ] && cp "$ROOT/web/amplify_outputs.dev.json" "$ROOT/web/amplify_outputs.json"

echo "[$ENV] deploying job $JOB_ID → https://main.${APP_ID}.amplifyapp.com"
