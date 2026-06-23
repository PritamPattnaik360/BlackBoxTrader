import { useState, useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { submitBacktest, getBacktestResult } from '../api/backtest'
import type { BacktestRun } from '../types'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import dayjs from 'dayjs'
import { FlaskConical } from 'lucide-react'

function MetricCard({ label, value, format = 'pct' }: { label: string; value: number | null; format?: 'pct' | 'num' | 'dollar' }) {
  if (value == null) return <div className="bg-gray-800 rounded-lg p-3"><div className="text-xs text-gray-500">{label}</div><div className="text-lg font-bold text-gray-600">—</div></div>
  const formatted = format === 'pct' ? `${(value * 100).toFixed(2)}%` : format === 'dollar' ? `$${value.toLocaleString()}` : value.toFixed(4)
  const positive = value >= 0
  return (
    <div className="bg-gray-800 rounded-lg p-3">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className={`text-lg font-bold ${positive ? 'text-green-400' : 'text-red-400'}`}>{formatted}</div>
    </div>
  )
}

export default function Backtest() {
  const [tickers, setTickers] = useState('AAPL,MSFT')
  const [startDate, setStartDate] = useState('2020-01-01')
  const [endDate, setEndDate] = useState('2024-12-31')
  const [capital, setCapital] = useState('100000')
  const [strategy, setStrategy] = useState('nlp_proxy')
  const [runId, setRunId] = useState<number | null>(null)
  const [result, setResult] = useState<BacktestRun | null>(null)
  const [polling, setPolling] = useState(false)

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
    submit.mutate({
      tickers: tickers.split(',').map((t) => t.trim().toUpperCase()),
      start_date: startDate,
      end_date: endDate,
      initial_capital: parseFloat(capital),
      strategy_name: strategy,
    })
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Backtest</h1>

      <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
        <form onSubmit={handleSubmit} className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="col-span-2 lg:col-span-1">
            <label className="text-xs text-gray-500 block mb-1">Tickers (comma-separated)</label>
            <input className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500" value={tickers} onChange={(e) => setTickers(e.target.value)} placeholder="AAPL,MSFT" />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Start Date</label>
            <input type="date" className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">End Date</label>
            <input type="date" className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Initial Capital ($)</label>
            <input type="number" className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500" value={capital} onChange={(e) => setCapital(e.target.value)} />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Strategy</label>
            <select className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500" value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              <option value="nlp_proxy">NLP Proxy (RSI+MACD)</option>
              <option value="sma_crossover">SMA Crossover</option>
            </select>
          </div>
          <div className="flex items-end">
            <button type="submit" disabled={submit.isPending || polling} className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium disabled:opacity-50">
              <FlaskConical size={14} />
              {polling ? 'Running...' : 'Run Backtest'}
            </button>
          </div>
        </form>
      </div>

      {polling && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-8 text-center text-gray-400">
          <div className="animate-spin w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-3" />
          Running backtest...
        </div>
      )}

      {result?.result && (
        <div className="space-y-4">
          {/* Metrics grid */}
          <div className="grid grid-cols-4 lg:grid-cols-8 gap-3">
            <MetricCard label="Total Return" value={result.result.total_return} format="pct" />
            <MetricCard label="CAGR" value={result.result.cagr} format="pct" />
            <MetricCard label="Sharpe" value={result.result.sharpe} format="num" />
            <MetricCard label="Sortino" value={result.result.sortino} format="num" />
            <MetricCard label="Max Drawdown" value={result.result.max_drawdown} format="pct" />
            <MetricCard label="Calmar" value={result.result.calmar} format="num" />
            <MetricCard label="Win Rate" value={result.result.win_rate} format="pct" />
            <div className="bg-gray-800 rounded-lg p-3">
              <div className="text-xs text-gray-500 mb-1">Total Trades</div>
              <div className="text-lg font-bold text-white">{result.result.total_trades ?? '—'}</div>
            </div>
          </div>

          {/* Equity curve */}
          {result.result.equity_curve && result.result.equity_curve.length > 1 && (
            <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
              <div className="text-sm font-medium mb-4">Equity Curve</div>
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={result.result.equity_curve}>
                  <XAxis dataKey="ts" tick={{ fontSize: 10 }} tickFormatter={(v) => dayjs(v).format('YY/MM')} />
                  <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `$${(v/1000).toFixed(0)}k`} />
                  <Tooltip formatter={(v: number) => [`$${v.toLocaleString()}`, 'Equity']} />
                  <ReferenceLine y={parseFloat(capital)} stroke="#4b5563" strokeDasharray="4 4" />
                  <Line type="monotone" dataKey="value" stroke="#3b82f6" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Trade log */}
          {result.result.trade_log && result.result.trade_log.length > 0 && (
            <div className="bg-gray-900 rounded-xl border border-gray-800">
              <div className="px-4 py-3 border-b border-gray-800 text-sm font-medium">Trade Log ({result.result.trade_log.length} trades)</div>
              <div className="overflow-x-auto max-h-64 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-gray-900">
                    <tr className="text-gray-500 border-b border-gray-800">
                      <th className="px-4 py-2 text-left">Entry</th>
                      <th className="px-4 py-2 text-left">Exit</th>
                      <th className="px-4 py-2 text-right">Entry $</th>
                      <th className="px-4 py-2 text-right">Exit $</th>
                      <th className="px-4 py-2 text-right">Qty</th>
                      <th className="px-4 py-2 text-right">P&L</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800">
                    {result.result.trade_log.map((t, i) => (
                      <tr key={i} className="hover:bg-gray-800/40">
                        <td className="px-4 py-1.5 text-gray-400">{dayjs(t.entry_ts).format('MM/DD/YY')}</td>
                        <td className="px-4 py-1.5 text-gray-400">{dayjs(t.exit_ts).format('MM/DD/YY')}</td>
                        <td className="px-4 py-1.5 text-right">${t.entry_price.toFixed(2)}</td>
                        <td className="px-4 py-1.5 text-right">${t.exit_price.toFixed(2)}</td>
                        <td className="px-4 py-1.5 text-right">{t.qty}</td>
                        <td className={`px-4 py-1.5 text-right font-medium ${t.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {result?.status === 'error' && (
        <div className="bg-red-900/30 border border-red-700 rounded-xl p-4 text-red-300 text-sm">
          Backtest failed. Check your tickers and date range.
        </div>
      )}
    </div>
  )
}
