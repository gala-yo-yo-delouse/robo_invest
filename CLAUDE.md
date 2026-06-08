# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A three-strategy Alpaca trading bot. The same Python engine runs two ways:

- **Local CLI / Streamlit** — offline-friendly, JSON-file state (the original).
- **Serverless AWS stack** — always-on: EventBridge → Lambda → DynamoDB, with an
  Amplify Gen 2 React dashboard. This is the deployed system; full runbook in
  **`DEPLOY.md`**.

The only difference between the two is the **storage backend**, chosen by the
`STORAGE_BACKEND` env var (`local` files vs `dynamodb`). All trading logic is shared.

## Commands

### Local (offline, paper)
```bash
python main.py portfolio | signals | profiles | status | execute
python main.py run [--interval 5]      # continuous loop during market hours
streamlit run dashboard.py             # local Streamlit dashboard
pip install -r requirements.txt
```

### Cloud (AWS profile `robotrade-admin`, region `us-east-1`)
```bash
npm run build:lambda                   # vendor the Docker-free arm64/py3.10 Lambda zip
npm run deploy:dev | deploy:prod       # deploy a backend stack (see Environments)
npm run host:dev   | host:prod         # build + publish the React dashboard to Amplify Hosting
```
First-time setup, seeding, admin user, and go-live steps: **`DEPLOY.md`**.

## Architecture

```
                 settings (settings.yaml  OR  DynamoDB config item)
                                    ↓
Alpaca Positions → Portfolio → StrategyEngine → TradeSignal[] (priority + symbol-order)
                                    ↓
                        InvestmentGuidelines (per-buy-type budget gate)
                                    ↓
                        AlpacaClient → Alpaca API
                                    ↓
                        ledger + watermarks  (JSON files  OR  DynamoDB)
```

Local: a `runner.py` loop calls `run_one_cycle()`. Cloud: EventBridge invokes the
trading Lambda, which calls the **same** `run_one_cycle()` once per fire.

### Strategy fork

Each security in the config is assigned one of three modes (`StrategyMode`):

- **HOLD** — do nothing unless stop-loss triggers (priority 10).
- **CASH_OUT** — sell signals: take-profit (8), trailing-stop via watermark (9).
- **INCREASE_HOLDING** — buy signals: buy-the-dip from watermark peak (5), DCA on
  schedule (2); optional profit-protection sell (8). Each buy is tagged `BuyType`
  (DCA or STRATEGY).

`StrategyEngine.evaluate_all()` routes each security to its fork.

### Budget model + ordering

Buys are gated by `InvestmentGuidelines` with **separate budgets for DCA vs
STRATEGY**. Daily limits are required; weekly/monthly/single-order are optional
(0 = no limit). Budget is reserved greedily during evaluation in **settings order**
— so the order of securities in the config is the priority order: earlier = funded
first when budget is tight. That same order is the tiebreaker in the final
priority sort (`evaluate_all`). The dashboard's Strategies tab edits this order.

### Storage backend (`src/storage.py`)

Pluggable, selected by `STORAGE_BACKEND` (default `local`):

- `LocalBackend` — JSON/YAML under `config/` (watermarks.json, spending_ledger.json,
  settings.yaml).
- `DynamoBackend` — one table `robotrade[-<env>]-state`, partition key `pk` ∈
  {`watermarks`, `ledger`, `config`}, each value a JSON string.

`watermark.py`, `guidelines.py`, and `config_loader.py` delegate to the active
backend behind unchanged signatures, so the CLI works offline and the Lambdas use
DynamoDB with no code-path fork. Settings live in DynamoDB in the cloud so the
dashboard can edit them; `settings.yaml` is the one-time seed
(`scripts/seed_settings.py`).

### Environments (dev / prod)

Two fully isolated stacks selected by `ROBOTRADE_ENV` at deploy time
(parameterizes every resource name in `amplify/backend.ts` + `data/resource.ts`):

| | dev | prod |
|---|---|---|
| Alpaca | paper (`robotrade/alpaca-paper`) | live (`robotrade/alpaca-live`) |
| Names | `robotrade-*` (legacy, unchanged) | `robotrade-prod-*` |
| Schedule | enabled | **disabled** until turned on |

