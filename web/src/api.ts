import { generateClient } from 'aws-amplify/data';
import type { Schema } from '../../amplify/data/resource';

const client = generateClient<Schema>();

// ── Shapes returned by the Python query Lambda (a.json() fields) ──────────
export interface Holding {
  symbol: string;
  description: string;
  quantity: number;
  lastPrice: number;
  currentValue: number;
  costBasisTotal: number;
  averageCostBasis: number;
  gainLossDollar: number;
  gainLossPercent: number;
  todayGainLossDollar: number;
  todayGainLossPercent: number;
  percentOfAccount: number;
  costBasisPctOfAccount: number;
  week52High: number;
  week52Low: number;
}

export interface Portfolio {
  accountId: string;
  totalValue: number;
  investedValue: number;
  cashBalance: number;
  cashPct: number;
  todayGainLoss: number;
  totalGainLoss: number;
  // Deposit-adjusted returns per window (1M/6M/YTD/12M/ALL); absent windows omitted.
  // pct is Modified Dietz (external cash flows removed + time-weighted); the $ splits
  // into realized (sell P/L + dividends/interest − fees) and unrealized (residual).
  periodReturns?: Record<string, {
    realized: number;
    unrealized: number;
    total: number;
    pct: number | null;
    realizedPct: number | null;
    unrealizedPct: number | null;
  }>;
  holdings: Holding[];
}

export interface Signal {
  symbol: string;
  side: 'buy' | 'sell';
  buyType: 'dca' | 'strategy';
  quantity: number;
  estimatedValue: number;
  limitPrice: number | null;
  reason: string;
  priority: number;
  strategyMode: string | null;
}

export interface Budget {
  maxDaily: number;
  maxWeekly: number;
  maxMonthly: number;
  maxSingleOrder: number;
  spentToday: number;
  spentThisWeek: number;
  spentThisMonth: number;
}

export interface Status {
  tradingEnabled: boolean;
  dca: Budget;
  strategy: Budget;
}

export interface Profile {
  symbol: string;
  description: string;
  livePrice: number;
  avgCost: number;
  quantity: number;
  bars: { date: string; open: number; high: number; low: number; close: number; volume: number }[];
}

// Settings is the raw config dict (guidelines + per-symbol strategies).
export type Settings = Record<string, any>;

function unwrap<T>(r: { data: unknown; errors?: { message: string }[] }): T {
  if (r.errors?.length) throw new Error(r.errors.map((e) => e.message).join('; '));
  // a.json() may arrive as a JSON string depending on transport — normalise.
  const d: any = r.data;
  return (typeof d === 'string' ? JSON.parse(d) : d) as T;
}

export const api = {
  portfolio: () => client.queries.getPortfolio().then(unwrap<Portfolio>),
  signals: () => client.queries.getSignals().then(unwrap<Signal[]>),
  profiles: () => client.queries.getProfiles().then(unwrap<Profile[]>),
  status: () => client.queries.getStatus().then(unwrap<Status>),
  getSettings: () => client.queries.getSettings().then(unwrap<Settings>),
  saveSettings: (settings: Settings) =>
    // AppSync's AWSJSON scalar expects a JSON *string*, not a raw object — the
    // Amplify client passes custom-op args through verbatim, so stringify here
    // (the query Lambda json.loads() it back). Sending a raw object yields
    // "Variable 'settings' has an invalid value."
    client.mutations
      .saveSettings({ settings: JSON.stringify(settings) })
      .then(unwrap<Settings>),
};
