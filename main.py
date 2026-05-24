#!/usr/bin/env python3
"""Investment Assistant — CLI entry point.

Usage:
    python main.py portfolio          Show portfolio summary (live from Alpaca)
    python main.py signals            Evaluate strategies and show trade signals
    python main.py profiles           Auto-generate security profiles via Alpaca
    python main.py status             Show guidelines spending status
    python main.py execute            Execute pending trade signals (with confirmation)
    python main.py run                Continuous mode: evaluate & execute every 5 min during market hours
"""

import argparse
import sys
from pathlib import Path

from src.alpaca_client import AlpacaClient
from src.config_loader import build_guidelines, build_strategies, load_config
from src.guidelines import load_guidelines_with_spending, print_guidelines_status
from src.portfolio import print_portfolio_summary
from src.strategy import StrategyEngine, print_signals


CONFIG_PATH = Path(__file__).parent / "config" / "settings.yaml"


def _get_portfolio():
    """Build live portfolio from Alpaca."""
    client = AlpacaClient()
    return client, client.build_portfolio()


def cmd_portfolio(args):
    """Display portfolio summary."""
    _, portfolio = _get_portfolio()
    print_portfolio_summary(portfolio)


def cmd_signals(args):
    """Evaluate strategies and display trade signals."""
    client, portfolio = _get_portfolio()
    config = load_config(args.config)
    guidelines = build_guidelines(config)
    strategies = build_strategies(config)

    engine = StrategyEngine(portfolio, strategies, guidelines,
                            price_fetcher=client.get_current_price)
    signals = engine.evaluate_all()

    print_portfolio_summary(portfolio)
    print_guidelines_status(engine.guidelines)
    print_signals(signals)

    return signals


def cmd_profiles(args):
    """Auto-generate security profiles via Alpaca market data."""
    _, portfolio = _get_portfolio()

    print(f"\n  Generating profiles for {len(portfolio.holdings)} securities...\n")

    client = AlpacaClient()
    for symbol, holding in sorted(portfolio.holdings.items()):
        profile = client.get_security_profile(
            symbol,
            quantity_held=holding.quantity,
            avg_cost=holding.average_cost_basis,
            gain_loss_pct=holding.total_gain_loss_percent,
        )
        print(f"  {'─'*55}")
        print(f"  {profile.symbol} — {profile.name}")
        print(f"  Type: {profile.asset_type.value}  |  Sector: {profile.sector or 'N/A'}")
        print(f"  Price: ${profile.current_price:,.2f}  "
              f"(Day: ${profile.day_low:,.2f}–${profile.day_high:,.2f})")
        print(f"  52-wk: ${profile.week_52_low:,.2f}–${profile.week_52_high:,.2f}  "
              f"|  Avg Vol: {profile.avg_volume:,}")
        print(f"  Holding: {profile.quantity_held:.4f} shares  "
              f"|  Avg Cost: ${profile.avg_cost:,.2f}  "
              f"|  P/L: {profile.total_gain_loss_pct:+.2f}%")
    print(f"  {'─'*55}\n")


def cmd_status(args):
    """Show investment guidelines spending status."""
    config = load_config(args.config)
    guidelines = build_guidelines(config)
    guidelines = load_guidelines_with_spending(guidelines)
    print_guidelines_status(guidelines)


def cmd_execute(args):
    """Execute trade signals with user confirmation."""
    from src.guidelines import record_spend
    from src.models import OrderSide

    signals = cmd_signals(args)
    if not signals:
        print("  Nothing to execute.")
        return

    print("\n  ⚠  PAPER TRADING MODE")
    confirm = input("  Execute these trades? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("  Aborted.")
        return

    client = AlpacaClient()
    for signal in signals:
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
            print(f"  ✓ {signal.side.value.upper()} {signal.quantity} {signal.symbol} "
                  f"— Order {result['status']} ({order_tag}) (ID: {result['id'][:8]}...)")
            if signal.side == OrderSide.BUY:
                record_spend(signal.estimated_value, signal.symbol, "buy", signal.buy_type)
        except Exception as e:
            print(f"  ✗ Failed: {signal.symbol} — {e}")

    print()


def cmd_run(args):
    """Run continuous mode — evaluate and execute during market hours."""
    from src.runner import run
    run(config_path=args.config, interval_minutes=args.interval)


def main():
    parser = argparse.ArgumentParser(description="Investment Assistant")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH,
                        help="Path to settings YAML")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("portfolio", help="Show portfolio summary")
    sub.add_parser("signals", help="Evaluate and show trade signals")
    sub.add_parser("profiles", help="Auto-generate security profiles")
    sub.add_parser("status", help="Show guidelines spending status")
    sub.add_parser("execute", help="Execute trade signals")

    run_parser = sub.add_parser("run", help="Continuous mode: evaluate & execute during market hours")
    run_parser.add_argument("--interval", type=int, default=5,
                            help="Minutes between evaluations (default: 5)")

    args = parser.parse_args()

    commands = {
        "portfolio": cmd_portfolio,
        "signals": cmd_signals,
        "profiles": cmd_profiles,
        "status": cmd_status,
        "execute": cmd_execute,
        "run": cmd_run,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
