import axios from 'axios'

const api = axios.create({ baseURL: '/api/v1' })

export interface RuleRow {
  key: string
  label: string
  value: string | number | boolean | null
  default?: number
  help: string
  env: string | null
}

export interface PeriodStats {
  closed: number
  wins: number
  losses: number
  win_rate: number | null
  net_pnl: number
  gross_profit: number
  gross_loss: number
  profit_factor: number | null
  avg_win: number | null
  avg_loss: number | null
  expectancy: number | null
  best: number | null
  worst: number | null
  avg_hold_min: number | null
}

export interface DayTradeRow {
  id: number
  ticker: string
  status: 'open' | 'closed'
  outcome: 'win' | 'loss' | 'open'
  side: 'long' | 'short'
  qty: number
  entry_price: number
  stop_price: number | null
  target_price: number | null
  entry_time: string | null
  exit_price: number | null
  exit_time: string | null
  pnl: number | null
  pnl_pct: number | null
  exit_reason: string | null
  held_minutes: number | null
  bias: string | null
  quant_score: number | null
}

export interface DayTradingOverview {
  settings: {
    autopilot: boolean
    execution_live: boolean
    market_open: boolean
    trading_mode: 'paper' | 'live'
    entry_rules: RuleRow[]
    exit_rules: RuleRow[]
    risk_rules: RuleRow[]
    learning: { enabled: boolean; last_review: { date: string; notes: string[] } | null; note: string }
  }
  stats: { today: PeriodStats; week: PeriodStats; all: PeriodStats }
  open_trades: number
  daily: Array<{ day: string; trades: number; closed: number; wins: number; losses: number; pnl: number; cumulative: number }>
  exit_reasons: Record<string, { count: number; wins: number; pnl: number }>
  tickers: {
    best: Array<{ ticker: string; trades: number; wins: number; pnl: number }>
    worst: Array<{ ticker: string; trades: number; wins: number; pnl: number }>
  }
  trades: DayTradeRow[]
}

export const getDayTrading = () => api.get<DayTradingOverview>('/day-trading').then((r) => r.data)

export interface PatternBucket {
  dim: 'hour' | 'score' | 'bias' | 'side' | 'ticker' | 'rvol' | 'vix'
  bucket: string
  n: number
  wins: number
  win_rate: number
  net: number
  avg: number
  train_avg: number
  test_avg: number
  test_n: number
  avoid: boolean
}
export interface PatternReport {
  n: number
  with_features: number
  min_bucket: number
  buckets: PatternBucket[]
  avoid: PatternBucket[]
  blocked_hours: number[]
}
export const getPatterns = () => api.get<PatternReport>('/day-trading/patterns').then((r) => r.data)
