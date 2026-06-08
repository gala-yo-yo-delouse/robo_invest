"""Frontend-facing Lambda: live reads + settings writes for the dashboard.

Invoked by AppSync (Amplify Data) custom queries/mutations. Routes on the
GraphQL field name (event['info']['fieldName']) or an explicit event['action']
for direct invokes. All trading logic is reused from src/ — this handler only
serialises results to JSON-friendly dicts.

Fields:
  getPortfolio  -> account totals + holdings
  getSignals    -> current trade signals (what the bot would do now)
  getProfiles   -> live price + 90-day candles per held symbol
  getStatus     -> budget consumption vs limits
  getSettings   -> the editable config (guidelines + strategies)
  saveSettings  -> validate + persist config (arguments.settings)
"""

import logging

from src.alpaca_client import AlpacaClient
from src.config_loader import build_guidelines, build_strategies, load_config
from src.guidelines import (
    get_last_dca_dates,
    load_guidelines_with_spending,
)
from src.models import BuyType, OrderSide, StrategyMode
from src.secrets import load_secrets_into_env
from src.storage import get_backend
from src.strategy import StrategyEngine

logging.getLogger().setLevel(logging.INFO)

_CONFIG_PATH = "config/settings.yaml"


# ── serialisers ───────────────────────────────────────────────────────

def _holding(h) -> dict:
    return {
        "symbol": h.symbol,
        "description": h.description,
        "quantity": h.quantity,
        "lastPrice": h.last_price,
        "currentValue": h.current_value,
        "costBasisTotal": h.cost_basis_total,
        "averageCostBasis": h.average_cost_basis,
        "gainLossDollar": h.total_gain_loss_dollar,
        "gainLossPercent": h.total_gain_loss_percent,
        "percentOfAccount": h.percent_of_account,
    }


def _signal(s) -> dict:
    return {
        "symbol": s.symbol,
        "side": s.side.value,
        "buyType": s.buy_type.value,
        "quantity": s.quantity,
        "estimatedValue": s.estimated_value,
        "limitPrice": s.limit_price,
        "reason": s.reason,
        "priority": s.priority,
        "strategyMode": s.strategy_mode.value if s.strategy_mode else None,
    }


def _budget(b) -> dict:
    return {
        "maxDaily": b.max_daily,
        "maxWeekly": b.max_weekly,
        "maxMonthly": b.max_monthly,
        "maxSingleOrder": b.max_single_order,
        "spentToday": b.spent_today,
        "spentThisWeek": b.spent_this_week,
        "spentThisMonth": b.spent_this_month,
    }


# ── field handlers ────────────────────────────────────────────────────

def _get_portfolio(client) -> dict:
    p = client.build_portfolio()
    return {
        "accountId": p.account_id,
        "totalValue": p.total_value,
        "investedValue": p.invested_value,
        "cashBalance": p.cash_balance,
        "cashPct": p.cash_pct,
        "holdings": [_holding(h) for h in sorted(
            p.holdings.values(), key=lambda x: x.current_value, reverse=True)],
    }


def _get_signals(client) -> list:
    p = client.build_portfolio()
    config = load_config(_CONFIG_PATH)
    guidelines = load_guidelines_with_spending(build_guidelines(config))
    strategies = build_strategies(config)
    engine = StrategyEngine(
        p, strategies, guidelines,
        price_fetcher=client.get_current_price,
        last_dca_dates=get_last_dca_dates(),
    )
    return [_signal(s) for s in engine.evaluate_all()]


def _get_profiles(client) -> list:
    from datetime import datetime, timedelta

    p = client.build_portfolio()
    start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    out = []
    for sym in sorted(p.holdings.keys()):
        h = p.holdings[sym]
        try:
            bars = [
                {"date": str(b.t)[:10], "open": float(b.o), "high": float(b.h),
                 "low": float(b.l), "close": float(b.c), "volume": int(b.v)}
                for b in client.api.get_bars(sym, "1Day", start=start)
            ]
        except Exception:
            bars = []
        out.append({
            "symbol": sym,
            "description": h.description,
            "livePrice": client.get_current_price(sym) or h.last_price,
            "avgCost": h.average_cost_basis,
            "quantity": h.quantity,
            "bars": bars,
        })
    return out


def _get_status() -> dict:
    config = load_config(_CONFIG_PATH)
    g = load_guidelines_with_spending(build_guidelines(config))
    return {
        "tradingEnabled": g.trading_enabled,
        "dca": _budget(g.dca),
        "strategy": _budget(g.strategy),
    }


def _save_settings(settings: dict) -> dict:
    if not isinstance(settings, dict) or "strategies" not in settings:
        raise ValueError("settings must be an object with a 'strategies' key")
    # Validate by building the dataclass tree — raises on a bad shape/mode.
    build_guidelines(settings)
    build_strategies(settings)
    get_backend().save_settings(settings)
    return settings


# ── router ────────────────────────────────────────────────────────────

def handler(event, context):
    field = (event.get("info", {}).get("fieldName")
             or event.get("action"))
    args = event.get("arguments", event) or {}
    logging.info("query_handler field=%s", field)

    # Settings/status read from DynamoDB only — no Alpaca connection needed,
    # so they work even before the Alpaca secret is populated.
    if field == "getSettings":
        return get_backend().load_settings()
    if field == "saveSettings":
        return _save_settings(args.get("settings"))
    if field == "getStatus":
        return _get_status()

    # Live views need Alpaca — load credentials from Secrets Manager now.
    load_secrets_into_env()
    client = AlpacaClient()
    if field == "getPortfolio":
        return _get_portfolio(client)
    if field == "getSignals":
        return _get_signals(client)
    if field == "getProfiles":
        return _get_profiles(client)

    raise ValueError(f"Unknown field/action: {field!r}")
