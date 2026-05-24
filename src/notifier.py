"""Telegram notification sender for trade alerts."""

import os
import urllib.request
import urllib.parse
import json
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def _send(text: str):
    """Send a message via Telegram Bot API."""
    if not BOT_TOKEN or not CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        }).encode()
        urllib.request.urlopen(url, data, timeout=10)
    except Exception:
        pass  # Don't let notification failures break the runner


def notify_started(interval: int):
    _send(
        f"🟢 <b>Investment Assistant Started</b>\n"
        f"Interval: {interval} min | {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )


def notify_stopped():
    _send(
        f"🔴 <b>Investment Assistant Stopped</b>\n"
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )


def notify_order(side: str, symbol: str, qty: float, value: float, reason: str, status: str):
    icon = "🔴" if side == "sell" else "🟢"
    _send(
        f"{icon} <b>{side.upper()} {symbol}</b>\n"
        f"Qty: {qty:.4f} | ~${value:,.2f}\n"
        f"Reason: {reason}\n"
        f"Status: {status}"
    )


def notify_error(message: str):
    _send(f"⚠️ <b>Error</b>\n{message}")


def notify_summary(total_orders: int, total_value: float):
    _send(
        f"📊 <b>Cycle Complete</b>\n"
        f"Orders: {total_orders} | Total: ${total_value:,.2f}\n"
        f"{datetime.now().strftime('%H:%M')}"
    )