They share nothing (separate DynamoDB / Lambdas / Cognito / AppSync / dashboards).
Promote = deploy the same code with `ROBOTRADE_ENV=prod`. See `DEPLOY.md`.

## Cloud stack components

- **Trading Lambda** (`lambda_fns/trading_handler.py`) — one `run_one_cycle()` per
  EventBridge fire (every 5 min, Mon–Fri, market-hours window; re-checks Alpaca's
  clock). A `{"ping": true}` event sends a Telegram test.
- **Query Lambda** (`lambda_fns/query_handler.py`) — frontend reads (portfolio /
  signals / profiles / status) computed fresh from Alpaca + settings read/write.
  Routed by AppSync `event.fieldName`. Reuses the Python strategy engine.
- **Dashboard** (`web/`) — React + Vite, Amplify Authenticator (single Cognito
  admin), `generateClient<Schema>()` against the AppSync custom queries. Mirrors
  the Streamlit tabs + a Strategies editor (add/remove/reorder securities, edit
  params/budgets, change mode).
- **IaC** (`amplify/backend.ts`) — Amplify Gen 2 + CDK: auth, data (AppSync custom
  queries → query Lambda by name), DynamoDB table, both Python Lambdas (arm64 /
  py3.10 zip, no Docker), EventBridge schedule, Secrets Manager grants.
- **Hosting** — `scripts/deploy_frontend.sh <env>`: manual Amplify Hosting deploy
  (no Git), one app per env.

## Key modules

| Module | Role |
|--------|------|
| `src/models.py` | Dataclasses + enums (Holding, Portfolio, TradeSignal, TradingStrategy, StrategyMode, BuyType, …) |
| `src/strategy.py` | `StrategyEngine` — signal generation + priority/order sort |
| `src/guidelines.py` | Budget enforcement, ledger I/O (via storage), DCA timing, dedup |
| `src/runner.py` | `run_one_cycle()` (shared by local loop + trading Lambda) and the continuous loop |
| `src/storage.py` | Pluggable persistence: `LocalBackend` (JSON) / `DynamoBackend` |
| `src/secrets.py` | Loads Alpaca/Telegram creds from Secrets Manager into env (cloud) |
| `src/config_loader.py` | Settings → dataclass tree (reads via the storage backend) |
| `src/alpaca_client.py` | Alpaca API wrapper (orders, market data, live portfolio) |
| `src/watermark.py` | High-water-mark persistence (via storage) for trailing stops |
| `src/notifier.py` | Telegram alerts (reads creds at call time; no-op if unset) |
| `lambda_fns/` | `trading_handler.py`, `query_handler.py` |
| `amplify/` | Gen 2 backend: `backend.ts`, `data/resource.ts`, `auth/resource.ts` |
| `web/` | React dashboard (Vite) |
| `scripts/` | `build_lambda.sh`, `seed_settings.py`, `deploy_frontend.sh` |

## Environment / secrets

**Local** — Alpaca + Telegram creds in `.env` (python-dotenv):
```
ALPACA_API_KEY=...        ALPACA_SECRET_KEY=...
ALPACA_BASE_URL=https://paper-api.alpaca.markets
TELEGRAM_BOT_TOKEN=...    TELEGRAM_CHAT_ID=...
```

**Cloud** — credentials in AWS Secrets Manager (user-owned, not CDK-managed):
`robotrade/alpaca-paper`, `robotrade/alpaca-live`, `robotrade/telegram`. The
Lambdas select the Alpaca secret via `ALPACA_ENV` (paper|live, derived from
`ROBOTRADE_ENV`). The Lambda runtime is **Python 3.10** (the old
`alpaca-trade-api` pins deps whose arm64 wheels stop at 3.10).

## Local continuous mode (`python main.py run`)

Autonomous loop during market hours with config reload each cycle, DCA timing,
signal dedup, file logging (`logs/runner.log`), and SIGHUP survival. For an
always-on setup prefer the cloud stack; for local, run under `tmux` +
`caffeinate -i`. The cloud stack supersedes this for production.
