"""High-watermark tracker — robust peak-price tracking per held symbol.

Each entry carries TWO peaks:

  - ``high`` — the **all-time ratchet** anchored at the position's entry. It only
    rises until the position is exited. Trailing stops trail down from it and
    profit-protection measures pullback against it.
  - ``recent_high`` — a **rolling recent high** over the last ``dip_lookback_days``
    days (default 15). It is allowed to DECAY as old highs age out, so
    buy-the-dip measures drawdown against the *recent* high, not a stale peak.

Both are:

  - ratcheted up live each cycle from sampled prices, with an outlier guard so a
    single bad tick can't poison either peak (#5);
  - reconciled against actual market bars (so highs reached during downtime or
    between 5-min samples are not lost) (#4): ``high`` over the ratchet window,
    ``recent_high`` over the rolling dip window;
  - anchored with a ``since`` date when a position is first seen (#1);
  - reset when a position is fully exited, and garbage-collected for symbols no
    longer held (#1, #6).

Only the trading loop persists (``persist=True``); every preview path
(dashboard, CLI ``signals``) reads with ``persist=False`` so viewing never
mutates state (#2).

Entry shape: ``{high: float, recent_high: float, since: 'YYYY-MM-DD',
updated_at: iso, reconciled: 'YYYY-MM-DD'}``
"""

from datetime import datetime, date, timedelta

from .storage import get_backend

# A new high more than this % above the current peak in a single sampled tick is
# treated as a bad print and ignored (0 disables the guard). Reconciliation from
# trusted bars bypasses it.
DEFAULT_MAX_TICK_JUMP_PCT = 25.0


def _now() -> str:
    return datetime.now().isoformat()


def _today_iso() -> str:
    return date.today().isoformat()


def get_high_watermark(symbol: str) -> float:
    """Return the recorded peak price for a symbol, or 0.0 if not tracked."""
    entry = get_backend().read_watermark(symbol)
    return entry["high"] if entry else 0.0


def update_watermarks(symbol: str, current_price: float, persist: bool = True,
                      max_jump_pct: float = DEFAULT_MAX_TICK_JUMP_PCT) -> tuple[float, float]:
    """Ratchet BOTH peaks from a live sampled price → ``(high, recent_high)``.

    A new intraday high is trivially inside the rolling dip window, so it lifts
    both the all-time ``high`` and the rolling ``recent_high`` together. With
    ``persist=False`` the would-be peaks are computed and returned but nothing is
    written — used by preview paths so that merely viewing signals never mutates
    stored state. The outlier guard applies to both.
    """
    entry = get_backend().read_watermark(symbol)
    cur_high = entry["high"] if entry else 0.0
    cur_recent = (entry.get("recent_high", 0.0) if entry else 0.0)

    # Outlier guard — reject an implausibly large single-tick jump (vs the
    # all-time peak, the larger of the two references).
    if cur_high > 0 and max_jump_pct > 0 and current_price > cur_high * (1 + max_jump_pct / 100):
        return cur_high, cur_recent

    new_high = max(cur_high, current_price)
    new_recent = max(cur_recent, current_price)

    if not persist:
        return new_high, new_recent

    if entry is None:
        # First sighting mid-cycle (before reconcile ran) — anchor both peaks.
        get_backend().write_watermark(symbol, {
            "high": current_price, "recent_high": current_price,
            "since": _today_iso(), "updated_at": _now(),
        })
        return current_price, current_price

    high = get_backend().bump_watermark_high(symbol, current_price, _now())
    recent = get_backend().bump_watermark_recent_high(symbol, current_price, _now())
    return high, recent


def update_high_watermark(symbol: str, current_price: float, persist: bool = True,
                          max_jump_pct: float = DEFAULT_MAX_TICK_JUMP_PCT) -> float:
    """Back-compat thin wrapper — returns only the all-time ``high``."""
    high, _ = update_watermarks(symbol, current_price, persist=persist, max_jump_pct=max_jump_pct)
    return high


def seed_watermark(symbol: str, high: float, since: str | None = None) -> None:
    """Create/anchor a watermark entry (used when a new position appears).

    Seeds both ``high`` and ``recent_high`` to the same value.
    """
    get_backend().write_watermark(symbol, {
        "high": high,
        "recent_high": high,
        "since": since or _today_iso(),
        "updated_at": _now(),
    })


