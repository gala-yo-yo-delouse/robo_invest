"""Continuous trading runner — evaluates and executes during market hours.

Runs on a loop (default every 5 minutes):
  1. Check if market is open via Alpaca clock API
  2. Build live portfolio from Alpaca positions
  3. Evaluate strategies → generate trade signals
  4. Dedup: skip signals already executed today
  5. Auto-execute remaining signals
  6. Sleep until next cycle (or until market opens if closed)
"""

import logging
import signal as signal_module
import time
from datetime import datetime, date
from pathlib import Path

from .alpaca_client import AlpacaClient
from .config_loader import load_config, build_guidelines, build_strategies
from .guidelines import (
    get_last_dca_dates,
    get_today_executed,
    load_guidelines_with_spending,
    record_spend,
)
from .models import BuyType, OrderSide, StrategyMode
from .notifier import notify_started, notify_stopped, notify_order, notify_error, notify_summary
from .strategy import StrategyEngine, print_signals
from .watermark import reset_watermark

LOG_PATH = Path(__file__).parent.parent / "logs" / "runner.log"


def _setup_logging():
    """Set up file logging for post-mortem diagnosis."""
    LOG_PATH.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_PATH),
        level=logging.INFO,
        format="%(asctime)s  %(levelname)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Also keep console output working
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    logging.getLogger().addHandler(console)


def _handle_sighup(signum, frame):
    """Ignore SIGHUP so the process survives terminal disconnects."""
    logging.info("Received SIGHUP — terminal disconnected, continuing...")


def run(config_path: Path, interval_minutes: int = 5):
    """Main run loop — evaluates and executes signals every N minutes during market hours."""
    _setup_logging()
    signal_module.signal(signal_module.SIGHUP, _handle_sighup)

    print(f"\n  Investment Assistant — Continuous Mode")
    print(f"  Interval: {interval_minutes} minutes | Paper trading")
    print(f"  Log: {LOG_PATH}")
    print(f"  Press Ctrl+C to stop")
    print(f"  {'─'*55}\n")

    logging.info("Started — interval=%d min, config=%s", interval_minutes, config_path)
    client = AlpacaClient()
    notify_started(interval_minutes)

    while True:
        try:
            clock = client.api.get_clock()

            if not clock.is_open:
                next_open = clock.next_open
                now = clock.timestamp
                wait_seconds = (next_open - now).total_seconds()

                if wait_seconds > 3600:
                    print(f"  [{_now()}] Market closed. Next open: "
                          f"{next_open.strftime('%Y-%m-%d %H:%M ET')}")
                    _sleep_until(next_open)
                else:
                    mins = max(1, int(wait_seconds / 60))
                    print(f"  [{_now()}] Market opens in ~{mins} min. Waiting...")
                    time.sleep(min(wait_seconds + 10, 60))
                continue

            run_one_cycle(client, config_path)

            print(f"  Next eval at ~{_add_minutes(interval_minutes)}.\n")
            time.sleep(interval_minutes * 60)

        except KeyboardInterrupt:
            print(f"\n  Stopped continuous mode.")
            logging.info("Stopped by KeyboardInterrupt")
            notify_stopped()
            break
        except Exception as e:
            print(f"\n  [{_now()}] Error: {e}")
            print(f"  Retrying in {interval_minutes} minutes...\n")
            logging.exception("Cycle error: %s", e)
            notify_error(str(e))
            time.sleep(interval_minutes * 60)


