"""High watermark tracker — persists the peak price for each security.

Used by the trailing stop logic to know the highest price reached
since tracking began, so the stop can trail the peak downward.
"""

import json
from datetime import datetime
from pathlib import Path


WATERMARK_FILE = Path(__file__).parent.parent / "config" / "watermarks.json"


def _load_watermarks() -> dict:
    if WATERMARK_FILE.exists():
        with open(WATERMARK_FILE, "r") as f:
            return json.load(f)
    return {}


def _save_watermarks(data: dict):
    WATERMARK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(WATERMARK_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_high_watermark(symbol: str) -> float:
    """Return the recorded peak price for a symbol, or 0.0 if not tracked."""
    return _load_watermarks().get(symbol, {}).get("high", 0.0)


def update_high_watermark(symbol: str, current_price: float) -> float:
    """Update the high watermark if current_price is a new peak.

    Returns the (possibly updated) high watermark.
    """
    data = _load_watermarks()
    entry = data.get(symbol, {"high": 0.0})

    if current_price > entry.get("high", 0.0):
        entry["high"] = current_price
        entry["updated_at"] = datetime.now().isoformat()
        data[symbol] = entry
        _save_watermarks(data)

    return entry["high"]


def reset_watermark(symbol: str):
    """Reset tracking for a symbol (e.g. after the position is sold)."""
    data = _load_watermarks()
    data.pop(symbol, None)
    _save_watermarks(data)


def get_all_watermarks() -> dict[str, float]:
    """Return all tracked watermarks as {symbol: high_price}."""
    return {sym: info["high"] for sym, info in _load_watermarks().items()}
