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
  percentOfAccount: number;
}

export interface Portfolio {
  accountId: string;
  totalValue: number;
  investedValue: number;
  cashBalance: number;
  cashPct: number;
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
    client.mutations.saveSettings({ settings }).then(unwrap<Settings>),
};
