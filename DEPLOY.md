# Cloud Deploy — Serverless Stack + Amplify Dashboard

The always-running stack: **EventBridge → Trading Lambda → DynamoDB**, with an
**Amplify Gen 2** dashboard (Cognito auth, single admin) backed by a **Query
Lambda**. Region `us-east-1`, AWS profile `robotrade-admin`. Starts on Alpaca
**paper**.

```
EventBridge (every 5 min, Mon–Fri, market-hours window)
      └─► robotrade-trading (Lambda)  ──► Alpaca  +  robotrade-state (DynamoDB)
Amplify Hosting (React) ─► Cognito ─► AppSync ─► robotrade-query (Lambda) ─► Alpaca / DynamoDB
Secrets Manager: robotrade/alpaca   (ALPACA_API_KEY / SECRET / BASE_URL)
```

## Prerequisites

- A valid SSO session for the profile: `aws sso login --profile robotrade-admin`
- Node deps installed at repo root (`npm install`) and in `web/` (`cd web && npm install`)

## 1. Deploy the backend

```bash
# builds the Docker-free Lambda zip, then provisions everything via CDK
npm run deploy            # one-shot   (ampx sandbox --once)
# or: npm run deploy:watch  to stay attached and hot-reload on backend edits
```

First run also bootstraps CDK in the account. On success, `web/amplify_outputs.json`
is (over)written with the real Cognito/AppSync config.

## 2. Set the Alpaca credentials

Credentials live in **user-owned** secrets (not CDK-managed), one per
environment. The Lambdas select one via the `ALPACA_ENV` env var
(`paper` | `live`, set in `backend.ts`). Create them once — paper is required,
live can stay stubbed until you're ready:

```bash
aws secretsmanager create-secret --profile robotrade-admin --region us-east-1 \
  --name robotrade/alpaca-paper \
  --secret-string '{"ALPACA_API_KEY":"<paper-key>","ALPACA_SECRET_KEY":"<paper-secret>","ALPACA_BASE_URL":"https://paper-api.alpaca.markets"}'

aws secretsmanager create-secret --profile robotrade-admin --region us-east-1 \
  --name robotrade/alpaca-live \
  --secret-string '{"ALPACA_API_KEY":"","ALPACA_SECRET_KEY":"","ALPACA_BASE_URL":"https://api.alpaca.markets"}'
```

(Update values later with `put-secret-value --secret-id robotrade/alpaca-<env>`.)

## 3. Seed settings into DynamoDB

Copies `config/settings.yaml` into the `config` item the bot reads:

```bash
AWS_PROFILE=robotrade-admin STORAGE_BACKEND=dynamodb \
  .venv/bin/python scripts/seed_settings.py
```

## 4. Create the single admin user

```bash
POOL=$(jq -r .auth.user_pool_id web/amplify_outputs.json)
aws cognito-idp admin-create-user --profile robotrade-admin --region us-east-1 \
  --user-pool-id "$POOL" --username you@example.com \
  --user-attributes Name=email,Value=you@example.com Name=email_verified,Value=true
# set a permanent password (skips the FORCE_CHANGE_PASSWORD flow)
aws cognito-idp admin-set-user-password --profile robotrade-admin --region us-east-1 \
  --user-pool-id "$POOL" --username you@example.com --password '<StrongPass1!>' --permanent
```

## 5. Run the dashboard

```bash
cd web && npm run dev      # local dev against the deployed backend
```

Log in with the admin user. For a hosted phone-accessible URL later, connect the
repo to **Amplify Hosting** (appRoot `web/`) — the same backend serves it.

## 6. Verify (paper)

- **Trading loop:** `aws logs tail /aws/lambda/robotrade-trading --since 15m --follow --profile robotrade-admin --region us-east-1`
  during market hours — expect a cycle summary each run, no real money.
- **Dashboard:** Portfolio / Signals / Profiles load live; edit a budget or a
  per-symbol param in **Strategies → Save**, then confirm the next trading
  cycle reflects it (settings reload every cycle).

## Switch to live (later)

1. Put real keys in the live secret:
   ```bash
   aws secretsmanager put-secret-value --profile robotrade-admin --region us-east-1 \
     --secret-id robotrade/alpaca-live \
     --secret-string '{"ALPACA_API_KEY":"<live>","ALPACA_SECRET_KEY":"<live>","ALPACA_BASE_URL":"https://api.alpaca.markets"}'
   ```
2. Flip the selector — set `const ALPACA_ENV = 'live'` in `amplify/backend.ts`
   and `npm run deploy`. (Quick, no-redeploy alternative: override the env var on
   both functions with `aws lambda update-function-configuration --function-name
   robotrade-{trading,query} --environment "Variables={...,ALPACA_ENV=live}"` —
   but you must pass the full Variables map, so editing backend.ts is safer.)

Secret values are never touched when switching — only the `ALPACA_ENV` pointer.

## Tear down

```bash
npm run deploy:delete      # removes the sandbox stack
```

`robotrade-state` (DynamoDB) has `RemovalPolicy.RETAIN` — it survives teardown
so trading history/watermarks aren't lost. Delete it manually if you really want
it gone.
