"""Portfolio display utilities."""

from .models import Portfolio


def print_portfolio_summary(portfolio: Portfolio):
    """Print a formatted portfolio summary."""
    print(f"\n{'='*70}")
    print(f"  PORTFOLIO SUMMARY — Account {portfolio.account_id}")
    print(f"{'='*70}")
    print(f"  Total Value:    ${portfolio.total_value:>12,.2f}")
    print(f"  Cash Balance:   ${portfolio.cash_balance:>12,.2f}  ({portfolio.cash_pct:.1f}%)")
    print(f"  Invested:       ${portfolio.invested_value:>12,.2f}")
    print(f"{'='*70}")
    print(f"  {'Symbol':<8} {'Qty':>8} {'Price':>10} {'Value':>12} {'Gain/Loss':>12} {'%':>8}")
    print(f"  {'-'*62}")

    sorted_holdings = sorted(
        portfolio.holdings.values(),
        key=lambda h: h.current_value,
        reverse=True,
    )
    for h in sorted_holdings:
        sign = "+" if h.total_gain_loss_dollar >= 0 else ""
        print(
            f"  {h.symbol:<8} {h.quantity:>8.2f} "
            f"${h.last_price:>9.2f} "
            f"${h.current_value:>11,.2f} "
            f"{sign}${h.total_gain_loss_dollar:>10,.2f} "
            f"{sign}{h.total_gain_loss_percent:>6.1f}%"
        )
    print(f"{'='*70}\n")
