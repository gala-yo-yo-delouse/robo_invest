import { useCallback, useEffect, useState, type ReactNode } from 'react';
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

// Where the current price sits within the 52-week range, 0–100 (-1 = unknown).
function rangePos(h: Holding): number {
  if (h.week52High <= 0 || h.week52Low <= 0) return -1;
  const span = h.week52High - h.week52Low;
  if (span <= 0) return 0;
  return Math.max(0, Math.min(100, ((h.lastPrice - h.week52Low) / span) * 100));
}

// 52-week "low – high" plus where the current price sits within that range.
function range52(h: Holding) {
  const pos = rangePos(h);
  if (pos < 0) return <span className="muted">—</span>;
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
// Column config drives both render and sort. First column is frozen on scroll.
type Col = {
  key: string;
  label: string;
  num: boolean;                       // numeric sort (else string)
  sortVal: (h: Holding) => number | string;
  render: (h: Holding) => ReactNode;
  cls?: (h: Holding) => string;       // colour class for the cell
};
const signCls = (n: number) => (n >= 0 ? 'pos' : 'neg');
const COLS: Col[] = [
  { key: 'symbol', label: 'Symbol', num: false, sortVal: (h) => h.symbol, render: (h) => h.symbol },
  { key: 'shares', label: 'Shares', num: true, sortVal: (h) => h.quantity, render: (h) => h.quantity.toFixed(2) },
  { key: 'price', label: 'Price', num: true, sortVal: (h) => h.lastPrice, render: (h) => usd(h.lastPrice) },
  { key: 'range', label: '52-Wk Range', num: true, sortVal: (h) => rangePos(h), render: (h) => range52(h) },
  { key: 'value', label: 'Value', num: true, sortVal: (h) => h.currentValue, render: (h) => usd(h.currentValue) },
  { key: 'cost', label: 'Cost Basis', num: true, sortVal: (h) => h.costBasisTotal, render: (h) => usd(h.costBasisTotal) },
  { key: 'acctCost', label: '% Acct (Cost)', num: true, sortVal: (h) => h.costBasisPctOfAccount, render: (h) => `${h.costBasisPctOfAccount.toFixed(1)}%` },
  { key: 'acctVal', label: '% Acct (Value)', num: true, sortVal: (h) => h.percentOfAccount, render: (h) => `${h.percentOfAccount.toFixed(1)}%` },
  { key: 'glTodayD', label: 'G/L Today', num: true, sortVal: (h) => h.todayGainLossDollar, render: (h) => usd(h.todayGainLossDollar), cls: (h) => signCls(h.todayGainLossDollar) },
  { key: 'glTodayP', label: '% Today', num: true, sortVal: (h) => h.todayGainLossPercent, render: (h) => pct(h.todayGainLossPercent), cls: (h) => signCls(h.todayGainLossPercent) },
  { key: 'glTotalD', label: 'G/L Total', num: true, sortVal: (h) => h.gainLossDollar, render: (h) => usd(h.gainLossDollar), cls: (h) => signCls(h.gainLossDollar) },
  { key: 'glTotalP', label: '% Total', num: true, sortVal: (h) => h.gainLossPercent, render: (h) => pct(h.gainLossPercent), cls: (h) => signCls(h.gainLossPercent) },
];

function PortfolioView() {
  const { data, error, loading } = useAsync<Portfolio>(api.portfolio);
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' }>({ key: 'value', dir: 'desc' });
  if (!data) return <Loader error={error} loading={loading} />;

  const pr = data.periodReturns ?? {};
  const totalCost = data.holdings.reduce((s, h) => s + h.costBasisTotal, 0);
  const prevTotal = data.totalValue - data.todayGainLoss;
  const unrealPct = totalCost > 0 ? (data.totalGainLoss / totalCost) * 100 : null;
  // Account-equity change per window — all the same measure (cash included).
  const returns: { label: string; dollar: number | null; pct: number | null }[] = [
    { label: 'Today', dollar: data.todayGainLoss, pct: prevTotal > 0 ? (data.todayGainLoss / prevTotal) * 100 : null },
    { label: '1M', dollar: pr['1M']?.dollar ?? null, pct: pr['1M']?.pct ?? null },
    { label: '6M', dollar: pr['6M']?.dollar ?? null, pct: pr['6M']?.pct ?? null },
    { label: 'YTD', dollar: pr['YTD']?.dollar ?? null, pct: pr['YTD']?.pct ?? null },
    { label: '12M', dollar: pr['12M']?.dollar ?? null, pct: pr['12M']?.pct ?? null },
    { label: 'All', dollar: pr['ALL']?.dollar ?? null, pct: pr['ALL']?.pct ?? null },
  ];

  const col = COLS.find((c) => c.key === sort.key) ?? COLS[0];
  const rows = [...data.holdings].sort((a, b) => {
    const va = col.sortVal(a), vb = col.sortVal(b);
    const cmp = typeof va === 'number' && typeof vb === 'number'
      ? va - vb : String(va).localeCompare(String(vb));
    return sort.dir === 'asc' ? cmp : -cmp;
  });
  const toggleSort = (c: Col) =>
    setSort((s) => (s.key === c.key
      ? { key: c.key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
      : { key: c.key, dir: c.num ? 'desc' : 'asc' }));

  return (
    <>
      <div className="summary">
        <div className="summary-head">
          <div>
            <div className="muted small">Total Value</div>
            <div className="total-value">{usd(data.totalValue)}</div>
          </div>
          <div className="summary-meta">
            <div><span className="muted small">Invested </span>{usd(data.investedValue)}</div>
            <div><span className="muted small">Cash </span>{usd(data.cashBalance)}{' '}
              <span className="muted small">({data.cashPct.toFixed(1)}%)</span></div>
            <div title="Unrealized P/L on currently held positions (vs cost basis)">
              <span className="muted small">Unrealized </span>
              <span className={signCls(data.totalGainLoss)}>
                {usd(data.totalGainLoss)}{unrealPct == null ? '' : ` (${pct(unrealPct)})`}
              </span>
            </div>
          </div>
        </div>
        <div className="returns" title="Account-equity change over each window (cash included)">
          {returns.map((r) => (
            <div className="ret" key={r.label}>
              <div className="muted small">{r.label}</div>
              <div className={r.dollar == null ? 'muted' : signCls(r.dollar)}>
                {r.dollar == null ? '—' : usd(r.dollar)}
              </div>
              <div className={`small ${r.pct == null ? 'muted' : signCls(r.pct)}`}>
                {r.pct == null ? '' : pct(r.pct)}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {COLS.map((c, ci) => (
                <th
                  key={c.key}
                  className={`sortable${ci === 0 ? ' sticky-col' : ''}`}
                  onClick={() => toggleSort(c)}
                  title="Click to sort"
                >
                  {c.label}{sort.key === c.key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((h) => (
              <tr key={h.symbol}>
                {COLS.map((c, ci) => (
                  <td key={c.key} className={`${ci === 0 ? 'sticky-col' : ''} ${c.cls ? c.cls(h) : ''}`}>
                    {c.render(h)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
          <div className="table-wrap">
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
      <div className="table-wrap">
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
      </div>
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
