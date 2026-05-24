"""Data models for the investment assistant."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class StrategyMode(Enum):
    """Defines the trading strategy for a security."""
    CASH_OUT = "cash_out"
    INCREASE_HOLDING = "increase_holding"
    HOLD = "hold"


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class AssetType(Enum):
    EQUITY = "equity"
    ETF = "etf"


@dataclass
class Holding:
    """Represents a single holding position."""
    symbol: str
    description: str
    quantity: float
    last_price: float
    current_value: float
    cost_basis_total: float
    average_cost_basis: float
    total_gain_loss_dollar: float
    total_gain_loss_percent: float
    percent_of_account: float
    asset_type: AssetType = AssetType.EQUITY

    @property
    def is_profitable(self) -> bool:
        return self.total_gain_loss_dollar > 0


@dataclass
class CashOutParams:
    """Parameters for the cash-out strategy fork."""
    take_profit_pct: float = 25.0       # Sell if price rises this % from avg cost
    trailing_stop_pct: Optional[float] = None  # Dynamic trailing stop %
    sell_quantity_pct: float = 100.0     # % of position to sell when triggered

    def should_take_profit(self, current_price: float, avg_cost: float) -> bool:
        pct_change = ((current_price - avg_cost) / avg_cost) * 100
        return pct_change >= self.take_profit_pct


@dataclass
class IncreaseHoldingParams:
    """Parameters for the increase-holding strategy fork."""
    dca_amount: float = 0.0             # Fixed dollar amount per DCA buy
    dca_interval_days: int = 7          # Days between DCA buys
    buy_dip_pct: float = -5.0           # Buy when price drops this % from watermark (peak)
    min_profit_pct: Optional[float] = None   # Minimum profit % to protect (e.g. 10.0)
    profit_trail_pct: Optional[float] = None  # Sell when price drops this % from watermark while in profit (e.g. -5.0)
    sell_quantity_pct: float = 100.0     # % of position to sell when profit protection triggers

    def should_buy_dip(self, current_price: float, watermark: float) -> bool:
        if watermark <= 0:
            return False
        pct_change = ((current_price - watermark) / watermark) * 100
        return pct_change <= self.buy_dip_pct

    def should_protect_profit(self, current_price: float, avg_cost: float, watermark: float) -> bool:
        """Triggers when price is dropping from peak AND current profit is above minimum floor."""
        if self.min_profit_pct is None or self.profit_trail_pct is None:
            return False
        if avg_cost <= 0 or watermark <= 0:
            return False
        # Signal 1: Are we above the minimum profit floor?
        current_profit_pct = ((current_price - avg_cost) / avg_cost) * 100
        if current_profit_pct < self.min_profit_pct:
            return False
        # Signal 2: Is the price dropping from its peak?
        pct_from_peak = ((current_price - watermark) / watermark) * 100
        return pct_from_peak <= self.profit_trail_pct


@dataclass
class HoldParams:
    """Parameters for the hold strategy — sit tight unless stop-loss triggers."""
    stop_loss_pct: float = -15.0     # Sell if price drops this % from avg cost
    sell_quantity_pct: float = 100.0  # % of position to sell when triggered

    def should_stop_loss(self, current_price: float, avg_cost: float) -> bool:
        pct_change = ((current_price - avg_cost) / avg_cost) * 100
        return pct_change <= self.stop_loss_pct


@dataclass
class TradingStrategy:
    """Trading strategy configuration for a single security."""
    symbol: str
    mode: StrategyMode
    enabled: bool = True
    cash_out: Optional[CashOutParams] = None
    increase_holding: Optional[IncreaseHoldingParams] = None
    hold: Optional[HoldParams] = None

    def __post_init__(self):
        if self.mode == StrategyMode.CASH_OUT and self.cash_out is None:
            self.cash_out = CashOutParams()
        elif self.mode == StrategyMode.INCREASE_HOLDING and self.increase_holding is None:
            self.increase_holding = IncreaseHoldingParams()
        elif self.mode == StrategyMode.HOLD and self.hold is None:
            self.hold = HoldParams()


class BuyType(Enum):
    """Distinguishes DCA buys from strategy-triggered buys."""
    DCA = "dca"
    STRATEGY = "strategy"


@dataclass
class SpendingBudget:
    """Budget limits and tracking for a single buy type (DCA or strategy)."""
    max_daily: float = 0.0
    max_weekly: float = 0.0
    max_monthly: float = 0.0
    max_single_order: float = 0.0

    # Tracking (populated from ledger)
    spent_today: float = 0.0
    spent_this_week: float = 0.0
    spent_this_month: float = 0.0

    def can_invest(self, amount: float) -> tuple[bool, str]:
        if self.max_single_order > 0 and amount > self.max_single_order:
            return False, f"Amount ${amount:.2f} exceeds max single order ${self.max_single_order:.2f}"
        if self.spent_today + amount > self.max_daily:
            return False, f"Would exceed daily limit (${self.max_daily:.2f})"
        if self.max_weekly > 0 and self.spent_this_week + amount > self.max_weekly:
            return False, f"Would exceed weekly limit (${self.max_weekly:.2f})"
        if self.max_monthly > 0 and self.spent_this_month + amount > self.max_monthly:
            return False, f"Would exceed monthly limit (${self.max_monthly:.2f})"
        return True, "OK"


@dataclass
class InvestmentGuidelines:
    """Global investment limits and rules, split by buy type."""
    dca: SpendingBudget = None
    strategy: SpendingBudget = None
    trading_enabled: bool = True

    def __post_init__(self):
        if self.dca is None:
            self.dca = SpendingBudget(max_daily=300.0)
        if self.strategy is None:
            self.strategy = SpendingBudget(max_daily=500.0)

    def can_invest(self, amount: float, buy_type: BuyType) -> tuple[bool, str]:
        """Check if an investment is allowed under the given buy type's budget."""
        if not self.trading_enabled:
            return False, "Trading is disabled"
        budget = self.dca if buy_type == BuyType.DCA else self.strategy
        return budget.can_invest(amount)

    def record_investment(self, amount: float, buy_type: BuyType):
        budget = self.dca if buy_type == BuyType.DCA else self.strategy
        budget.spent_today += amount
        budget.spent_this_week += amount
        budget.spent_this_month += amount


@dataclass
class SecurityProfile:
    """Auto-generated profile for a held security."""
    symbol: str
    name: str
    asset_type: AssetType
    sector: str = ""
    current_price: float = 0.0
    day_high: float = 0.0
    day_low: float = 0.0
    week_52_high: float = 0.0
    week_52_low: float = 0.0
    avg_volume: int = 0
    market_cap: float = 0.0
    # Holding context
    quantity_held: float = 0.0
    avg_cost: float = 0.0
    total_gain_loss_pct: float = 0.0
    # Strategy
    strategy: Optional[TradingStrategy] = None


@dataclass
class Portfolio:
    """The complete portfolio state."""
    account_id: str = ""
    cash_balance: float = 0.0
    holdings: dict[str, Holding] = field(default_factory=dict)
    total_value: float = 0.0

    @property
    def invested_value(self) -> float:
        return self.total_value - self.cash_balance

    @property
    def cash_pct(self) -> float:
        if self.total_value == 0:
            return 0
        return (self.cash_balance / self.total_value) * 100
