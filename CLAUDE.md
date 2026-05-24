# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# CLI entry point (6 subcommands) — all use live Alpaca data
python main.py portfolio              # Portfolio summary
python main.py signals                # Evaluate strategies, show trade signals
python main.py profiles               # Generate security profiles
python main.py status                 # Spending guideline budget status
python main.py execute                # Execute pending signals (prompts for confirmation)
python main.py run [--interval 5]     # Continuous mode: auto-evaluate & execute during market hours

# Web dashboard
streamlit run dashboard.py

# Dependencies
pip install -r requirements.txt
```

## Architecture

**Three-strategy fork with dual-budget enforcement, Alpaca paper trading (transitioning to live).**

```
Alpaca Positions → Portfolio → StrategyEngine ← settings.yaml
                                    ↓
                        TradeSignal[] (priority-sorted)
                                    ↓
                        Guidelines (budget gate)
                                    ↓
                        AlpacaClient → Alpaca API
                                    ↓
                        spending_ledger.json (record)
```

### Strategy Fork

Each security in `config/settings.yaml` is assigned one of three modes (`StrategyMode` enum):

- **HOLD** — Do nothing unless stop-loss triggers (priority 10). Prevents premature selling when in losses.
- **CASH_OUT** — Sell signals: take-profit (priority 8), trailing-stop via watermark (9). Sell quantity is configurable as a percentage.
- **INCREASE_HOLDING** — Buy signals: buy-the-dip from watermark peak (priority 5), DCA on schedule (2). Optional profit protection sell (priority 8): triggers when price drops from peak while still above a minimum profit floor. Each buy signal is tagged with a `BuyType` (DCA or STRATEGY).

Evaluation happens in `StrategyEngine._evaluate_all()` which routes each holding to the appropriate fork based on its configured mode.

### Budget Model

Buy signals are gated by `InvestmentGuidelines` with **separate budgets** for DCA vs STRATEGY buy types. Both enforce daily limits; weekly/monthly/single-order limits are optional (0 = no limit). The spending ledger (`spending_ledger.json`) tracks executed trades for budget accounting.

### Persistent State (JSON files, no database)

- `config/watermarks.json` — Peak prices per symbol for trailing-stop calculations
- `spending_ledger.json` — Trade execution log for budget enforcement (auto-created)

## Key Modules

| Module | Role |
|--------|------|
| `src/models.py` | All dataclasses and enums (Holding, Portfolio, TradeSignal, TradingStrategy, StrategyMode, HoldParams, BuyType, etc.) |
| `src/strategy.py` | `StrategyEngine` — signal generation, the core evaluation logic |
| `src/guidelines.py` | Budget enforcement, spending ledger I/O, DCA timing, dedup |
| `src/runner.py` | Continuous mode loop: market hours check, evaluate, execute, sleep |
| `src/portfolio.py` | Portfolio display utilities |
| `src/config_loader.py` | YAML → dataclass tree (strategies + guidelines) |
| `src/alpaca_client.py` | Alpaca API wrapper (orders, market data, profiles, live portfolio builder) |
| `src/watermark.py` | High-water-mark persistence for trailing stops |

## Environment

Alpaca credentials in `.env` (loaded via python-dotenv):
```
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```

## Continuous Mode (`python main.py run`)

Runs autonomously during market hours (9:30 AM–4:00 PM ET):
- **Market check**: Uses Alpaca `get_clock()` — sleeps until open when closed
- **Live portfolio**: Builds Portfolio from Alpaca positions each cycle
- **DCA timing**: Tracks `last_dca_date` per symbol in the ledger; only fires DCA if interval elapsed
- **Signal dedup**: Checks ledger for today's executions; skips already-executed signals
- **Auto-execute**: No confirmation prompt; orders go straight to Alpaca
- **Config reload**: Reads `settings.yaml` each cycle — edit without restarting
- **Logging**: Writes to `logs/runner.log` for post-mortem diagnosis if the process dies
- **SIGHUP-safe**: Survives terminal disconnects (handles SIGHUP signal)

### Running with tmux (recommended)

Use `tmux` so the process survives Terminal.app crashes and macOS session restores:

```bash
tmux new -s invest
source .venv/bin/activate && caffeinate -i python main.py run --interval 5
# Detach: Ctrl+B, then D
# Reattach: tmux attach -t invest
```

## Dashboard

Streamlit app with 4 tabs (Portfolio, Trade Signals, Security Profiles, Strategies) and sidebar showing budget consumption. All data is live from Alpaca.
