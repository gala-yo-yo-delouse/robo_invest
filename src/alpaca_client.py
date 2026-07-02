"""Alpaca API client wrapper for paper trading (alpaca-py SDK)."""

import os
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    StockLatestTradeRequest,
    StockSnapshotRequest,
)
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide as AlpacaSide, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
)

from .models import AssetType, Holding, OrderSide, Portfolio, SecurityProfile


load_dotenv()


def _to_datetime(start) -> datetime:
    """Accept a 'YYYY-MM-DD' string or a datetime; return a datetime."""
    if isinstance(start, datetime):
        return start
    return datetime.strptime(start, "%Y-%m-%d")


class AlpacaClient:
    """Wrapper around the Alpaca trading + market-data APIs (alpaca-py)."""

    def __init__(self):
        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_SECRET_KEY")
        paper = "paper" in os.getenv(
            "ALPACA_BASE_URL", "https://paper-api.alpaca.markets"
        )
        self.trading = TradingClient(api_key, secret_key, paper=paper)
        self.data = StockHistoricalDataClient(api_key, secret_key)
        self._validate_connection()

    def _validate_connection(self):
        """Verify API credentials work."""
        try:
            account = self.trading.get_account()
            print(f"  Connected to Alpaca — Account status: {account.status}")
            print(f"  Buying power: ${float(account.buying_power):,.2f}")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Alpaca: {e}")

    def get_account(self):
        return self.trading.get_account()

    def get_clock(self):
        return self.trading.get_clock()

    def get_current_price(self, symbol: str) -> float:
        """Get the latest trade price for a symbol."""
        try:
            req = StockLatestTradeRequest(symbol_or_symbols=symbol)
            trade = self.data.get_stock_latest_trade(req)[symbol]
            return float(trade.price)
        except Exception:
            return 0.0

    def get_bars(self, symbol: str, start: str) -> list[dict]:
        """Return normalized daily bars for one symbol from ``start``
        (YYYY-MM-DD or datetime): [{date, open, high, low, close, volume}, ...].
        Used by the dashboard/query handler for candlestick charts.
        """
        out: list[dict] = []
        try:
            req = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Day,
                start=_to_datetime(start),
            )
            bars = self.data.get_stock_bars(req)
            for b in bars.data.get(symbol, []):
                out.append({
                    "date": str(b.timestamp)[:10],
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": int(b.volume),
                })
        except Exception:
            pass
        return out

    def get_security_profile(self, symbol: str, quantity_held: float = 0,
                              avg_cost: float = 0, gain_loss_pct: float = 0) -> SecurityProfile:
        """Build a SecurityProfile from Alpaca market data."""
        try:
            asset = self.trading.get_asset(symbol)
            snap_req = StockSnapshotRequest(symbol_or_symbols=symbol)
            snapshot = self.data.get_stock_snapshot(snap_req)[symbol]

            known_etfs = {"GLD", "SPY", "RSP", "QQQ", "IWM", "DIA", "VTI", "VOO"}
            asset_type = AssetType.ETF if symbol in known_etfs else AssetType.EQUITY

            trade = snapshot.latest_trade
            bar = snapshot.daily_bar
            current_price = float(trade.price) if trade else 0.0
            day_high = float(bar.high) if bar else 0.0
            day_low = float(bar.low) if bar else 0.0

            # Get bars for 52-week high/low and avg volume.
            week_52_high = day_high
            week_52_low = day_low
            avg_volume = 0
            try:
                start = datetime.now() - timedelta(days=365)
                req = StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=TimeFrame.Day,
                    start=start,
                )
                bar_list = self.data.get_stock_bars(req).data.get(symbol, [])
                if bar_list:
                    highs = [float(b.high) for b in bar_list]
                    lows = [float(b.low) for b in bar_list]
                    week_52_high = max(highs)
                    week_52_low = min(lows)
                    # Avg volume from last 20 bars.
                    recent = bar_list[-20:]
                    volumes = [int(b.volume) for b in recent]
                    avg_volume = sum(volumes) // len(volumes) if volumes else 0
            except Exception:
                pass

            return SecurityProfile(
                symbol=symbol,
                name=asset.name,
                asset_type=asset_type,
                current_price=current_price,
                day_high=day_high,
                day_low=day_low,
                week_52_high=week_52_high,
                week_52_low=week_52_low,
                avg_volume=avg_volume,
                quantity_held=quantity_held,
                avg_cost=avg_cost,
                total_gain_loss_pct=gain_loss_pct,
            )
        except Exception as e:
            print(f"  Warning: Could not build profile for {symbol}: {e}")
            return SecurityProfile(
                symbol=symbol,
                name=symbol,
                asset_type=AssetType.EQUITY,
                quantity_held=quantity_held,
                avg_cost=avg_cost,
                total_gain_loss_pct=gain_loss_pct,
            )

    def submit_order(self, symbol: str, qty: float, side: OrderSide,
                     order_type: str = "market", time_in_force: str = "day",
                     limit_price: float = None) -> dict:
        """Submit an order to Alpaca."""
        alpaca_side = AlpacaSide.BUY if side == OrderSide.BUY else AlpacaSide.SELL
        tif = TimeInForce.GTC if str(time_in_force).lower() == "gtc" else TimeInForce.DAY

        if order_type == "limit" and limit_price:
            req = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=alpaca_side,
                time_in_force=tif,
                limit_price=float(limit_price),
            )
        else:
            req = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=alpaca_side,
                time_in_force=tif,
            )

        order = self.trading.submit_order(order_data=req)
        return {
            "id": str(order.id),
            "symbol": str(order.symbol),
            "qty": str(order.qty),
            "side": str(order.side),
            "type": str(order.order_type),
            "status": str(order.status),
            "submitted_at": str(order.submitted_at),
        }

    def get_52_week_ranges(self, symbols: list[str]) -> dict[str, tuple[float, float]]:
        """Return {symbol: (week_52_low, week_52_high)} from ~1y of daily bars.

        Batched into a single multi-symbol request to keep the dashboard snappy.
        """
        ranges: dict[str, tuple[float, float]] = {}
        if not symbols:
            return ranges
        try:
            start = datetime.now() - timedelta(days=365)
            req = StockBarsRequest(
                symbol_or_symbols=list(symbols),
                timeframe=TimeFrame.Day,
                start=start,
            )
            bars = self.data.get_stock_bars(req)
            for sym, bar_list in bars.data.items():
                if not bar_list:
                    continue
                lows = [float(b.low) for b in bar_list]
                highs = [float(b.high) for b in bar_list]
                ranges[sym] = (min(lows), max(highs))
        except Exception as e:
            print(f"  Warning: Could not fetch 52-week ranges: {e}")
        return ranges

    def get_daily_highs(self, symbols, start: str) -> dict[str, list[tuple]]:
        """Return {symbol: [(date, high), ...]} of daily-bar highs from ``start``
        (YYYY-MM-DD). Batched into one multi-symbol request; used to reconcile
        watermarks against real market data."""
        out: dict[str, list[tuple]] = {s: [] for s in symbols}
        if not symbols:
            return out
        try:
            req = StockBarsRequest(
                symbol_or_symbols=list(symbols),
                timeframe=TimeFrame.Day,
                start=_to_datetime(start),
            )
            bars = self.data.get_stock_bars(req)
            for sym, bar_list in bars.data.items():
                if sym not in out:
                    continue
                for b in bar_list:
                    out[sym].append((b.timestamp.date(), float(b.high)))
        except Exception as e:
            print(f"  Warning: get_daily_highs failed: {e}")
        return out

    def build_portfolio(self, include_ranges: bool = False) -> Portfolio:
        """Build a Portfolio from live Alpaca account and positions.

        ``include_ranges`` adds 52-week high/low per holding (one extra batched
        market-data request) — used by the dashboard, skipped by the trading loop.
        """
        account = self.trading.get_account()
        positions = self.trading.get_all_positions()

        known_etfs = {"GLD", "SPY", "RSP", "QQQ", "IWM", "DIA", "VTI", "VOO"}
        holdings = {}
        for p in positions:
            symbol = p.symbol
            qty = float(p.qty)
            avg_cost = float(p.avg_entry_price)
            current_price = float(p.current_price)
            market_value = float(p.market_value)
            cost_basis = qty * avg_cost
            unrealized_pl = float(p.unrealized_pl)
            unrealized_plpc = float(p.unrealized_plpc) * 100
            intraday_pl = float(p.unrealized_intraday_pl)
            intraday_plpc = float(p.unrealized_intraday_plpc) * 100

            holdings[symbol] = Holding(
                symbol=symbol,
                description=symbol,
                quantity=qty,
                last_price=current_price,
                current_value=market_value,
                cost_basis_total=cost_basis,
                average_cost_basis=avg_cost,
                total_gain_loss_dollar=unrealized_pl,
                total_gain_loss_percent=unrealized_plpc,
                percent_of_account=0,
                asset_type=AssetType.ETF if symbol in known_etfs else AssetType.EQUITY,
                today_gain_loss_dollar=intraday_pl,
                today_gain_loss_percent=intraday_plpc,
            )

        cash = float(account.cash)
        total = sum(h.current_value for h in holdings.values()) + cash

        for h in holdings.values():
            h.percent_of_account = (h.current_value / total * 100) if total > 0 else 0
            h.cost_basis_pct_of_account = (h.cost_basis_total / total * 100) if total > 0 else 0

        if include_ranges:
            ranges = self.get_52_week_ranges(list(holdings.keys()))
            for sym, h in holdings.items():
                if sym in ranges:
                    h.week_52_low, h.week_52_high = ranges[sym]

        return Portfolio(
            account_id=account.account_number,
            cash_balance=cash,
            holdings=holdings,
            total_value=total,
        )

    def _get_account_activities(self, activity_types: str, page_size: int = 100) -> list[dict]:
        """All account activities of the given comma-separated ``activity_types``,
        paginated to exhaustion. The Trading API's ``/account/activities`` isn't
        wrapped by ``TradingClient`` in alpaca-py, so we call the low-level GET and
        page with ``page_token`` = the last row's id. Returns [] on any failure."""
        out: list[dict] = []
        token = None
        try:
            while True:
                params = {"activity_types": activity_types, "page_size": page_size}
                if token:
                    params["page_token"] = token
                page = self.trading.get("/account/activities", params)
                if not page:
                    break
                out.extend(page)
                if len(page) < page_size:
                    break
                token = page[-1]["id"]
        except Exception as e:
            print(f"  Warning: account activities ({activity_types}) failed: {e}")
        return out

    def get_period_returns(self, current_equity: float | None = None) -> dict:
        """Deposit-adjusted returns per look-back window, split realized/unrealized.

        Combines Alpaca's daily equity curve (portfolio-history) with account
        activities (fills, cash transfers, dividends/interest, fees) so that:

        - the **%** is Modified Dietz — external deposits/withdrawals are removed
          from the numerator and time-weighted out of the denominator (this is
          what fixes the old "deposit shows up as +100% return" bug);
        - the **$** splits into ``realized`` (sell P&L + dividends + interest − fees)
          and ``unrealized`` (the residual: appreciation still held).

        Returns ``{"1M": {realized, unrealized, total, pct, realizedPct,
        unrealizedPct}, "6M": .., "12M": .., "YTD": .., "ALL": ..}``; windows that
        can't be computed are omitted. Math lives in ``src/returns.py``.
        """
        from alpaca.trading.requests import GetPortfolioHistoryRequest

        from . import returns as R

        out: dict = {}
        try:
            hist = self.trading.get_portfolio_history(
                GetPortfolioHistoryRequest(period="1A", timeframe="1D")
            )
            ts = list(getattr(hist, "timestamp", None) or [])
            eq = list(getattr(hist, "equity", None) or [])
        except Exception as e:
            print(f"  Warning: portfolio history failed: {e}")
            return out

        # (date, equity) pairs, dropping gaps where Alpaca reports null/zero.
        series = [
            (datetime.fromtimestamp(int(t), tz=timezone.utc).date(), float(e))
            for t, e in zip(ts, eq)
            if e is not None and float(e) > 0
        ]
        if not series:
            return out

        now_eq = float(current_equity) if current_equity else series[-1][1]
        today = datetime.now(timezone.utc).date()

        def equity_on_or_before(target: date) -> float:
            chosen = None
            for d, v in series:
                if d <= target:
                    chosen = v
                else:
                    break
            return chosen if chosen is not None else series[0][1]

        # ── activities → dated events for the accounting identity ──────────
        def _d(a: dict) -> date | None:
            raw = a.get("date") or a.get("transaction_time")
            return datetime.fromisoformat(str(raw)[:10]).date() if raw else None

        # Fills: realized sell P&L via running average cost (needs full history).
        fills = []
        for a in self._get_account_activities("FILL"):
            d = _d(a)
            if d is None:
                continue
            fills.append({
                "date": d,
                "symbol": a.get("symbol"),
                "side": "sell" if str(a.get("side", "")).startswith("sell") else "buy",
                "qty": float(a.get("qty") or 0),
                "price": float(a.get("price") or 0),
            })
        fills.sort(key=lambda f: f["date"])
        realized_events = R.realized_pnl_from_fills(fills)

        # External cash transfers (+deposit / −withdrawal) — excluded from return.
        # Absorb the opening deposit into the baseline equity so it isn't counted
        # both in begin_equity and as a flow (Alpaca dates the two a few days apart).
        transfers = [
            (_d(a), float(a.get("net_amount") or 0))
            for a in self._get_account_activities("CSD,CSW,JNLC,TRANS,PTC")
        ]
        transfers = [(d, amt) for d, amt in transfers if d is not None]
        transfers = R.external_flows(transfers, series[0][1])

        # Dividends + interest (+) and fees (−) — realized income booked to cash.
        income_events = [
            (_d(a), float(a.get("net_amount") or 0))
            for a in self._get_account_activities(
                "DIV,DIVCGL,DIVCGS,DIVNRA,DIVROC,DIVTXEX,INT,FEE,CFEE")
        ]
        income_events = [(d, amt) for d, amt in income_events if d is not None]

        # ── windows ───────────────────────────────────────────────────────
        first_date = series[0][0]
        windows = {
            "1M": today - timedelta(days=30),
            "6M": today - timedelta(days=182),
            "12M": today - timedelta(days=365),
            "YTD": date(today.year, 1, 1) - timedelta(days=1),  # last close of prior year
            "ALL": first_date,
        }
        for label, target in windows.items():
            # Account younger than the window ⇒ measure since inception.
            base_date = target if target >= first_date else first_date
            result = R.compute_window(
                base_date=base_date,
                end_date=today,
                begin_equity=equity_on_or_before(target),
                end_equity=now_eq,
                transfers=transfers,
                realized_events=realized_events,
                income_events=income_events,
            )
            if result is not None:
                out[label] = result
        return out

    def get_positions(self) -> list[dict]:
        """Get all current positions from Alpaca."""
        positions = self.trading.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
            }
            for p in positions
        ]

    def get_recent_orders(self, limit: int = 10) -> list[dict]:
        """Get recent orders."""
        orders = self.trading.get_orders(GetOrdersRequest(limit=limit))
        return [
            {
                "id": str(o.id),
                "symbol": o.symbol,
                "qty": o.qty,
                "side": str(o.side),
                "type": str(o.order_type),
                "status": str(o.status),
                "submitted_at": str(o.submitted_at),
                "filled_at": str(o.filled_at) if o.filled_at else None,
                "filled_avg_price": str(o.filled_avg_price) if o.filled_avg_price else None,
            }
            for o in orders
        ]
