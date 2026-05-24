"""Alpaca API client wrapper for paper trading."""

import os
from datetime import datetime

import alpaca_trade_api as tradeapi
from dotenv import load_dotenv

from .models import AssetType, Holding, OrderSide, Portfolio, SecurityProfile


load_dotenv()


class AlpacaClient:
    """Wrapper around the Alpaca trading API."""

    def __init__(self):
        self.api = tradeapi.REST(
            key_id=os.getenv("ALPACA_API_KEY"),
            secret_key=os.getenv("ALPACA_SECRET_KEY"),
            base_url=os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
            api_version="v2",
        )
        self._validate_connection()

    def _validate_connection(self):
        """Verify API credentials work."""
        try:
            account = self.api.get_account()
            print(f"  Connected to Alpaca — Account status: {account.status}")
            print(f"  Buying power: ${float(account.buying_power):,.2f}")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Alpaca: {e}")

    def get_account(self):
        return self.api.get_account()

    def get_current_price(self, symbol: str) -> float:
        """Get the latest trade price for a symbol."""
        try:
            trade = self.api.get_latest_trade(symbol)
            return float(trade.p)
        except Exception:
            return 0.0

    def get_security_profile(self, symbol: str, quantity_held: float = 0,
                              avg_cost: float = 0, gain_loss_pct: float = 0) -> SecurityProfile:
        """Build a SecurityProfile from Alpaca market data."""
        try:
            asset = self.api.get_asset(symbol)
            snapshot = self.api.get_snapshot(symbol)

            # 'class' is a reserved word, so use getattr
            asset_class = getattr(asset, 'class', '') or asset._raw.get('class', '')
            known_etfs = {"GLD", "SPY", "RSP", "QQQ", "IWM", "DIA", "VTI", "VOO"}
            asset_type = AssetType.ETF if symbol in known_etfs else AssetType.EQUITY

            # Snapshot fields use short keys: p=price, h=high, l=low
            trade = snapshot.latest_trade
            bar = snapshot.daily_bar
            current_price = float(trade.p) if trade else 0.0
            day_high = float(bar.h) if bar else 0.0
            day_low = float(bar.l) if bar else 0.0

            # Get bars for 52-week high/low and avg volume
            from datetime import timedelta
            week_52_high = day_high
            week_52_low = day_low
            avg_volume = 0
            try:
                start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
                bar_list = list(self.api.get_bars(symbol, "1Day", start=start))
                if bar_list:
                    highs = [float(b.h) for b in bar_list]
                    lows = [float(b.l) for b in bar_list]
                    week_52_high = max(highs)
                    week_52_low = min(lows)
                    # Avg volume from last 20 bars
                    recent = bar_list[-20:]
                    volumes = [int(b.v) for b in recent]
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
        kwargs = {
            "symbol": symbol,
            "qty": qty,
            "side": side.value,
            "type": order_type,
            "time_in_force": time_in_force,
        }
        if limit_price and order_type == "limit":
            kwargs["limit_price"] = str(limit_price)

        order = self.api.submit_order(**kwargs)
        return {
            "id": order.id,
            "symbol": order.symbol,
            "qty": order.qty,
            "side": order.side,
            "type": order.type,
            "status": order.status,
            "submitted_at": str(order.submitted_at),
        }

    def build_portfolio(self) -> Portfolio:
        """Build a Portfolio from live Alpaca account and positions."""
        account = self.api.get_account()
        positions = self.api.list_positions()

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
            )

        cash = float(account.cash)
        total = sum(h.current_value for h in holdings.values()) + cash

        for h in holdings.values():
            h.percent_of_account = (h.current_value / total * 100) if total > 0 else 0

        return Portfolio(
            account_id=account.account_number,
            cash_balance=cash,
            holdings=holdings,
            total_value=total,
        )

    def get_positions(self) -> list[dict]:
        """Get all current positions from Alpaca."""
        positions = self.api.list_positions()
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
        orders = self.api.list_orders(limit=limit, status="all")
        return [
            {
                "id": o.id,
                "symbol": o.symbol,
                "qty": o.qty,
                "side": o.side,
                "type": o.type,
                "status": o.status,
                "submitted_at": str(o.submitted_at),
                "filled_at": str(o.filled_at) if o.filled_at else None,
                "filled_avg_price": str(o.filled_avg_price) if o.filled_avg_price else None,
            }
            for o in orders
        ]
