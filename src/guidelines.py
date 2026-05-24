"""Investment guidelines engine — enforces spending limits and rules."""

import json
from datetime import datetime, date, timedelta
from pathlib import Path

from .models import BuyType, InvestmentGuidelines


LEDGER_FILE = Path(__file__).parent.parent / "config" / "spending_ledger.json"


def _load_ledger() -> dict:
    """Load the spending ledger from disk."""
    if LEDGER_FILE.exists():
        with open(LEDGER_FILE, "r") as f:
            return json.load(f)
    return {"entries": [], "last_reset": {}}


def _save_ledger(ledger: dict):
    """Save the spending ledger to disk."""
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_FILE, "w") as f:
        json.dump(ledger, f, indent=2, default=str)


def load_guidelines_with_spending(guidelines: InvestmentGuidelines) -> InvestmentGuidelines:
    """Load spending history and update each budget's running totals."""
    ledger = _load_ledger()
    today = date.today()

    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    # Accumulators keyed by buy_type
    totals = {
        "dca": {"today": 0.0, "week": 0.0, "month": 0.0},
        "strategy": {"today": 0.0, "week": 0.0, "month": 0.0},
    }

    for entry in ledger.get("entries", []):
        if entry.get("side", "buy") != "buy":
            continue
        entry_date = date.fromisoformat(entry["date"])
        amount = entry["amount"]
        buy_type = entry.get("buy_type", "strategy")  # Legacy entries default to strategy

        if buy_type not in totals:
            continue

        if entry_date == today:
            totals[buy_type]["today"] += amount
        if entry_date >= week_start:
            totals[buy_type]["week"] += amount
        if entry_date >= month_start:
            totals[buy_type]["month"] += amount

    guidelines.dca.spent_today = totals["dca"]["today"]
    guidelines.dca.spent_this_week = totals["dca"]["week"]
    guidelines.dca.spent_this_month = totals["dca"]["month"]

    guidelines.strategy.spent_today = totals["strategy"]["today"]
    guidelines.strategy.spent_this_week = totals["strategy"]["week"]
    guidelines.strategy.spent_this_month = totals["strategy"]["month"]

    return guidelines


def record_spend(amount: float, symbol: str, side: str, buy_type: BuyType):
    """Record a completed trade in the spending ledger."""
    ledger = _load_ledger()
    ledger["entries"].append({
        "date": date.today().isoformat(),
        "amount": amount,
        "symbol": symbol,
        "side": side,
        "buy_type": buy_type.value,
        "timestamp": datetime.now().isoformat(),
    })
    _save_ledger(ledger)


def get_last_dca_dates() -> dict[str, date]:
    """Return the most recent DCA execution date per symbol from the ledger."""
    ledger = _load_ledger()
    last_dates: dict[str, date] = {}
    for entry in ledger.get("entries", []):
        if entry.get("buy_type") == "dca" and entry.get("side", "buy") == "buy":
            entry_date = date.fromisoformat(entry["date"])
            if entry["symbol"] not in last_dates or entry_date > last_dates[entry["symbol"]]:
                last_dates[entry["symbol"]] = entry_date
    return last_dates


def get_today_executed() -> set[tuple[str, str, str]]:
    """Return set of (symbol, side, buy_type) already executed today."""
    ledger = _load_ledger()
    today = date.today()
    executed = set()
    for entry in ledger.get("entries", []):
        if date.fromisoformat(entry["date"]) == today:
            executed.add((entry["symbol"], entry.get("side", "buy"), entry.get("buy_type", "strategy")))
    return executed


def _print_budget(label: str, budget):
    """Print a single budget's status."""
    print(f"  {label}:")
    print(f"    Daily:   ${budget.spent_today:>8,.2f} / ${budget.max_daily:>8,.2f}")
    if budget.max_weekly > 0:
        print(f"    Weekly:  ${budget.spent_this_week:>8,.2f} / ${budget.max_weekly:>8,.2f}")
    if budget.max_monthly > 0:
        print(f"    Monthly: ${budget.spent_this_month:>8,.2f} / ${budget.max_monthly:>8,.2f}")
    if budget.max_single_order > 0:
        print(f"    Max single order: ${budget.max_single_order:>8,.2f}")


def print_guidelines_status(guidelines: InvestmentGuidelines):
    """Print current spending status against limits."""
    print(f"\n  Investment Guidelines Status:")
    print(f"  {'─'*50}")
    _print_budget("DCA (scheduled buys)", guidelines.dca)
    print()
    _print_budget("Strategy (dip buys)", guidelines.strategy)
    print(f"\n  Trading enabled:  {guidelines.trading_enabled}")
    print()
