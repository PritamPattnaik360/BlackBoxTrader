import { useQuery } from '@tanstack/react-query'
import { getPortfolio, getPortfolioHistory } from '../api/portfolio'
import { useTradingStore } from '../store/tradingStore'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import dayjs from 'dayjs'
import { Info } from 'lucide-react'

function ExplainBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-3 bg-blue-950/30 border border-blue-900/50 rounded-xl px-4 py-3 text-xs text-gray-400 leading-relaxed">
      <Info size={14} className="text-blue-400 flex-shrink-0 mt-0.5" />
      <div>{children}</div>
    </div>
  )
}

export default function Portfolio() {
  const { data: portfolio, isLoading, isError } = useQuery({ queryKey: ['portfolio'], queryFn: getPortfolio, refetchInterval: 30000 })
  const { data: history } = useQuery({ queryKey: ['portfolioHistory'], queryFn: getPortfolioHistory, refetchInterval: 60000 })
  const prices = useTradingStore((s) => s.prices)

  const positions = (portfolio as any)?.positions ?? []
  const acct = (portfolio as any)?.account
  const portfolioError = (portfolio as any)?.error

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold mb-3">Portfolio</h1>
        <ExplainBox>
          Your Alpaca paper-trading account snapshot. The <strong className="text-gray-300">Equity Curve</strong> shows how your total account value has changed over time — pulled directly from Alpaca's portfolio history endpoint.
          <strong className="text-gray-300"> Live Price</strong> in the positions table is updated in real time via WebSocket; <strong className="text-gray-300">Unrealized P&L</strong> recalculates every tick.
          Positions are sized by the risk engine: 1% of equity risked per trade, divided by 2× ATR.
        </ExplainBox>
      </div>

      {/* Alpaca connection error */}
      {(isError || portfolioError) && (
        <div className="bg-red-900/30 border border-red-700 rounded-lg px-4 py-3 text-sm text-red-300 space-y-1">
          <div className="font-semibold">Alpaca connection error — no positions can be loaded</div>
          {portfolioError && <div className="text-xs opacity-80">{portfolioError}</div>}
          <div className="text-xs text-red-400 mt-1">
            Check that <code className="bg-red-900/50 px-1 rounded">ALPACA_API_KEY</code> and{' '}
            <code className="bg-red-900/50 px-1 rounded">ALPACA_SECRET_KEY</code> are set in{' '}
            <code className="bg-red-900/50 px-1 rounded">backend/.env</code>, then restart the backend.
          </div>
        </div>
      )}

      {/* Autonomous mode reminder when no positions and no error */}
      {!isLoading && !portfolioError && !isError && positions.length === 0 && (
        <div className="bg-yellow-900/20 border border-yellow-700/50 rounded-lg px-4 py-3 text-sm text-yellow-300">
          <div className="font-semibold mb-1">No open positions</div>
          <div className="text-xs text-yellow-400">
            Alpaca is connected but your paper account has no positions yet. Make sure{' '}
            <strong>Auto Pilot is ON</strong> in Settings and market hours are active (Mon–Fri 9:30–16:00 ET).
            The system will place its first trade on the next scan cycle.
          </div>
        </div>
      )}

      {/* Equity curve */}
      {history && history.length > 1 && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
          <div className="text-sm font-medium mb-4">Equity Curve</div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={history}>
              <XAxis dataKey="ts" tick={{ fontSize: 10 }} tickFormatter={(v) => dayjs(v).format('MM/DD')} />
              <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `$${(v/1000).toFixed(0)}k`} />
              <Tooltip formatter={(v: number) => [`$${v.toLocaleString()}`, 'Equity']} labelFormatter={(l) => dayjs(l).format('MMM DD')} />
              <Line type="monotone" dataKey="equity" stroke="#3b82f6" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Account summary */}
      {acct && (
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: 'Total Equity', value: acct.equity },
            { label: 'Cash', value: acct.cash },
            { label: 'Buying Power', value: acct.buying_power },
          ].map(({ label, value }) => (
            <div key={label} className="bg-gray-900 rounded-xl p-4 border border-gray-800">
              <div className="text-xs text-gray-500">{label}</div>
              <div className="text-xl font-bold mt-1">${value.toLocaleString('en-US', { maximumFractionDigits: 2 })}</div>
            </div>
          ))}
        </div>
      )}

      {/* Positions table */}
      <div className="bg-gray-900 rounded-xl border border-gray-800">
        <div className="px-4 py-3 border-b border-gray-800 text-sm font-medium">
          Open Positions ({positions.length})
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 border-b border-gray-800">
                <th className="px-4 py-2 text-left">Ticker</th>
                <th className="px-4 py-2 text-right">Qty</th>
                <th className="px-4 py-2 text-right">Avg Cost</th>
                <th className="px-4 py-2 text-right">Live Price</th>
                <th className="px-4 py-2 text-right">Market Value</th>
                <th className="px-4 py-2 text-right">Unrealized P&L</th>
                <th className="px-4 py-2 text-right">P&L %</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {positions.map((p) => {
                const live = prices[p.ticker]?.close ?? p.current_price
                const pnl = (live - p.avg_entry_price) * p.qty
                const pnlPct = ((live - p.avg_entry_price) / p.avg_entry_price) * 100
                return (
                  <tr key={p.ticker} className="hover:bg-gray-800/50">
                    <td className="px-4 py-3 font-medium">{p.ticker}</td>
                    <td className="px-4 py-3 text-right">{p.qty}</td>
                    <td className="px-4 py-3 text-right">${p.avg_entry_price.toFixed(2)}</td>
                    <td className="px-4 py-3 text-right font-mono">${live?.toFixed(2) ?? '—'}</td>
                    <td className="px-4 py-3 text-right">${(live * p.qty).toLocaleString('en-US', { maximumFractionDigits: 0 })}</td>
                    <td className={`px-4 py-3 text-right font-medium ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
                    </td>
                    <td className={`px-4 py-3 text-right ${pnlPct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
                    </td>
                  </tr>
                )
              })}
              {positions.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-500">No open positions</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
