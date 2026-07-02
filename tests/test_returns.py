"""Unit tests for the period-return math (src/returns.py).

Pure functions, no Alpaca. Run: ``.venv/bin/python -m pytest tests/test_returns.py``
(or just ``.venv/bin/python tests/test_returns.py`` for the asserts).
"""

from datetime import date

from src.returns import compute_window, external_flows, realized_pnl_from_fills


def _d(s: str) -> date:
    return date.fromisoformat(s)


def test_realized_average_cost():
    # Buy 10@10 then 10@20 (avg 15), sell 5@25 → realized (25-15)*5 = 50.
    fills = [
        {"date": _d("2026-01-01"), "symbol": "X", "side": "buy", "qty": 10, "price": 10},
        {"date": _d("2026-01-02"), "symbol": "X", "side": "buy", "qty": 10, "price": 20},
        {"date": _d("2026-01-03"), "symbol": "X", "side": "sell", "qty": 5, "price": 25},
    ]
    out = realized_pnl_from_fills(fills)
    assert out == [(_d("2026-01-03"), 50.0)]


def test_external_flows_absorbs_opening_deposit():
    # $100k opening deposit is already in the $100k baseline → not a flow.
    flows = external_flows([(_d("2026-03-23"), 100_000.0)], baseline_equity=100_000.0)
    assert flows == []
    # A later top-up beyond the baseline survives as a real flow.
    flows = external_flows(
        [(_d("2026-03-23"), 100_000.0), (_d("2026-05-01"), 5_000.0)],
        baseline_equity=100_000.0,
    )
    assert flows == [(_d("2026-05-01"), 5_000.0)]


def test_deposit_does_not_inflate_return():
    # The screenshot bug: start $1000, add $1000 mid-window, end $2003.
    # Return must reflect only the ~$3 of appreciation, not the +100% deposit.
    flows = external_flows(
        [(_d("2026-01-01"), 1_000.0), (_d("2026-04-01"), 1_000.0)],
        baseline_equity=1_000.0,
    )
    assert flows == [(_d("2026-04-01"), 1_000.0)]
    r = compute_window(
        base_date=_d("2026-01-01"), end_date=_d("2026-07-01"),
        begin_equity=1_000.0, end_equity=2_003.0,
        transfers=flows, realized_events=[], income_events=[],
    )
    # total = 2003 - 1000 - 1000 = 3 (not +1003).
    assert r["total"] == 3.0
    assert 0 < r["pct"] < 1  # small positive, nowhere near +100%.


def test_realized_plus_unrealized_reconciles_and_dividends_are_realized():
    # Sell realized +50, dividend +10 (income), and price appreciation as residual.
    r = compute_window(
        base_date=_d("2026-01-01"), end_date=_d("2026-07-01"),
        begin_equity=1_000.0, end_equity=1_100.0,
        transfers=[],
        realized_events=[(_d("2026-03-01"), 50.0)],
        income_events=[(_d("2026-04-01"), 10.0)],  # dividend → realized income
    )
    assert r["total"] == 100.0
    assert r["realized"] == 60.0            # 50 sell + 10 dividend
    assert r["unrealized"] == 40.0          # residual appreciation
    assert r["realized"] + r["unrealized"] == r["total"]


def test_modified_dietz_time_weights_flow():
    # $100 in at the very end contributes ~nothing to the denominator.
    r = compute_window(
        base_date=_d("2026-01-01"), end_date=_d("2026-01-11"),
        begin_equity=100.0, end_equity=210.0,
        transfers=[(_d("2026-01-10"), 100.0)],  # 1 of 10 days remaining → weight 0.1
        realized_events=[], income_events=[],
    )
    # total = 210 - 100 - 100 = 10; denom = 100 + 100*0.1 = 110; pct = 9.09%.
    assert r["total"] == 10.0
    assert r["pct"] == 9.09


def test_empty_window_returns_none():
    assert compute_window(
        base_date=_d("2026-07-01"), end_date=_d("2026-07-01"),
        begin_equity=100.0, end_equity=100.0,
        transfers=[], realized_events=[], income_events=[],
    ) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok {name}")
    print("all passed")
