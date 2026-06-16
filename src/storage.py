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
from decimal import Decimal
from pathlib import Path

import yaml

_CONFIG_DIR = Path(__file__).parent.parent / "config"
_WATERMARK_FILE = _CONFIG_DIR / "watermarks.json"
_LEDGER_FILE = _CONFIG_DIR / "spending_ledger.json"
_SETTINGS_FILE = _CONFIG_DIR / "settings.yaml"

_EMPTY_LEDGER = {"entries": [], "last_reset": {}}

# DynamoDB partition keys (single-table design). Watermarks are stored one item
# per symbol (pk = "wm#<symbol>") so peaks can be updated atomically; the ledger
# and settings stay single JSON-string blobs.
_WM_PREFIX = "wm#"
_PK_LEDGER = "ledger"
_PK_SETTINGS = "config"


class StorageBackend(ABC):
    """Read/write bot state. Watermarks are per-symbol (atomic peak ratchet);
    ledger and settings are single dict blobs."""

    # ── watermarks (per-symbol) ──────────────────────────────────────────
    @abstractmethod
    def read_watermark(self, symbol: str) -> dict | None: ...

    @abstractmethod
    def write_watermark(self, symbol: str, entry: dict) -> None: ...

    @abstractmethod
    def bump_watermark_high(self, symbol: str, price: float, updated_at: str) -> float:
        """Atomically set high = max(high, price); return the resulting high."""

    @abstractmethod
    def bump_watermark_recent_high(self, symbol: str, price: float, updated_at: str) -> float:
        """Atomically set recent_high = max(recent_high, price); return the result."""

    @abstractmethod
    def delete_watermark(self, symbol: str) -> None: ...

    @abstractmethod
    def list_watermarks(self) -> dict[str, dict]: ...

    # ── ledger + settings (single blob each) ─────────────────────────────
    @abstractmethod
    def load_ledger(self) -> dict: ...

    @abstractmethod
    def save_ledger(self, data: dict) -> None: ...

    @abstractmethod
    def load_settings(self, config_path=None) -> dict: ...

    @abstractmethod
    def save_settings(self, data: dict) -> None: ...


class LocalBackend(StorageBackend):
    """JSON/YAML files under config/ — the original file-based behaviour.

    Watermarks live in one JSON file keyed by symbol; since the local CLI is
    single-process the read-modify-write per op is effectively atomic.
    """

    def _load_wm(self) -> dict:
        if _WATERMARK_FILE.exists():
            with open(_WATERMARK_FILE, "r") as f:
                return json.load(f)
        return {}

    def _save_wm(self, data: dict) -> None:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_WATERMARK_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def read_watermark(self, symbol: str) -> dict | None:
        return self._load_wm().get(symbol)

    def write_watermark(self, symbol: str, entry: dict) -> None:
        data = self._load_wm()
        cur = data.get(symbol, {})
        cur.update({k: v for k, v in entry.items() if v is not None})
        data[symbol] = cur
        self._save_wm(data)

    def bump_watermark_high(self, symbol: str, price: float, updated_at: str) -> float:
        data = self._load_wm()
        entry = data.get(symbol, {"high": 0.0})
        if price > entry.get("high", 0.0):
            entry["high"] = price
            entry["updated_at"] = updated_at
            data[symbol] = entry
            self._save_wm(data)
        return data.get(symbol, {}).get("high", price)

    def bump_watermark_recent_high(self, symbol: str, price: float, updated_at: str) -> float:
        data = self._load_wm()
        entry = data.get(symbol, {"recent_high": 0.0})
        if price > entry.get("recent_high", 0.0):
            entry["recent_high"] = price
            entry["updated_at"] = updated_at
            data[symbol] = entry
            self._save_wm(data)
        return data.get(symbol, {}).get("recent_high", price)

    def delete_watermark(self, symbol: str) -> None:
        data = self._load_wm()
        if data.pop(symbol, None) is not None:
            self._save_wm(data)

    def list_watermarks(self) -> dict[str, dict]:
        return self._load_wm()

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

    @staticmethod
    def _wm_entry(item: dict) -> dict:
        return {
            "high": float(item.get("high", 0.0)),
            "recent_high": float(item.get("recent_high", 0.0)),
            "since": item.get("since"),
            "updated_at": item.get("updated_at"),
            "reconciled": item.get("reconciled"),
        }

    def read_watermark(self, symbol: str) -> dict | None:
        resp = self._table.get_item(Key={"pk": _WM_PREFIX + symbol})
        item = resp.get("Item")
        return self._wm_entry(item) if item else None

    def write_watermark(self, symbol: str, entry: dict) -> None:
        item = {"pk": _WM_PREFIX + symbol}
        if entry.get("high") is not None:
            item["high"] = Decimal(str(entry["high"]))
        if entry.get("recent_high") is not None:
            item["recent_high"] = Decimal(str(entry["recent_high"]))
        for k in ("since", "updated_at", "reconciled"):
            if entry.get(k) is not None:
                item[k] = entry[k]
        self._table.put_item(Item=item)

    def bump_watermark_high(self, symbol: str, price: float, updated_at: str) -> float:
        from botocore.exceptions import ClientError
        try:
            # Atomic ratchet: only writes when the new price is a strict new peak,
            # so concurrent writers (trading Lambda + any other caller) can't lose
            # each other's updates.
            self._table.update_item(
                Key={"pk": _WM_PREFIX + symbol},
                UpdateExpression="SET high = :p, updated_at = :t",
                ConditionExpression="attribute_not_exists(high) OR high < :p",
                ExpressionAttributeValues={":p": Decimal(str(price)), ":t": updated_at},
            )
            return price
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                cur = self.read_watermark(symbol)
                return cur["high"] if cur else price
            raise

    def bump_watermark_recent_high(self, symbol: str, price: float, updated_at: str) -> float:
        from botocore.exceptions import ClientError
        try:
            # Atomic rolling-high ratchet for buy-the-dip — mirrors
            # bump_watermark_high but on the recent_high attribute. (Decay of the
            # rolling window happens via reconcile, not here.)
            self._table.update_item(
                Key={"pk": _WM_PREFIX + symbol},
                UpdateExpression="SET recent_high = :p, updated_at = :t",
                ConditionExpression="attribute_not_exists(recent_high) OR recent_high < :p",
                ExpressionAttributeValues={":p": Decimal(str(price)), ":t": updated_at},
            )
            return price
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                cur = self.read_watermark(symbol)
                return cur["recent_high"] if cur else price
            raise

    def delete_watermark(self, symbol: str) -> None:
        self._table.delete_item(Key={"pk": _WM_PREFIX + symbol})

    def list_watermarks(self) -> dict[str, dict]:
        from boto3.dynamodb.conditions import Attr
        out: dict[str, dict] = {}
        kwargs = {"FilterExpression": Attr("pk").begins_with(_WM_PREFIX)}
        while True:
            resp = self._table.scan(**kwargs)
            for item in resp.get("Items", []):
                out[item["pk"][len(_WM_PREFIX):]] = self._wm_entry(item)
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return out

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
