"""Load Alpaca credentials from AWS Secrets Manager into the environment.

Locally, AlpacaClient reads ALPACA_* from .env (via python-dotenv) and this is
a no-op. In Lambda, ALPACA_ENV ("paper" | "live") selects the secret
`robotrade/alpaca-<env>`, whose JSON value holds ALPACA_API_KEY /
ALPACA_SECRET_KEY / ALPACA_BASE_URL; we fetch it once at cold start and populate
os.environ so AlpacaClient works unchanged. Flip paper↔live by changing the one
env var — secret values are never touched. (ALPACA_SECRET_ARN is still honoured
as a fallback for direct ARN wiring.)
"""

import json
import os


def _secret_id() -> str | None:
    env = os.getenv("ALPACA_ENV")
    if env:
        return f"robotrade/alpaca-{env}"
    return os.getenv("ALPACA_SECRET_ARN")


def _load_secret_json_into_env(secret_id: str) -> None:
    import boto3

    client = boto3.client("secretsmanager")
    try:
        secret = client.get_secret_value(SecretId=secret_id)
    except client.exceptions.ResourceNotFoundException:
        return
    try:
        data = json.loads(secret["SecretString"])
    except (ValueError, KeyError):
        return
    for key, value in data.items():
        os.environ[key] = str(value)


def load_telegram_into_env() -> None:
    """Hydrate TELEGRAM_* from the robotrade/telegram secret, if it exists.

    Optional — if the secret is absent or empty, notifications simply no-op.
    """
    if os.getenv("STORAGE_BACKEND", "local").lower() != "dynamodb":
        return  # local runs read TELEGRAM_* from .env
    _load_secret_json_into_env("robotrade/telegram")


def load_secrets_into_env() -> None:
    """Hydrate os.environ from the selected Secrets Manager secret, if any."""
    secret_id = _secret_id()
    if not secret_id:
        return

    import boto3

    secret = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
    try:
        data = json.loads(secret["SecretString"])
    except (ValueError, KeyError):
        # Secret not populated with real JSON credentials yet — leave env as-is
        # so callers fail later with a clear Alpaca connection error instead of
        # an opaque JSON decode error.
        return
    for key, value in data.items():
        os.environ[key] = str(value)
