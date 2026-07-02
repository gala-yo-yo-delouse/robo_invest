"""Period-return math: deposit-adjusted rate + realized/unrealized split.

Pure functions, no Alpaca dependency — all I/O lives in ``AlpacaClient``. Kept
here so the accounting identity is unit-testable in isolation.

The model (per look-back window):

  ΔEquity − external_transfers = realized_sells + income − fees + unrealized

so the two buckets the user asked for fall out exactly:

  total       = end_equity − begin_equity − net_transfers      (Modified-Dietz numerator)
  realized    = realized_sells + dividends + interest − fees    (cash actually booked)
  unrealized  = total − realized                                (appreciation still on the books)

The **percentage** is Modified Dietz — total over time-weighted average capital —
so deposits/withdrawals inside the window neither inflate the return (the bug this
replaces) nor distort the rate when we DCA mid-window. Dividends and interest are
treated as realized income (they raise equity without being an external flow, so
they land in ``total`` automatically and we attribute them to ``realized``).
"""

from datetime import date


def realized_pnl_from_fills(fills: list[dict]) -> list[tuple[date, float]]:
    """Replay fills chronologically, average-cost accounting, and emit one
    ``(date, realized_pnl)`` per sell.

    ``fills`` — dicts with ``date`` (``date``), ``symbol``, ``side`` ('buy'/'sell'),
    ``qty`` (float), ``price`` (float), assumed already sorted oldest-first. Realized
    P&L on a sell is ``(price − running_avg_cost) × qty``; buys move the average, sells
    don't. Needs the *full* fill history so the average cost is correct — a truncated
    history would misstate cost basis.
    """
    books: dict[str, dict] = {}  # symbol -> {qty, avg_cost}
    out: list[tuple[date, float]] = []
    for f in fills:
        sym = f["symbol"]
        qty = float(f["qty"])
        price = float(f["price"])
        b = books.setdefault(sym, {"qty": 0.0, "avg_cost": 0.0})
        if f["side"] == "sell":
            realized = (price - b["avg_cost"]) * qty
            b["qty"] = max(0.0, b["qty"] - qty)
            out.append((f["date"], realized))
        else:  # buy — blend into the average cost
            new_qty = b["qty"] + qty
            if new_qty > 0:
                b["avg_cost"] = (b["avg_cost"] * b["qty"] + price * qty) / new_qty
            b["qty"] = new_qty
    return out


def external_flows(
    transfers: list[tuple[date, float]], baseline_equity: float
) -> list[tuple[date, float]]:
    """Strip the initial funding already reflected in ``baseline_equity`` and return
    only the transfers that are genuine in-period external flows.

    Alpaca's equity curve can reflect the opening deposit a few days before the
    transfer *activity* is dated, so a naive date comparison double-counts it (in
    the baseline **and** as a flow). We instead absorb the earliest deposits up to
    ``baseline_equity`` — that's the capital that established the starting value —
    and pass through the remainder (later top-ups, withdrawals). Robust whether the
    account was funded once at inception or topped up later.
    """
    remaining = max(0.0, baseline_equity)
    out: list[tuple[date, float]] = []
    for d, amt in sorted(transfers, key=lambda t: t[0]):
        if amt > 0 and remaining > 0.01:
            absorbed = min(amt, remaining)
            remaining -= absorbed
            leftover = amt - absorbed
            if leftover > 0.01:
                out.append((d, leftover))
        else:
            out.append((d, amt))
    return out


def _in_window(events: list[tuple[date, float]], base: date, end: date) -> float:
    """Sum amounts for events dated strictly after ``base`` and on/before ``end``."""
    return sum(amt for d, amt in events if base < d <= end)


def compute_window(
    base_date: date,
    end_date: date,
    begin_equity: float,
    end_equity: float,
    transfers: list[tuple[date, float]],
    realized_events: list[tuple[date, float]],
    income_events: list[tuple[date, float]],
) -> dict | None:
    """Realized/unrealized/total ($) + Modified-Dietz rate (%) for one window.

    ``transfers`` are external cash flows (+deposit / −withdrawal); ``realized_events``
    are per-sell realized P&L; ``income_events`` are dividends + interest (+) and fees
    (−). Only events dated within ``(base_date, end_date]`` are counted — so the initial
    deposit is excluded from every window whose base is on/after it. Returns ``None`` if
    the window has no positive span or no capital base to divide by.
    """
    span = (end_date - base_date).days
    if span <= 0:
        return None

    flows_in = [(d, amt) for d, amt in transfers if base_date < d <= end_date]
    net_transfers = sum(amt for _, amt in flows_in)
    # Time-weighted capital: each flow earns weight = fraction of the window it was present.
    weighted = sum(amt * ((end_date - d).days / span) for d, amt in flows_in)
    denom = begin_equity + weighted

    total = end_equity - begin_equity - net_transfers
    realized = (_in_window(realized_events, base_date, end_date)
                + _in_window(income_events, base_date, end_date))
    unrealized = total - realized

    pct = (total / denom * 100) if denom > 0 else None
    # Split the rate on the same denominator so realized% + unrealized% == total%.
    return {
        "realized": round(realized, 2),
        "unrealized": round(unrealized, 2),
        "total": round(total, 2),
        "pct": round(pct, 2) if pct is not None else None,
        "realizedPct": round(realized / denom * 100, 2) if denom > 0 else None,
        "unrealizedPct": round(unrealized / denom * 100, 2) if denom > 0 else None,
    }
