"""Pluggable persistence backend — local JSON files or DynamoDB.

The bot keeps three small state blobs:
  - watermarks : peak price per symbol (trailing-stop tracking)
  - ledger     : executed-trade log (budget accounting + dedup)
  - settings   : the trading config (guidelines + per-security strategies)

Locally these are JSON files under config/ (the original behaviour, so the
CLI and Streamlit dashboard keep working offline with no AWS dependency).
In the cloud they become three items in a single DynamoDB table, which lets
the Lambda read/write state without a persistent filesystem and lets the
frontend edit settings.

Backend selection is by the STORAGE_BACKEND env var ("local" | "dynamodb"),
defaulting to "local". Each blob is stored as a JSON string so we never have
to wrestle DynamoDB's Decimal/float number type.
"""

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path

import yaml

_CONFIG_DIR = Path(__file__).parent.parent / "config"
_WATERMARK_FILE = _CONFIG_DIR / "watermarks.json"
_LEDGER_FILE = _CONFIG_DIR / "spending_ledger.json"
_SETTINGS_FILE = _CONFIG_DIR / "settings.yaml"

_EMPTY_LEDGER = {"entries": [], "last_reset": {}}

# DynamoDB partition keys for the three blobs (single-table design).
_PK_WATERMARKS = "watermarks"
_PK_LEDGER = "ledger"
_PK_SETTINGS = "config"


class StorageBackend(ABC):
    """Read/write the three state blobs. Each returns/accepts a plain dict."""

    @abstractmethod
    def load_watermarks(self) -> dict: ...

    @abstractmethod
    def save_watermarks(self, data: dict) -> None: ...

    @abstractmethod
    def load_ledger(self) -> dict: ...

    @abstractmethod
    def save_ledger(self, data: dict) -> None: ...

    @abstractmethod
    def load_settings(self, config_path=None) -> dict: ...

    @abstractmethod
    def save_settings(self, data: dict) -> None: ...


class LocalBackend(StorageBackend):
    """JSON/YAML files under config/ — the original file-based behaviour."""

    def load_watermarks(self) -> dict:
        if _WATERMARK_FILE.exists():
            with open(_WATERMARK_FILE, "r") as f:
                return json.load(f)
        return {}

    def save_watermarks(self, data: dict) -> None:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_WATERMARK_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def load_ledger(self) -> dict:
        if _LEDGER_FILE.exists():
            with open(_LEDGER_FILE, "r") as f:
                return json.load(f)
        return dict(_EMPTY_LEDGER)

    def save_ledger(self, data: dict) -> None:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_LEDGER_FILE, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def load_settings(self, config_path=None) -> dict:
        path = Path(config_path) if config_path else _SETTINGS_FILE
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with open(path, "r") as f:
            return yaml.safe_load(f)

    def save_settings(self, data: dict) -> None:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_SETTINGS_FILE, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)


class DynamoBackend(StorageBackend):
    """Single DynamoDB table, one item per blob, value held as a JSON string.

    Table name comes from STATE_TABLE (default "robotrade-state"); schema is a
    single partition key "pk" (string). boto3 is imported lazily so the local
    CLI never needs it installed.
    """

    def __init__(self, table_name: str | None = None):
        import boto3  # lazy — only needed in the cloud

        table_name = table_name or os.getenv("STATE_TABLE", "robotrade-state")
        self._table = boto3.resource("dynamodb").Table(table_name)

    def _get(self, pk: str, default):
        resp = self._table.get_item(Key={"pk": pk})
        item = resp.get("Item")
        if not item or "data" not in item:
            return default
        return json.loads(item["data"])

    def _put(self, pk: str, obj) -> None:
        self._table.put_item(Item={"pk": pk, "data": json.dumps(obj, default=str)})

    def load_watermarks(self) -> dict:
        return self._get(_PK_WATERMARKS, {})

    def save_watermarks(self, data: dict) -> None:
        self._put(_PK_WATERMARKS, data)

    def load_ledger(self) -> dict:
        return self._get(_PK_LEDGER, dict(_EMPTY_LEDGER))

    def save_ledger(self, data: dict) -> None:
        self._put(_PK_LEDGER, data)

    def load_settings(self, config_path=None) -> dict:
        data = self._get(_PK_SETTINGS, None)
        if data is None:
            raise RuntimeError(
                "Settings item not found in DynamoDB. Seed it first "
                "(scripts/seed_settings.py)."
            )
        return data

    def save_settings(self, data: dict) -> None:
        self._put(_PK_SETTINGS, data)


_backend: StorageBackend | None = None


def get_backend() -> StorageBackend:
    """Return the process-wide backend, selected by STORAGE_BACKEND env var."""
    global _backend
    if _backend is None:
        kind = os.getenv("STORAGE_BACKEND", "local").lower()
        _backend = DynamoBackend() if kind == "dynamodb" else LocalBackend()
    return _backend