def run_one_cycle(client: AlpacaClient, config_path: Path) -> dict:
    """Evaluate strategies once and execute any new signals.

    This is the unit of work shared by continuous mode (called in a loop) and
    the EventBridge-triggered Lambda (called once per invocation). Assumes the
    market is open — the caller is responsible for the clock check. Returns a
    summary dict for logging / the Lambda response.
    """
    print(f"  [{_now()}] Evaluating signals...")

    # Build live portfolio from Alpaca positions
    portfolio = client.build_portfolio()
    print(f"  Portfolio: ${portfolio.total_value:,.2f} "
          f"({len(portfolio.holdings)} positions, "
          f"${portfolio.cash_balance:,.2f} cash)")

    # Reload config each cycle (picks up settings edits without restart)
    config = load_config(config_path)
    guidelines = build_guidelines(config)
    strategies = build_strategies(config)

    # DCA timing and dedup
    last_dca = get_last_dca_dates()
    today_executed = get_today_executed()

    # Evaluate
    engine = StrategyEngine(
        portfolio, strategies, guidelines,
        price_fetcher=client.get_current_price,
        last_dca_dates=last_dca,
    )
    signals = engine.evaluate_all()

    # Filter out signals already executed today
    new_signals = []
    for s in signals:
        key = (s.symbol, s.side.value, s.buy_type.value)
        if key not in today_executed:
            new_signals.append(s)
        else:
            print(f"    (skip) {s.symbol} {s.side.value} [{s.buy_type.value}] — already executed today")

    total_executed = 0
    total_value = 0.0
    if not new_signals:
        print(f"  No new signals.")
        logging.info("No new signals (portfolio=$%.2f, %d positions)",
                     portfolio.total_value, len(portfolio.holdings))
    else:
        print(f"  Executing {len(new_signals)} signal(s):")
        logging.info("Executing %d signal(s)", len(new_signals))
        for signal in new_signals:
            ok = _execute_signal(client, signal)
            if ok:
                total_executed += 1
                total_value += signal.estimated_value
        if total_executed > 0:
            logging.info("Executed %d orders, total=$%.2f", total_executed, total_value)
            notify_summary(total_executed, total_value)

    return {
        "portfolio_value": portfolio.total_value,
        "positions": len(portfolio.holdings),
        "signals_evaluated": len(signals),
        "signals_new": len(new_signals),
        "executed": total_executed,
        "executed_value": round(total_value, 2),
    }


def _execute_signal(client: AlpacaClient, signal) -> bool:
    """Execute a single trade signal and record it. Returns True on success."""
    try:
        order_type = "limit" if signal.limit_price else "market"
        result = client.submit_order(
            symbol=signal.symbol,
            qty=signal.quantity,
            side=signal.side,
            order_type=order_type,
            limit_price=signal.limit_price,
        )
        order_tag = f"limit @${signal.limit_price:.2f}" if signal.limit_price else "market"
        print(f"    ✓ {signal.side.value.upper()} {signal.quantity:.4f} "
              f"{signal.symbol} (~${signal.estimated_value:,.2f}) "
              f"— {signal.reason} [{result['status']}] ({order_tag})")

        record_spend(
            signal.estimated_value, signal.symbol,
            signal.side.value, signal.buy_type,
        )

        notify_order(
            signal.side.value, signal.symbol, signal.quantity,
            signal.estimated_value, signal.reason, result['status'],
        )

        # Reset watermark after profit protection sell so the cycle starts fresh
        if signal.side == OrderSide.SELL and signal.strategy_mode == StrategyMode.INCREASE_HOLDING:
            reset_watermark(signal.symbol)
            logging.info("Watermark reset for %s after profit protection sell", signal.symbol)

        return True
    except Exception as e:
        print(f"    ✗ FAILED {signal.symbol}: {e}")
        notify_error(f"Order failed: {signal.symbol} — {e}")
        return False


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _add_minutes(minutes: int) -> str:
    from datetime import timedelta
    return (datetime.now() + timedelta(minutes=minutes)).strftime("%H:%M:%S")


def _sleep_until(target):
    """Sleep until target time, checking every 60 seconds for interrupts."""
    while True:
        now = datetime.now(target.tzinfo)
        remaining = (target - now).total_seconds()
        if remaining <= 0:
            break
        time.sleep(min(remaining + 5, 60))
