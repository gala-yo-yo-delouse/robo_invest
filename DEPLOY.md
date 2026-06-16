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
# builds the Docker-free Lambda zip, then provisions the stack via CDK
npm run deploy:dev        # dev/paper stack
# npm run deploy:prod     # prod/live stack (-prod- names, schedule starts disabled)
```

First run also bootstraps CDK in the account
(`npx cdk bootstrap aws://<account>/us-east-1 --profile robotrade-admin`).
Each deploy writes `web/amplify_outputs.<env>.json` with the real
Cognito/AppSync config (and `host:<env>` builds the dashboard against it).

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

## Environments (dev / prod)

Two **fully isolated** stacks, selected by `ROBOTRADE_ENV` at deploy time. They
share nothing — separate DynamoDB tables, Lambdas, Cognito pools, AppSync APIs,
dashboards, and Alpaca secrets.

| | **dev** | **prod** |
|---|---|---|
| Alpaca | paper (`robotrade/alpaca-paper`) | live (`robotrade/alpaca-live`) |
| Resource names | `robotrade-*` (legacy) | `robotrade-prod-*` |
| Schedule | enabled | **disabled** until you turn it on |
| Backend deploy | `npm run deploy:dev` | `npm run deploy:prod` |
| Dashboard deploy | `npm run host:dev` | `npm run host:prod` |

Workflow: develop + validate on **dev/paper**; deploy the *same code* to
**prod/live** with `npm run deploy:prod`. Each backend deploy writes
`web/amplify_outputs.<env>.json`; the matching `host:<env>` builds the dashboard
against it as a separate Amplify Hosting app.

Per-env setup (once): seed settings into that env's table
(`STATE_TABLE=robotrade-prod-state … scripts/seed_settings.py`) and create its
Cognito admin user.

## Go live (turn on prod)

Prod has **three independent safety gates**, off by default: the EventBridge
schedule ships disabled, `trading_enabled` is forced **false** when the prod
config is seeded (so the bot evaluates but places no orders — buys *and* sells),
and the live secret starts stubbed. Bring them up in order.

1. **Deploy the prod backend** (creates `robotrade-prod-*`, schedule disabled):
   ```bash
   npm run deploy:prod
   ```

2. **Put real keys in the live secret** (create it first if this is the first
   prod deploy — see step 2 above with `--name robotrade/alpaca-live`):
   ```bash
   aws secretsmanager put-secret-value --profile robotrade-admin --region us-east-1 \
     --secret-id robotrade/alpaca-live \
     --secret-string '{"ALPACA_API_KEY":"<live>","ALPACA_SECRET_KEY":"<live>","ALPACA_BASE_URL":"https://api.alpaca.markets"}'
   ```

3. **Seed prod settings** into the prod table — comes up with trading OFF:
   ```bash
   AWS_PROFILE=robotrade-admin STORAGE_BACKEND=dynamodb \
     ROBOTRADE_ENV=prod STATE_TABLE=robotrade-prod-state \
     .venv/bin/python scripts/seed_settings.py
   # prints: env=prod  trading_enabled=False  ← enable from the dashboard when ready
   ```

4. **Create the prod Cognito admin** (use `web/amplify_outputs.prod.json` for the
   pool id) and **deploy the dashboard**: `npm run host:prod`.

5. **Verify wiring** — fire a Telegram test at the prod Lambda; the message
   should arrive tagged `🔴 [PROD · LIVE]`:
   ```bash
   aws lambda invoke --function-name robotrade-prod-trading \
     --payload '{"ping":true}' --cli-binary-format raw-in-base64-out \
     --profile robotrade-admin --region us-east-1 /dev/stdout
   ```

6. **Configure strategies** in the prod dashboard (Strategies tab) while trading
   stays OFF. Then **enable the schedule** — with trading off, each cycle
   evaluates and notifies but executes nothing, so you can watch real signals
   against the live account risk-free:
   ```bash
   aws events enable-rule --name robotrade-prod-trading-schedule \
     --profile robotrade-admin --region us-east-1
   ```

7. **Go hot:** when the signals look right, flip **Trading enabled** on in the
   dashboard (Settings → Save). Orders now execute. To stop, untick it (halts
   buys and sells instantly, no redeploy) and/or disable the rule:
   ```bash
   aws events disable-rule --name robotrade-prod-trading-schedule \
     --profile robotrade-admin --region us-east-1
   ```

## Tear down

```bash
npm run deploy:delete:prod                              # removes the prod stack
ampx sandbox delete --profile robotrade-admin           # removes the dev stack
```

`robotrade[-env]-state` (DynamoDB) has `RemovalPolicy.RETAIN` — it survives teardown
so trading history/watermarks aren't lost. Delete it manually if you really want
it gone.
