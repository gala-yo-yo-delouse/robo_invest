import { useCallback, useEffect, useState } from 'react';
import {
  api,
  type Holding,
  type Portfolio,
  type Profile,
  type Settings,
  type Signal,
  type Status,
} from './api';

const TABS = ['Portfolio', 'Signals', 'Profiles', 'Strategies'] as const;
type Tab = (typeof TABS)[number];

const usd = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
const pct = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`;

// 52-week "low – high" plus where the current price sits within that range.
function range52(h: Holding) {
  if (h.week52High <= 0 || h.week52Low <= 0) return <span className="muted">—</span>;
  const span = h.week52High - h.week52Low;
  const at = span > 0 ? ((h.lastPrice - h.week52Low) / span) * 100 : 0;
  const pos = Math.max(0, Math.min(100, at));
  return (
    <span title={`${pos.toFixed(0)}% of 52-week range`}>
      {usd(h.week52Low)} – {usd(h.week52High)}{' '}
      <span className="muted small">({pos.toFixed(0)}%)</span>
    </span>
  );
}

// Small async-data hook with loading/error states.
function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const run = useCallback(() => {
    setLoading(true);
    setError(null);
    fn()
      .then(setData)
      .catch((e) => setError(String(e?.message ?? e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(run, [run]);
  return { data, error, loading, reload: run };
}

function Loader({ error, loading }: { error: string | null; loading: boolean }) {
  if (loading) return <p className="muted">Loading live data from Alpaca…</p>;
  if (error) return <p className="error">⚠️ {error}</p>;
  return null;
}

// ── Portfolio ────────────────────────────────────────────────────────────
function PortfolioView() {
  const { data, error, loading } = useAsync<Portfolio>(api.portfolio);
  if (!data) return <Loader error={error} loading={loading} />;
  return (
    <>
      <div className="cards">
        <Card label="Total" value={usd(data.totalValue)} />
        <Card label="Invested" value={usd(data.investedValue)} />
        <Card label="Cash" value={usd(data.cashBalance)} sub={`${data.cashPct.toFixed(1)}%`} />
        <Card label="Gain/Loss Today" value={usd(data.todayGainLoss)}
              valueClass={data.todayGainLoss >= 0 ? 'pos' : 'neg'} />
        <Card label="Gain/Loss Total" value={usd(data.totalGainLoss)}
              valueClass={data.totalGainLoss >= 0 ? 'pos' : 'neg'} />
      </div>
      <table>
        <thead>
          <tr>
            <th>Symbol</th><th>Shares</th><th>Price</th>
            <th>52-Wk Range</th>
            <th>Value</th>
            <th>Cost Basis</th>
            <th>% Acct (Cost)</th><th>% Acct (Value)</th>
            <th>Gain/Loss Today</th><th>%</th>
            <th>Gain/Loss Total</th><th>%</th>
          </tr>
        </thead>
        <tbody>
          {data.holdings.map((h) => (
            <tr key={h.symbol}>
              <td>{h.symbol}</td>
              <td>{h.quantity.toFixed(2)}</td>
              <td>{usd(h.lastPrice)}</td>
              <td>{range52(h)}</td>
              <td>{usd(h.currentValue)}</td>
              <td>{usd(h.costBasisTotal)}</td>
              <td>{h.costBasisPctOfAccount.toFixed(1)}%</td>
              <td>{h.percentOfAccount.toFixed(1)}%</td>
              <td className={h.todayGainLossDollar >= 0 ? 'pos' : 'neg'}>{usd(h.todayGainLossDollar)}</td>
              <td className={h.todayGainLossPercent >= 0 ? 'pos' : 'neg'}>{pct(h.todayGainLossPercent)}</td>
              <td className={h.gainLossDollar >= 0 ? 'pos' : 'neg'}>{usd(h.gainLossDollar)}</td>
              <td className={h.gainLossPercent >= 0 ? 'pos' : 'neg'}>{pct(h.gainLossPercent)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

// ── Signals ──────────────────────────────────────────────────────────────
function SignalsView() {
  const { data, error, loading } = useAsync<Signal[]>(api.signals);
  if (!data) return <Loader error={error} loading={loading} />;
  if (data.length === 0) return <p className="muted">No trade signals — all positions within bounds.</p>;
  const group = (pred: (s: Signal) => boolean) => data.filter(pred);
  const sections: [string, Signal[]][] = [
    ['🔴 Sells', group((s) => s.side === 'sell')],
    ['🟡 Strategy Buys (dip)', group((s) => s.side === 'buy' && s.buyType === 'strategy')],
    ['🟢 DCA Buys', group((s) => s.side === 'buy' && s.buyType === 'dca')],
  ];
  return (
    <>
      {sections.filter(([, rows]) => rows.length > 0).map(([title, rows]) => (
        <div key={title}>
          <h3>{title}</h3>
          <table>
            <thead><tr><th>Symbol</th><th>Qty</th><th>Est. Value</th><th>Reason</th><th>Priority</th></tr></thead>
            <tbody>
              {rows.map((s, i) => (
                <tr key={i}>
                  <td>{s.symbol}</td>
                  <td>{s.quantity.toFixed(4)}</td>
                  <td>{usd(s.estimatedValue)}</td>
                  <td>{s.reason}</td>
                  <td>{s.priority}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </>
  );
}

// ── Profiles ─────────────────────────────────────────────────────────────
function ProfilesView() {
  const { data, error, loading } = useAsync<Profile[]>(api.profiles);
  if (!data) return <Loader error={error} loading={loading} />;
  return (
    <div className="cards">
      {data.map((p) => {
        const plPct = p.avgCost > 0 ? ((p.livePrice - p.avgCost) / p.avgCost) * 100 : 0;
        return (
          <div className="profile" key={p.symbol}>
            <div className="profile-head">
              <strong>{p.symbol}</strong>
              <span className={plPct >= 0 ? 'pos' : 'neg'}>{pct(plPct)}</span>
            </div>
            <div className="muted small">{p.description}</div>
            <div className="kv"><span>Live</span><span>{usd(p.livePrice)}</span></div>
            <div className="kv"><span>Avg cost</span><span>{usd(p.avgCost)}</span></div>
            <div className="kv"><span>Shares</span><span>{p.quantity.toFixed(2)}</span></div>
            <div className="kv"><span>Bars (90d)</span><span>{p.bars.length}</span></div>
          </div>
        );
      })}
    </div>
  );
}

// ── Strategies / Settings editor (read + write) ──────────────────────────
const MODES = ['increase_holding', 'cash_out', 'hold'] as const;

// Default param block when a security is switched to a given mode.
const MODE_DEFAULTS: Record<string, Record<string, number | null>> = {
  increase_holding: {
    dca_amount: 0, dca_interval_days: 7, buy_dip_pct: -10,
    min_profit_pct: 10, profit_trail_pct: -5, sell_quantity_pct: 100,
  },
  cash_out: { take_profit_pct: 25, trailing_stop_pct: null, sell_quantity_pct: 100 },
  hold: { stop_loss_pct: -15, sell_quantity_pct: 100 },
};

// Hover help per parameter (from settings.yaml docs).
const PARAM_HELP: Record<string, string> = {
  dca_amount: 'Fixed $ amount per scheduled DCA buy (0 = DCA off)',
  dca_interval_days: 'Days between DCA buys',
  buy_dip_pct: 'Buy when price drops this % from the watermark peak (e.g. -10)',
  min_profit_pct: 'Optional — minimum profit % to protect before a profit-trail sell',
  profit_trail_pct: 'Optional — sell when price drops this % from peak while above min profit',
  sell_quantity_pct: '% of position to sell when triggered (default 100)',
  take_profit_pct: 'Sell when price rises this % above average cost',
  trailing_stop_pct: 'Optional dynamic trailing stop %',
  stop_loss_pct: 'Sell if price drops this % below average cost (negative)',
};

function StrategiesView() {
  const { data, error, loading, reload } = useAsync<Settings>(api.getSettings);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [newSym, setNewSym] = useState('');
  const [newMode, setNewMode] = useState<string>('increase_holding');

  useEffect(() => { if (data) setDraft(structuredClone(data)); }, [data]);
  if (!draft) return <Loader error={error} loading={loading} />;

  const g = draft.guidelines ?? {};
  const setGuideline = (path: string[], val: any) => {
    const next = structuredClone(draft);
    let o = next.guidelines ?? (next.guidelines = {});
    for (let i = 0; i < path.length - 1; i++) o = o[path[i]] ?? (o[path[i]] = {});
    o[path[path.length - 1]] = val;
    setDraft(next);
  };
  const setParam = (sym: string, modeKey: string, key: string, val: any) => {
    const next = structuredClone(draft);
    next.strategies[sym][modeKey][key] = val;
    setDraft(next);
  };
  const setEnabled = (sym: string, val: boolean) => {
    const next = structuredClone(draft);
    next.strategies[sym].enabled = val;
    setDraft(next);
  };
  const setMode = (sym: string, mode: string) => {
    const next = structuredClone(draft);
    const s = next.strategies[sym];
    s.mode = mode;
    // Seed the new mode's param block with defaults if it doesn't exist yet
    // (a previously-used mode's block is preserved, so toggling back keeps values).
    if (!s[mode]) s[mode] = { ...MODE_DEFAULTS[mode] };
    setDraft(next);
  };
  // Reordering rewrites the strategies object key order; that order is the
  // priority/budget order the engine uses (earlier = funded first).
  const moveSymbol = (sym: string, dir: 'up' | 'down') => {
    const entries = Object.entries(draft.strategies as Record<string, any>);
    const i = entries.findIndex(([k]) => k === sym);
    const j = dir === 'up' ? i - 1 : i + 1;
    if (j < 0 || j >= entries.length) return;
    [entries[i], entries[j]] = [entries[j], entries[i]];
    setDraft({ ...draft, strategies: Object.fromEntries(entries) });
  };
  const addSymbol = () => {
    const sym = newSym.trim().toUpperCase();
    if (!sym) return;
    if ((draft.strategies as Record<string, any>)[sym]) {
      setMsg(`⚠️ ${sym} already exists`);
      return;
    }
    const next = structuredClone(draft);
    next.strategies[sym] = { mode: newMode, enabled: true, [newMode]: { ...MODE_DEFAULTS[newMode] } };
    setDraft(next);
    setNewSym('');
    setMsg(null);
  };
  const removeSymbol = (sym: string) => {
    const next = structuredClone(draft);
    delete next.strategies[sym];
    setDraft(next);
  };

  const save = async () => {
    setSaving(true);
    setMsg(null);
    try {
      await api.saveSettings(draft);
      setMsg('✓ Saved. The bot picks this up on its next cycle.');
      reload();
    } catch (e: any) {
      setMsg(`⚠️ ${e?.message ?? e}`);
    } finally {
      setSaving(false);
    }
  };

  const numInput = (val: any, onChange: (n: number | null) => void) => (
    <input
      type="number"
      step="any"
      value={val ?? ''}
      onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
    />
  );

  return (
    <>
      <h3>Global Guidelines</h3>
      <label className="toggle">
        <input
          type="checkbox"
          checked={!!g.trading_enabled}
          onChange={(e) => setGuideline(['trading_enabled'], e.target.checked)}
        />
        Trading enabled
      </label>
      <table>
        <thead><tr><th>Budget</th><th>Daily</th><th>Weekly</th><th>Monthly</th><th>Single order</th></tr></thead>
        <tbody>
          {(['dca', 'strategy'] as const).map((b) => (
            <tr key={b}>
              <td>{b.toUpperCase()}</td>
              <td>{numInput(g[b]?.max_daily, (v) => setGuideline([b, 'max_daily'], v))}</td>
              <td>{numInput(g[b]?.max_weekly, (v) => setGuideline([b, 'max_weekly'], v))}</td>
              <td>{numInput(g[b]?.max_monthly, (v) => setGuideline([b, 'max_monthly'], v))}</td>
              <td>{numInput(g[b]?.max_single_order, (v) => setGuideline([b, 'max_single_order'], v))}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">
        Two separate wallets. <strong>DCA</strong> funds scheduled DCA buys;{' '}
        <strong>Strategy</strong> funds buy-the-dip signals. Each buy is checked against
        its wallet's single / daily / weekly / monthly caps (0 = no limit) and{' '}
        <em>reserved as it's approved</em>, in the security order below — so when a wallet
        runs low, symbols higher in the list are funded first. The wallets are independent:
        DCA buys never draw down the Strategy budget, or vice-versa.
      </p>

      <h3>Per-Security Strategies</h3>
      <p className="muted small">
        Order = priority. When budget is tight, symbols higher in this list are funded first.
        Use ▲▼ to reorder.
      </p>
      <div className="addsym">
        <input
          placeholder="Ticker (e.g. TSLA)"
          value={newSym}
          onChange={(e) => setNewSym(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') addSymbol(); }}
        />
        <select value={newMode} onChange={(e) => setNewMode(e.target.value)}>
          {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <button onClick={addSymbol}>+ Add symbol</button>
      </div>
      {Object.entries(draft.strategies as Record<string, any>).map(([sym, s], idx, arr) => {
        const modeKey = s.mode as string; // 'increase_holding' | 'cash_out' | 'hold'
        const params = s[modeKey] ?? {};
        return (
          <div className="strat" key={sym}>
            <div className="strat-head">
              <span className="rank">{idx + 1}</span>
              <strong>{sym}</strong>
              <select
                className="mode-select"
                value={modeKey}
                onChange={(e) => setMode(sym, e.target.value)}
                title="Strategy type — switching swaps in that mode's parameters"
              >
                {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
              <label className="toggle">
                <input type="checkbox" checked={!!s.enabled} onChange={(e) => setEnabled(sym, e.target.checked)} />
                enabled
              </label>
              <span className="reorder">
                <button onClick={() => moveSymbol(sym, 'up')} disabled={idx === 0} title="Move up (higher priority)">▲</button>
                <button onClick={() => moveSymbol(sym, 'down')} disabled={idx === arr.length - 1} title="Move down">▼</button>
                <button onClick={() => removeSymbol(sym)} className="remove" title="Remove symbol">✕</button>
              </span>
            </div>
            <div className="params">
              {Object.keys(params).map((k) => (
                <label key={k} className="param" title={PARAM_HELP[k] ?? ''}>
                  <span>{k} {PARAM_HELP[k] ? <span className="help">ⓘ</span> : null}</span>
                  {numInput(params[k], (v) => setParam(sym, modeKey, k, v))}
                </label>
              ))}
            </div>
          </div>
        );
      })}

      <div className="savebar">
        <button onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save settings'}</button>
        {msg && <span className={msg.startsWith('✓') ? 'pos' : 'error'}>{msg}</span>}
      </div>
    </>
  );
}

function Card({ label, value, sub, valueClass }:
    { label: string; value: string; sub?: string; valueClass?: string }) {
  return (
    <div className="card">
      <div className="muted small">{label}</div>
      <div className={`card-value${valueClass ? ' ' + valueClass : ''}`}>{value}</div>
      {sub && <div className="muted small">{sub}</div>}
    </div>
  );
}

// ── Sidebar (budget status) ──────────────────────────────────────────────
function Sidebar({ signOut, username }: { signOut?: () => void; username?: string }) {
  const { data } = useAsync<Status>(api.status);
  return (
    <aside className="sidebar">
      <h2>⚙️ Status</h2>
      {data ? (
        <>
          <div className={`pill ${data.tradingEnabled ? 'pos' : 'neg'}`}>
            Trading {data.tradingEnabled ? 'ON' : 'OFF'}
          </div>
          <div className="budget">
            <div className="muted small">DCA daily</div>
            <div>{usd(data.dca.spentToday)} / {usd(data.dca.maxDaily)}</div>
          </div>
          <div className="budget">
            <div className="muted small">Strategy daily</div>
            <div>{usd(data.strategy.spentToday)} / {usd(data.strategy.maxDaily)}</div>
          </div>
        </>
      ) : (
        <p className="muted small">Loading…</p>
      )}
      <div className="spacer" />
      <div className="muted small">{username}</div>
      <button className="signout" onClick={signOut}>Sign out</button>
    </aside>
  );
}

export default function App({ signOut, username }: { signOut?: () => void; username?: string }) {
  const [tab, setTab] = useState<Tab>('Portfolio');
  return (
    <div className="layout">
      <Sidebar signOut={signOut} username={username} />
      <main>
        <header>
          <h1>📊 Investment Assistant</h1>
          <nav>
            {TABS.map((t) => (
              <button key={t} className={t === tab ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>
            ))}
          </nav>
        </header>
        {tab === 'Portfolio' && <PortfolioView />}
        {tab === 'Signals' && <SignalsView />}
        {tab === 'Profiles' && <ProfilesView />}
        {tab === 'Strategies' && <StrategiesView />}
      </main>
    </div>
  );
}
