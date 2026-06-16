"""One-time seed: copy config/settings.yaml into the DynamoDB Settings item.

Run after the stack is deployed and the robotrade-state table exists:

    AWS_PROFILE=robotrade-admin STORAGE_BACKEND=dynamodb \
        .venv/bin/python scripts/seed_settings.py

Idempotent — re-running just overwrites the config item with the current YAML.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage import DynamoBackend, LocalBackend


def main():
    local = LocalBackend()
    settings = local.load_settings()
    n = len(settings.get("strategies", {}))

    # Safety: a fresh prod deploy must come up with trading OFF so the operator
    # configures strategies and explicitly enables it from the dashboard. dev
    # keeps the YAML value (paper account, safe to auto-run).
    env = os.getenv("ROBOTRADE_ENV", "dev").lower()
    if env == "prod":
        settings.setdefault("guidelines", {})["trading_enabled"] = False

    table = os.getenv("STATE_TABLE", "robotrade-state")
    DynamoBackend(table).save_settings(settings)
    enabled = settings.get("guidelines", {}).get("trading_enabled", True)
    print(f"Seeded {n} strategies + guidelines into '{table}' (config item).")
    print(f"  env={env}  trading_enabled={enabled}"
          + ("  ← enable from the dashboard when ready" if not enabled else ""))


if __name__ == "__main__":
    main()
