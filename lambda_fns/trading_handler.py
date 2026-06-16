"""EventBridge-triggered Lambda: run one trading cycle.

This is the cloud replacement for `python main.py run`. EventBridge fires it on
a schedule during market hours; each invocation does exactly one evaluate +
execute pass (the loop/sleep lives in EventBridge now, not in code).

Env:
  STORAGE_BACKEND=dynamodb   state in the robotrade-state table
  STATE_TABLE=robotrade-state
  ALPACA_SECRET_ARN=...      Alpaca keys in Secrets Manager
"""

import logging

from src.alpaca_client import AlpacaClient
from src.notifier import notify_test
from src.runner import run_one_cycle
from src.secrets import load_secrets_into_env, load_telegram_into_env

logging.getLogger().setLevel(logging.INFO)

# settings live in DynamoDB; config_loader ignores this path for the dynamo
# backend, but run_one_cycle still requires an argument.
_CONFIG_PATH = "config/settings.yaml"


def handler(event, context):
    load_secrets_into_env()
    load_telegram_into_env()

    # Diagnostic hook: `{"ping": true}` sends a Telegram test message and exits
    # (used to verify cloud notification wiring without waiting for a trade).
    if event.get("ping"):
        notify_test()
        return {"ping": "sent"}

    client = AlpacaClient()

    # EventBridge fires on a market-hours schedule, but guard against holidays
    # and early closes using Alpaca's authoritative clock.
    clock = client.get_clock()
    if not clock.is_open:
        logging.info("Market closed (next open %s) — skipping cycle.", clock.next_open)
        return {"skipped": True, "reason": "market_closed"}

    summary = run_one_cycle(client, _CONFIG_PATH)
    logging.info("Cycle summary: %s", summary)
    return {"skipped": False, **summary}
