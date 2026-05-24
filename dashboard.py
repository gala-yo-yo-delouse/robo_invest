"""Investment Assistant — Streamlit Dashboard."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

from src.alpaca_client import AlpacaClient
from src.config_loader import build_guidelines, build_strategies, load_config
from src.guidelines import load_guidelines_with_spending
from src.models import BuyType, StrategyMode, OrderSide
from src.strategy import StrategyEngine

CONFIG_PATH = Path(__file__).parent / "config" / "settings.yaml"

st.set_page_config(
    page_title="Investment Assistant",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Data Loading (cached) ─────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_data():
    client = AlpacaClient()
    portfolio = client.build_portfolio()
    config = load_config(CONFIG_PATH)
    guidelines = build_guidelines(config)
    strategies = build_strategies(config)
    return portfolio, config, guidelines, strategies


@st.cache_data(ttl=300)
def fetch_live_profiles(symbols: list[str]):
    """Fetch live security profiles from Alpaca."""
    try:
        from src.alpaca_client import AlpacaClient
        client = AlpacaClient()
        profiles = {}
        for symbol in symbols:
            profiles[symbol] = {
                "price": client.get_current_price(symbol),
            }
            try:
                from datetime import datetime, timedelta
                bar_list = list(client.api.get_bars(
                    symbol, "1Day",
                    start=(datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"),
                ))
                profiles[symbol]["bars"] = [
                    {"date": str(b.t)[:10], "open": float(b.o), "high": float(b.h),
                     "low": float(b.l), "close": float(b.c), "volume": int(b.v)}
                    for b in bar_list
                ]
            except Exception:
                profiles[symbol]["bars"] = []
        return profiles, True
    except Exception as e:
        return {}, False


portfolio, config, guidelines, strategies = load_data()
guidelines = load_guidelines_with_spending(guidelines)


# ── Sidebar ───────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚙️ Controls")
    st.divider()
    st.subheader("DCA Budget")
    dca = guidelines.dca
    st.metric("Daily", f"${dca.spent_today:,.0f} / ${dca.max_daily:,.0f}")

    st.divider()
    st.subheader("Strategy Budget")
    strat = guidelines.strategy
    st.metric("Daily", f"${strat.spent_today:,.0f} / ${strat.max_daily:,.0f}")

    st.divider()
    st.caption(f"Trading: **{'Enabled' if guidelines.trading_enabled else 'Disabled'}**")


# ── Live data ─────────────────────────────────────────────────────────

with st.spinner("Fetching live data from Alpaca..."):
    live_profiles, alpaca_connected = fetch_live_profiles(list(portfolio.holdings.keys()))


# ── Header ────────────────────────────────────────────────────────────

st.title("📊 Investment Assistant")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Portfolio", f"${portfolio.total_value:,.2f}")
col2.metric("Invested", f"${portfolio.invested_value:,.2f}")
col3.metric("Cash", f"${portfolio.cash_balance:,.2f}", f"{portfolio.cash_pct:.1f}%")

total_gl = sum(h.total_gain_loss_dollar for h in portfolio.holdings.values())
total_gl_pct = (total_gl / sum(h.cost_basis_total for h in portfolio.holdings.values()) * 100
                if sum(h.cost_basis_total for h in portfolio.holdings.values()) > 0 else 0)
col4.metric("Total Gain/Loss", f"${total_gl:+,.2f}", f"{total_gl_pct:+.1f}%")

if alpaca_connected:
    st.caption("🟢 Connected to Alpaca (Paper)")

st.divider()

# ── Portfolio Allocation & Holdings ───────────────────────────────────

tab_overview, tab_signals, tab_profiles, tab_strategies = st.tabs(
    ["📈 Portfolio", "🎯 Trade Signals", "🔍 Security Profiles", "⚙️ Strategies"]
)

with tab_overview:
    chart_col, table_col = st.columns([1, 1.5])

    with chart_col:
        # Allocation pie chart
        labels = list(portfolio.holdings.keys()) + ["Cash"]
        values = [h.current_value for h in portfolio.holdings.values()] + [portfolio.cash_balance]
        colors = px.colors.qualitative.Set3

        fig_pie = px.pie(
            names=labels, values=values,
            title="Portfolio Allocation",
            color_discrete_sequence=colors,
            hole=0.4,
        )
        fig_pie.update_traces(textinfo="label+percent", textposition="outside")
        fig_pie.update_layout(height=420, margin=dict(t=40, b=20, l=20, r=20),
                              showlegend=False)
        st.plotly_chart(fig_pie, use_container_width=True)

    with table_col:
        # Holdings table
        rows = []
        for sym, h in sorted(portfolio.holdings.items(), key=lambda x: x[1].current_value, reverse=True):
            strategy = strategies.get(sym)
            mode = strategy.mode.value.replace("_", " ").title() if strategy else "—"
            rows.append({
                "Symbol": sym,
                "Shares": f"{h.quantity:.2f}",
                "Price": f"${h.last_price:,.2f}",
                "Value": f"${h.current_value:,.2f}",
                "Cost Basis": f"${h.cost_basis_total:,.2f}",
                "Gain/Loss": f"${h.total_gain_loss_dollar:+,.2f}",
                "G/L %": f"{h.total_gain_loss_percent:+.1f}%",
                "Strategy": mode,
            })
        df_holdings = pd.DataFrame(rows)
        st.dataframe(df_holdings, use_container_width=True, hide_index=True, height=400)

    # Gain/Loss bar chart
    gl_data = pd.DataFrame([
        {"Symbol": sym, "Gain/Loss $": h.total_gain_loss_dollar,
         "Gain/Loss %": h.total_gain_loss_percent}
        for sym, h in sorted(portfolio.holdings.items(), key=lambda x: x[1].total_gain_loss_dollar)
    ])
    fig_gl = px.bar(
        gl_data, x="Symbol", y="Gain/Loss $",
        color="Gain/Loss $",
        color_continuous_scale=["#ef4444", "#fbbf24", "#22c55e"],
        title="Gain / Loss by Position",
    )
    fig_gl.update_layout(height=320, margin=dict(t=40, b=20))
    st.plotly_chart(fig_gl, use_container_width=True)


# ── Trade Signals ─────────────────────────────────────────────────────

with tab_signals:
    price_fetcher = None
    if alpaca_connected:
        price_fetcher = lambda sym: live_profiles.get(sym, {}).get("price", 0.0)

    engine = StrategyEngine(portfolio, strategies, guidelines, price_fetcher)
    signals = engine.evaluate_all()

    if not signals:
        st.info("No trade signals at this time. All positions are within their strategy bounds.")
    else:
        sell_signals = [s for s in signals if s.side == OrderSide.SELL]
        dca_signals = [s for s in signals if s.side == OrderSide.BUY and s.buy_type == BuyType.DCA]
        strat_signals = [s for s in signals if s.side == OrderSide.BUY and s.buy_type == BuyType.STRATEGY]

        def _signal_table(sigs):
            return pd.DataFrame([{
                "Symbol": s.symbol,
                "Qty": f"{s.quantity:.4f}",
                "Est. Value": f"${s.estimated_value:,.2f}",
                "Reason": s.reason,
                "Priority": s.priority,
            } for s in sigs])

        if sell_signals:
            st.subheader("🔴 Sell Signals")
            st.dataframe(_signal_table(sell_signals), use_container_width=True, hide_index=True)

        if strat_signals:
            st.subheader("🟡 Strategy Buys (dip)")
            st.dataframe(_signal_table(strat_signals), use_container_width=True, hide_index=True)

        if dca_signals:
            st.subheader("🟢 DCA Buys (scheduled)")
            st.dataframe(_signal_table(dca_signals), use_container_width=True, hide_index=True)

        st.divider()
        scol1, scol2, scol3 = st.columns(3)
        total_sell = sum(s.estimated_value for s in sell_signals)
        total_strat = sum(s.estimated_value for s in strat_signals)
        total_dca = sum(s.estimated_value for s in dca_signals)
        scol1.metric("Sells", f"${total_sell:,.2f}")
        scol2.metric("Strategy Buys", f"${total_strat:,.2f}")
        scol3.metric("DCA Buys", f"${total_dca:,.2f}")


# ── Security Profiles ────────────────────────────────────────────────

with tab_profiles:
    if not alpaca_connected:
        st.error("Could not connect to Alpaca. Check your API keys in `.env`.")
    else:
        for sym in sorted(portfolio.holdings.keys()):
            holding = portfolio.holdings[sym]
            profile_data = live_profiles.get(sym, {})
            bars = profile_data.get("bars", [])

            with st.expander(f"**{sym}** — {holding.description}", expanded=False):
                mcol1, mcol2, mcol3, mcol4 = st.columns(4)
                live_price = profile_data.get("price", holding.last_price)
                mcol1.metric("Live Price", f"${live_price:,.2f}")
                mcol2.metric("Avg Cost", f"${holding.average_cost_basis:,.2f}")
                mcol3.metric("Shares", f"{holding.quantity:.2f}")
                gl_pct = ((live_price - holding.average_cost_basis) / holding.average_cost_basis * 100
                          if holding.average_cost_basis > 0 else 0)
                mcol4.metric("P/L", f"{gl_pct:+.1f}%")

                if bars:
                    df_bars = pd.DataFrame(bars)
                    df_bars["date"] = pd.to_datetime(df_bars["date"])

                    fig = go.Figure(data=[go.Candlestick(
                        x=df_bars["date"],
                        open=df_bars["open"], high=df_bars["high"],
                        low=df_bars["low"], close=df_bars["close"],
                        name=sym,
                    )])
                    # Add avg cost line
                    fig.add_hline(
                        y=holding.average_cost_basis,
                        line_dash="dash", line_color="orange",
                        annotation_text=f"Avg Cost ${holding.average_cost_basis:.2f}",
                    )
                    fig.update_layout(
                        height=350, xaxis_rangeslider_visible=False,
                        margin=dict(t=20, b=20, l=40, r=20),
                        yaxis_title="Price",
                    )
                    st.plotly_chart(fig, use_container_width=True)

                    # Volume bar chart below
                    fig_vol = px.bar(df_bars, x="date", y="volume", title="Volume")
                    fig_vol.update_layout(height=150, margin=dict(t=30, b=10, l=40, r=20))
                    st.plotly_chart(fig_vol, use_container_width=True)


# ── Strategies ────────────────────────────────────────────────────────

with tab_strategies:
    st.subheader("Per-Security Strategy Configuration")
    st.caption("Edit `config/settings.yaml` to change these values, then refresh.")

    cash_out_rows = []
    increase_rows = []
    hold_rows = []

    for sym, strat in sorted(strategies.items()):
        if strat.mode == StrategyMode.CASH_OUT and strat.cash_out:
            p = strat.cash_out
            cash_out_rows.append({
                "Symbol": sym,
                "Enabled": "✅" if strat.enabled else "❌",
                "Take Profit": f"{p.take_profit_pct}%",
                "Trailing Stop": f"{p.trailing_stop_pct}%" if p.trailing_stop_pct else "—",
                "Sell Qty %": f"{p.sell_quantity_pct}%",
            })
        elif strat.mode == StrategyMode.INCREASE_HOLDING and strat.increase_holding:
            p = strat.increase_holding
            increase_rows.append({
                "Symbol": sym,
                "Enabled": "✅" if strat.enabled else "❌",
                "DCA Amount": f"${p.dca_amount:,.0f}" if p.dca_amount > 0 else "—",
                "DCA Interval": f"{p.dca_interval_days}d" if p.dca_amount > 0 else "—",
                "Buy Dip": f"{p.buy_dip_pct}%",
            })
        elif strat.mode == StrategyMode.HOLD and strat.hold:
            p = strat.hold
            hold_rows.append({
                "Symbol": sym,
                "Enabled": "✅" if strat.enabled else "❌",
                "Stop Loss": f"{p.stop_loss_pct}%",
                "Sell Qty %": f"{p.sell_quantity_pct}%",
            })

    if cash_out_rows:
        st.markdown("#### 🔴 Cash-Out Strategies")
        st.dataframe(pd.DataFrame(cash_out_rows), use_container_width=True, hide_index=True)

    if hold_rows:
        st.markdown("#### 🟡 Hold Strategies")
        st.dataframe(pd.DataFrame(hold_rows), use_container_width=True, hide_index=True)

    if increase_rows:
        st.markdown("#### 🟢 Increase-Holding Strategies")
        st.dataframe(pd.DataFrame(increase_rows), use_container_width=True, hide_index=True)
