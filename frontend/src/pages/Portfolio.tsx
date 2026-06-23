import { useQuery } from '@tanstack/react-query'
import { getPortfolio, getPortfolioHistory } from '../api/portfolio'
import { useTradingStore } from '../store/tradingStore'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import dayjs from 'dayjs'

export default function Portfolio() {
  const { data: portfolio } = useQuery({ queryKey: ['portfolio'], queryFn: getPortfolio, refetchInterval: 30000 })
  const { data: history } = useQuery({ queryKey: ['portfolioHistory'], queryFn: getPortfolioHistory, refetchInterval: 60000 })
  const prices = useTradingStore((s) => s.prices)

  const positions = portfolio?.positions ?? []
  const acct = portfolio?.account

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Portfolio</h1>

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
