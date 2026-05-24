"""Configuration loader — reads settings.yaml and builds strategy objects."""

from pathlib import Path

import yaml

from .models import (
    CashOutParams,
    HoldParams,
    IncreaseHoldingParams,
    InvestmentGuidelines,
    SpendingBudget,
    StrategyMode,
    TradingStrategy,
)


DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "settings.yaml"


def load_config(config_path: str | Path = DEFAULT_CONFIG) -> dict:
    """Load and parse the YAML configuration file."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def _build_budget(cfg: dict, defaults: dict) -> SpendingBudget:
    """Build a SpendingBudget from a config subsection."""
    return SpendingBudget(
        max_daily=cfg.get("max_daily", defaults["max_daily"]),
        max_weekly=cfg.get("max_weekly", defaults["max_weekly"]),
        max_monthly=cfg.get("max_monthly", defaults["max_monthly"]),
        max_single_order=cfg.get("max_single_order", defaults["max_single_order"]),
    )


def build_guidelines(config: dict) -> InvestmentGuidelines:
    """Build InvestmentGuidelines from config dict."""
    g = config.get("guidelines", {})

    dca_cfg = g.get("dca", {})
    strategy_cfg = g.get("strategy", {})

    return InvestmentGuidelines(
        dca=_build_budget(dca_cfg, {
            "max_daily": 300.0, "max_weekly": 0.0,
            "max_monthly": 0.0, "max_single_order": 0.0,
        }),
        strategy=_build_budget(strategy_cfg, {
            "max_daily": 500.0, "max_weekly": 0.0,
            "max_monthly": 0.0, "max_single_order": 0.0,
        }),
        trading_enabled=g.get("trading_enabled", True),
    )


def build_strategies(config: dict) -> dict[str, TradingStrategy]:
    """Build TradingStrategy objects from config dict."""
    strategies = {}
    for symbol, s_config in config.get("strategies", {}).items():
        mode = StrategyMode(s_config["mode"])
        enabled = s_config.get("enabled", True)

        cash_out = None
        increase_holding = None
        hold = None

        if mode == StrategyMode.CASH_OUT and "cash_out" in s_config:
            co = s_config["cash_out"]
            cash_out = CashOutParams(
                take_profit_pct=co.get("take_profit_pct", 25.0),
                trailing_stop_pct=co.get("trailing_stop_pct"),
                sell_quantity_pct=co.get("sell_quantity_pct", 100.0),
            )

        if mode == StrategyMode.INCREASE_HOLDING and "increase_holding" in s_config:
            ih = s_config["increase_holding"]
            increase_holding = IncreaseHoldingParams(
                dca_amount=ih.get("dca_amount", 0.0),
                dca_interval_days=ih.get("dca_interval_days", 7),
                buy_dip_pct=ih.get("buy_dip_pct", -5.0),
                min_profit_pct=ih.get("min_profit_pct"),
                profit_trail_pct=ih.get("profit_trail_pct"),
                sell_quantity_pct=ih.get("sell_quantity_pct", 100.0),
            )

        if mode == StrategyMode.HOLD and "hold" in s_config:
            h = s_config["hold"]
            hold = HoldParams(
                stop_loss_pct=h.get("stop_loss_pct", -15.0),
                sell_quantity_pct=h.get("sell_quantity_pct", 100.0),
            )

        strategies[symbol] = TradingStrategy(
            symbol=symbol,
            mode=mode,
            enabled=enabled,
            cash_out=cash_out,
            increase_holding=increase_holding,
            hold=hold,
        )

    return strategies