def reset_watermark(symbol: str):
    """Reset tracking for a symbol (e.g. after the position is fully exited)."""
    get_backend().delete_watermark(symbol)


def get_all_watermarks() -> dict[str, float]:
    """Return all tracked watermarks as {symbol: high_price}."""
    return {sym: info["high"] for sym, info in get_backend().list_watermarks().items()}


def reconcile_watermarks(held_symbols, bars_provider, *, stop_window_days: int = 0,
                         dip_window_days: int = 15, max_lookback_days: int = 365,
                         today: date | None = None) -> dict:
    """Daily reconcile of BOTH peaks against real market bars.

    - Garbage-collects watermarks for symbols no longer held (covers full exits
      and external/manual sells) (#1, #6).
    - Seeds a watermark for newly-held symbols, anchored to the window/position
      highs from bars (#1).
    - Repairs each held symbol's peaks from actual daily-bar highs so highs
      missed during downtime or between samples are not lost (#4).

    Two peaks are computed per symbol:
      - ``high`` — trailing-stop / profit-protection reference. ``stop_window_days
        > 0`` makes it a rolling high over the last N days; ``== 0`` (default)
        keeps an all-time ratchet anchored at the position's ``since`` date (only
        ever rises).
      - ``recent_high`` — buy-the-dip reference: a rolling high over the last
        ``dip_window_days`` days, allowed to DECAY as old highs age out.

    ``bars_provider(symbols, start_iso) -> {symbol: [(date, high), ...]}``.
    Returns a summary dict for logging. Only fetches bars when at least one held
    symbol still needs today's reconcile, so it costs one batched request/day.
    """
    today = today or date.today()
    today_str = today.isoformat()
    held = set(held_symbols)
    backend = get_backend()

    existing = backend.list_watermarks()

    # GC + exit reset — any tracked symbol we no longer hold is stale.
    pruned = []
    for sym in list(existing):
        if sym not in held:
            backend.delete_watermark(sym)
            pruned.append(sym)

    todo = [s for s in held
            if existing.get(s) is None or existing[s].get("reconciled") != today_str]
    if not todo:
        return {"pruned": pruned, "reconciled": [], "seeded": []}

    # Lookback span for the batched bars request — must cover BOTH windows.
    if stop_window_days and stop_window_days > 0:
        stop_lookback = stop_window_days
    else:
        sinces = [existing[s]["since"] for s in todo
                  if existing.get(s) and existing[s].get("since")]
        if sinces:
            earliest = min(date.fromisoformat(x) for x in sinces)
            stop_lookback = min(max_lookback_days, max(1, (today - earliest).days))
        else:
            stop_lookback = max_lookback_days
    lookback = max(stop_lookback, dip_window_days)
    start = (today - timedelta(days=lookback)).isoformat()

    highs = bars_provider(todo, start) or {}

    reconciled, seeded = [], []
    for sym in todo:
        bars = highs.get(sym, [])
        entry = existing.get(sym)
        since = (entry and entry.get("since")) or today_str

        # ── all-time / stop-window high (only decays if stop_window_days > 0) ──
        stop_start = (today - timedelta(days=stop_window_days)) if (stop_window_days and stop_window_days > 0) \
            else date.fromisoformat(since)
        stop_high = max((h for (d, h) in bars if d >= stop_start), default=0.0)

        # ── rolling recent high for buy-the-dip (always decays) ──
        dip_start = today - timedelta(days=dip_window_days)
        recent_high = max((h for (d, h) in bars if d >= dip_start), default=0.0)

        if entry is None:
            high = stop_high                 # seed from market history
            seeded.append(sym)
        elif stop_window_days and stop_window_days > 0:
            high = stop_high                 # rolling — allowed to decay
        else:
            high = max(entry.get("high", 0.0), stop_high)  # all-time ratchet
        reconciled.append(sym)

        backend.write_watermark(sym, {
            "high": high, "recent_high": recent_high, "since": since,
            "reconciled": today_str, "updated_at": _now(),
        })

    return {"pruned": pruned, "reconciled": reconciled, "seeded": seeded}
