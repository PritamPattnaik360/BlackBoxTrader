export interface Position {
  ticker: string
  qty: number
  avg_entry_price: number
  current_price: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  market_value: number
  asset_class: string
}

export interface Account {
  equity: number
  cash: number
  buying_power: number
  portfolio_value: number
  day_trade_count: number
  trading_blocked: boolean
}

export interface Signal {
  id: number
  ticker: string
  composite_score: number
  confidence: number
  direction: 'BUY' | 'SELL' | 'HOLD'
  source_count: number
  news_score: number | null
  reddit_score: number | null
  raw_headlines: Array<{ title: string; source: string; score: string }> | null
  created_at: string
}

export interface BacktestResult {
  total_return: number | null
  cagr: number | null
  sharpe: number | null
  sortino: number | null
  max_drawdown: number | null
  calmar: number | null
  win_rate: number | null
  profit_factor: number | null
  total_trades: number | null
  equity_curve: Array<{ ts: string; value: number }> | null
  trade_log: Array<{
    entry_ts: string
    exit_ts: string
    entry_price: number
    exit_price: number
    qty: number
    pnl: number
    ticker?: string
    side?: string
    exit_reason?: string
  }> | null
}

export interface BacktestRun {
  run_id: number
  status: string
  tickers: string[]
  start_date: string
  end_date: string
  strategy_name: string
  result: BacktestResult | null
}

export interface LivePrice {
  ticker: string
  time: string
  close: number
  volume?: number
}

export interface TradingMode {
  trading_mode: 'paper' | 'live'
  execution_live: boolean
  autonomous: boolean
  alpaca_base_url: string
}

export interface Order {
  id: number
  alpaca_order_id: string | null
  ticker: string
  side: string
  order_type: string
  qty: number
  status: string
  filled_qty: number | null
  filled_avg_price: number | null
  source: 'auto' | 'manual'
  quant_score: number | null
  submitted_at: string
  filled_at: string | null
}
