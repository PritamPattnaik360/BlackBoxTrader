import { useState, useEffect, useMemo } from 'react'
import { useMutation } from '@tanstack/react-query'
import { submitBacktest, getBacktestResult } from '../api/backtest'
import type { BacktestRun } from '../types'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import dayjs from 'dayjs'
import { FlaskConical, Info } from 'lucide-react'

// ── Strategy catalogue ────────────────────────────────────────────────────────

const STRATEGIES = [
  {
    value: 'nlp_proxy',
    label: 'NLP Proxy — RSI + MACD',
    intraday: false,
    explain:
      'Simulates the live NLP signal using RSI(14) and MACD histogram crossovers on daily bars. ' +
      'Buys when RSI < 40 and MACD turns positive; sells when RSI > 65 or MACD turns negative. ' +
      'Use this for long date ranges (1–5 years) to benchmark the daily strategy.',
  },
  {
    value: 'sma_crossover',
    label: 'SMA Crossover — 20 / 50 day',
    intraday: false,
    explain:
      'Classic moving-average trend-following benchmark. Enters long when the 20-day SMA crosses ' +
      'above the 50-day SMA; exits when it crosses back below. No NLP — pure price action. ' +
      'Good for comparing the AI strategy against a simple baseline.',
  },
  {
    value: 'intraday_orb',
    label: 'Intraday ORB + VWAP (day trading)',
    intraday: true,
    explain:
      'Mirrors the live day-trading engine on 5-minute bars. Enters long when price breaks above ' +
      "the first 30 min's high (Opening Range High) AND is above the session VWAP AND 5-bar momentum " +
      'is positive. Exits on a VWAP cross, a hard stop, or end of day — no overnight holds. ' +
      'yfinance only provides 60 days of free 5-minute data, so date range is capped automatically.',
  },
]

// ── Metric explanations ───────────────────────────────────────────────────────

const METRIC_INFO: Record<string, string> = {
  'Total Return': 'Total gain or loss from start to end of the period.',
  CAGR: 'Compound Annual Growth Rate — annualised return if the test ran exactly one year.',
  Sharpe: 'Return per unit of total risk. >1 is good, >2 is excellent.',
  Sortino: 'Like Sharpe but only penalises downside volatility — a better metric for traders.',
  'Max Drawdown': 'Worst peak-to-trough decline. Shows the worst loss you would have experienced.',
  Calmar: 'CAGR ÷ Max Drawdown — how much return you earn per unit of drawdown risk.',
  'Win Rate': 'Percentage of closed trades that made money.',
  'Profit Factor': 'Gross wins ÷ gross losses. >1.2 is decent; >1.5 is good.',
}

const EXIT_INFO: Record<string, string> = {
  stop: 'Price fell through the hard stop (entry × 0.995) — cut loss early.',
  vwap_cross: 'Price crossed back below VWAP — momentum reversed, exit triggered.',
  eod: 'End of day forced close — strategy never holds overnight.',
}

// ── Sub-components ────────────────────────────────────────────────────────────

function MetricCard({ label, value, format = 'pct' }: { label: string; value: number | null; format?: 'pct' | 'num' | 'dollar' }) {
  const info = METRIC_INFO[label]
  if (value == null) {
    return (
      <div className="bg-gray-800 rounded-lg p-3" title={info}>
        <div className="text-xs text-gray-500">{label}</div>
        <div className="text-lg font-bold text-gray-600">—</div>
      </div>
    )
  }
  const formatted =
    format === 'pct' ? `${(value * 100).toFixed(2)}%`
    : format === 'dollar' ? `$${value.toLocaleString()}`
    : value.toFixed(3)
  const positive = value >= 0
  return (
    <div className="bg-gray-800 rounded-lg p-3 cursor-help" title={info}>
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className={`text-lg font-bold ${positive ? 'text-green-400' : 'text-red-400'}`}>{formatted}</div>
    </div>
  )
}

function ExplainBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-3 bg-blue-950/30 border border-blue-900/50 rounded-xl px-4 py-3 text-xs text-gray-400 leading-relaxed">
      <Info size={14} className="text-blue-400 flex-shrink-0 mt-0.5" />
      <div>{children}</div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Backtest() {
  const today = dayjs().format('YYYY-MM-DD')
  const sixtyDaysAgo = dayjs().subtract(59, 'day').format('YYYY-MM-DD')
  const oneYearAgo = dayjs().subtract(1, 'year').format('YYYY-MM-DD')

  const [tickers, setTickers] = useState('AAPL,NVDA,MSFT')
  const [startDate, setStartDate] = useState(oneYearAgo)
  const [endDate, setEndDate] = useState(today)
  const [capital, setCapital] = useState('100000')
  const [strategy, setStrategy] = useState('nlp_proxy')
  const [orbMinutes, setOrbMinutes] = useState('30')
  const [stopPct, setStopPct] = useState('0.005')
  const [runId, setRunId] = useState<number | null>(null)
  const [result, setResult] = useState<BacktestRun | null>(null)
  const [polling, setPolling] = useState(false)

  const selectedStrategy = STRATEGIES.find((s) => s.value === strategy)!
  const isIntraday = selectedStrategy.intraday

  // Auto-adjust date range when switching to intraday
  useEffect(() => {
    if (isIntraday) {
      setStartDate(sixtyDaysAgo)
      setEndDate(today)
    } else {
      setStartDate(oneYearAgo)
      setEndDate(today)
    }
  }, [isIntraday])

  const submit = useMutation({
    mutationFn: submitBacktest,
    onSuccess: (data) => {
      setRunId(data.run_id)
      setPolling(true)
      setResult(null)
    },
  })

  useEffect(() => {
    if (!polling || !runId) return
    const interval = setInterval(async () => {
      const r = await getBacktestResult(runId)
      if (r.status === 'done' || r.status === 'error') {
        setResult(r)
        setPolling(false)
      }
    }, 2000)
    return () => clearInterval(interval)
  }, [polling, runId])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const params: Record<string, unknown> = {}
    if (isIntraday) {
      params.orb_minutes = parseInt(orbMinutes, 10)
      params.stop_pct = parseFloat(stopPct)
    }
    submit.mutate({
      tickers: tickers.split(',').map((t) => t.trim().toUpperCase()).filter(Boolean),
      start_date: startDate,
      end_date: endDate,
      initial_capital: parseFloat(capital),
      strategy_name: strategy,
      params: Object.keys(params).length > 0 ? params : undefined,
    })
  }

  // Compute exit_reason_summary from trade_log (intraday only)
  const exitSummary = useMemo(() => {
    const log = result?.result?.trade_log
    if (!log || log.length === 0) return null
    const hasReasons = log.some((t) => t.exit_reason)
    if (!hasReasons) return null
    const grouped: Record<string, { count: number; total_pnl: number }> = {}
    for (const t of log) {
      const r = t.exit_reason || 'unknown'
      if (!grouped[r]) grouped[r] = { count: 0, total_pnl: 0 }
      grouped[r].count++
      grouped[r].total_pnl += t.pnl
    }
    return Object.entries(grouped).map(([reason, s]) => ({
      reason,
      count: s.count,
      total_pnl: s.total_pnl,
      avg_pnl: s.total_pnl / s.count,
    }))
  }, [result])

  const hasMultipleTickers = (result?.result?.trade_log ?? []).some((t) => t.ticker)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold mb-3">Backtest</h1>
        <ExplainBox>
          Replay a trading strategy on real historical data to see how it would have performed before risking real money.
          Choose a strategy, set the date range and tickers, then hit <strong className="text-gray-300">Run Backtest</strong>.
          Results include an equity curve, trade-by-trade log, and performance metrics.
          Hover any metric card to see what it means.
        </ExplainBox>
      </div>

      {/* ── Form ── */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-5 space-y-4">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="col-span-2 lg:col-span-1">
              <label className="text-xs text-gray-500 block mb-1">Tickers (comma-separated)</label>
              <input
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
                value={tickers}
                onChange={(e) => setTickers(e.target.value)}
                placeholder="AAPL,NVDA,MSFT"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-1">Start Date</label>
              <input
                type="date"
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
                value={startDate}
                max={endDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-1">End Date</label>
              <input
                type="date"
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
                value={endDate}
                max={today}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-1">Initial Capital ($)</label>
              <input
                type="number"
                min="1000"
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
                value={capital}
                onChange={(e) => setCapital(e.target.value)}
              />
            </div>
          </div>

          {/* Strategy selector */}
          <div>
            <label className="text-xs text-gray-500 block mb-1">Strategy</label>
            <select
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
            >
              {STRATEGIES.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
            <p className="text-xs text-gray-500 mt-1.5 leading-relaxed">{selectedStrategy.explain}</p>
          </div>

          {/* Intraday params */}
          {isIntraday && (
            <div className="grid grid-cols-2 gap-4 pt-1">
              <div>
                <label className="text-xs text-gray-500 block mb-1">Opening Range (minutes)</label>
                <select
                  className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
                  value={orbMinutes}
                  onChange={(e) => setOrbMinutes(e.target.value)}
                >
                  <option value="15">15 min — tighter range, more breakouts</option>
                  <option value="30">30 min — standard (recommended)</option>
                  <option value="45">45 min — wider range, stronger signals</option>
                  <option value="60">60 min — very conservative</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">Hard Stop Loss</label>
                <select
                  className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
                  value={stopPct}
                  onChange={(e) => setStopPct(e.target.value)}
                >
                  <option value="0.003">0.3% — very tight, cuts losses fast</option>
                  <option value="0.005">0.5% — standard (recommended)</option>
                  <option value="0.008">0.8% — gives more room to breathe</option>
                  <option value="0.01">1.0% — wide stop</option>
                </select>
              </div>
            </div>
          )}

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={submit.isPending || polling}
              className="flex items-center gap-2 px-5 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium disabled:opacity-50"
            >
              <FlaskConical size={14} />
              {polling ? 'Running...' : 'Run Backtest'}
            </button>
            {isIntraday && (
              <span className="text-xs text-yellow-500">
                ⚠ 5-min data capped at 60 days — start date auto-set to {sixtyDaysAgo}
              </span>
            )}
          </div>
        </form>
      </div>

      {/* ── Running spinner ── */}
      {polling && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-8 text-center text-gray-400">
          <div className="animate-spin w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-3" />
          Running backtest — this may take 10–30 seconds for large date ranges…
        </div>
      )}

      {/* ── Results ── */}
      {result?.result && (
        <div className="space-y-4">
          {/* Metrics */}
          <div className="grid grid-cols-4 lg:grid-cols-8 gap-3">
            <MetricCard label="Total Return" value={result.result.total_return} format="pct" />
            <MetricCard label="CAGR"          value={result.result.cagr}          format="pct" />
            <MetricCard label="Sharpe"        value={result.result.sharpe}        format="num" />
            <MetricCard label="Sortino"       value={result.result.sortino}       format="num" />
            <MetricCard label="Max Drawdown"  value={result.result.max_drawdown}  format="pct" />
            <MetricCard label="Calmar"        value={result.result.calmar}        format="num" />
            <MetricCard label="Win Rate"      value={result.result.win_rate}      format="pct" />
            <div className="bg-gray-800 rounded-lg p-3">
              <div className="text-xs text-gray-500 mb-1">Profit Factor</div>
              <div className={`text-lg font-bold ${(result.result.profit_factor ?? 0) >= 1 ? 'text-green-400' : 'text-red-400'}`}>
                {result.result.profit_factor != null ? result.result.profit_factor.toFixed(2) : '—'}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 text-xs text-gray-400 px-1">
            <span>Total trades: <span className="text-white font-medium">{result.result.total_trades ?? '—'}</span></span>
            <span>Strategy: <span className="text-white font-medium">{result.strategy_name}</span> · {result.tickers.join(', ')}</span>
          </div>

          {/* Exit reason breakdown (intraday only) */}
          {exitSummary && (
            <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
              <div className="text-sm font-medium mb-3">Exit Reason Breakdown</div>
              <div className="grid grid-cols-3 gap-3">
                {exitSummary.map(({ reason, count, total_pnl, avg_pnl }) => (
                  <div key={reason} className="bg-gray-800 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-medium text-gray-300 capitalize">{reason.replace('_', ' ')}</span>
                      <span className="text-xs text-gray-500">{count} trades</span>
                    </div>
                    <div className={`text-base font-bold ${total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {total_pnl >= 0 ? '+' : ''}${total_pnl.toFixed(0)}
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5">
                      avg {avg_pnl >= 0 ? '+' : ''}${avg_pnl.toFixed(1)} / trade
                    </div>
                    <div className="text-xs text-gray-600 mt-1 leading-tight">{EXIT_INFO[reason] ?? ''}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Equity curve */}
          {result.result.equity_curve && result.result.equity_curve.length > 1 && (
            <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
              <div className="text-sm font-medium mb-1">Equity Curve</div>
              <div className="text-xs text-gray-500 mb-4">
                Dashed line = starting capital (${parseFloat(capital).toLocaleString()})
              </div>
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={result.result.equity_curve}>
                  <XAxis
                    dataKey="ts"
                    tick={{ fontSize: 10 }}
                    tickFormatter={(v) => dayjs(v).format(isIntraday ? 'MM/DD' : 'YY/MM')}
                  />
                  <YAxis
                    tick={{ fontSize: 10 }}
                    tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                    width={55}
                  />
                  <Tooltip
                    formatter={(v: number) => [`$${v.toLocaleString()}`, 'Equity']}
                    labelFormatter={(l) => dayjs(l).format('MMM D, YYYY')}
                  />
                  <ReferenceLine y={parseFloat(capital)} stroke="#4b5563" strokeDasharray="4 4" />
                  <Line type="monotone" dataKey="value" stroke="#3b82f6" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Trade log */}
          {result.result.trade_log && result.result.trade_log.length > 0 && (
            <div className="bg-gray-900 rounded-xl border border-gray-800">
              <div className="px-4 py-3 border-b border-gray-800 text-sm font-medium">
                Trade Log ({result.result.trade_log.length} trades)
              </div>
              <div className="overflow-x-auto max-h-72 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-gray-900">
                    <tr className="text-gray-500 border-b border-gray-800">
                      <th className="px-3 py-2 text-left">Entry</th>
                      <th className="px-3 py-2 text-left">Exit</th>
                      {hasMultipleTickers && <th className="px-3 py-2 text-left">Ticker</th>}
                      <th className="px-3 py-2 text-left">Side</th>
                      <th className="px-3 py-2 text-right">Entry $</th>
                      <th className="px-3 py-2 text-right">Exit $</th>
                      <th className="px-3 py-2 text-right">Qty</th>
                      <th className="px-3 py-2 text-right">P&amp;L</th>
                      {exitSummary && <th className="px-3 py-2 text-left">Exit Reason</th>}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800">
                    {result.result.trade_log.map((t, i) => (
                      <tr key={i} className="hover:bg-gray-800/40">
                        <td className="px-3 py-1.5 text-gray-400">{dayjs(t.entry_ts).format('MM/DD/YY HH:mm')}</td>
                        <td className="px-3 py-1.5 text-gray-400">{dayjs(t.exit_ts).format('MM/DD/YY HH:mm')}</td>
                        {hasMultipleTickers && <td className="px-3 py-1.5 font-medium">{t.ticker ?? '—'}</td>}
                        <td className={`px-3 py-1.5 ${t.side === 'short' ? 'text-red-400' : 'text-green-400'}`}>
                          {(t.side ?? 'long').toUpperCase()}
                        </td>
                        <td className="px-3 py-1.5 text-right">${t.entry_price.toFixed(2)}</td>
                        <td className="px-3 py-1.5 text-right">${t.exit_price.toFixed(2)}</td>
                        <td className="px-3 py-1.5 text-right">{t.qty}</td>
                        <td className={`px-3 py-1.5 text-right font-medium ${t.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(2)}
                        </td>
                        {exitSummary && (
                          <td className="px-3 py-1.5 text-gray-500 capitalize">{(t.exit_reason ?? '').replace('_', ' ')}</td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Error ── */}
      {result?.status === 'error' && (
        <div className="bg-red-900/30 border border-red-700 rounded-xl p-4 text-red-300 text-sm space-y-1">
          <div className="font-medium">Backtest failed</div>
          <div className="text-xs text-red-400">
            Common causes: invalid ticker symbol, date range with no trading days, or yfinance data unavailable for the selected period.
            {isIntraday && ' For intraday_orb, ensure your date range is within the last 60 days.'}
          </div>
        </div>
      )}
    </div>
  )
}
