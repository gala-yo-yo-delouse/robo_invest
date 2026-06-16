"""Telegram notification sender for trade alerts."""

import os
import urllib.request
import urllib.parse
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()


def _env_prefix() -> str:
    """A leading tag identifying which stack sent this message.

    dev and prod share one Telegram chat, so every alert is prefixed with its
    environment. prod/live is flagged loudly (real money); everything else
    (dev/paper, local CLI) is marked paper. Read at call time so the value
    hydrated from env after import is picked up.
    """
    env = (os.getenv("ROBOTRADE_ENV") or "").lower()
    money = (os.getenv("ALPACA_ENV") or "").lower()
    if env == "prod" or money == "live":
        return "🔴 <b>[PROD · LIVE]</b>\n"
    label = env.upper() if env else "LOCAL"
    return f"🧪 <b>[{label} · PAPER]</b>\n"


def _send(text: str):
    """Send a message via Telegram Bot API.

    Credentials are read at call time (not import time) so that values loaded
    into the environment after import — e.g. from Secrets Manager in Lambda —
    are picked up.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": _env_prefix() + text,
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


def notify_test():
    _send(
        f"✅ <b>Cloud wiring test</b>\n"
        f"Telegram notifications are live from the serverless stack.\n"
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )


def notify_summary(total_orders: int, total_value: float):
    _send(
        f"📊 <b>Cycle Complete</b>\n"
        f"Orders: {total_orders} | Total: ${total_value:,.2f}\n"
        f"{datetime.now().strftime('%H:%M')}"
    )
