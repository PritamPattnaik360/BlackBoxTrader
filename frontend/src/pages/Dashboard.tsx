import { useQuery } from '@tanstack/react-query'
import { getPortfolio } from '../api/portfolio'
import { getSignals } from '../api/signals'
import { getOrders } from '../api/orders'
import { useTradingStore } from '../store/tradingStore'
import { TrendingUp, DollarSign, Activity, Info } from 'lucide-react'
import dayjs from 'dayjs'

function ExplainBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-3 bg-blue-950/30 border border-blue-900/50 rounded-xl px-4 py-3 text-xs text-gray-400 leading-relaxed">
      <Info size={14} className="text-blue-400 flex-shrink-0 mt-0.5" />
      <div>{children}</div>
    </div>
  )
}

function PnLCard({ label, value, pct }: { label: string; value: number; pct?: number }) {
  const positive = value >= 0
  return (
    <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className={`text-2xl font-bold ${positive ? 'text-green-400' : 'text-red-400'}`}>
        {positive ? '+' : ''}${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </div>
      {pct !== undefined && (
        <div className={`text-sm mt-1 ${positive ? 'text-green-500' : 'text-red-500'}`}>
          {positive ? '+' : ''}{(pct * 100).toFixed(2)}%
        </div>
      )}
    </div>
  )
}

export default function Dashboard() {
  const { data: portfolio } = useQuery({ queryKey: ['portfolio'], queryFn: getPortfolio, refetchInterval: 30000 })
  const { data: signals } = useQuery({ queryKey: ['signals'], queryFn: () => getSignals(10), refetchInterval: 60000 })
  const { data: orders } = useQuery({ queryKey: ['orders'], queryFn: () => getOrders(10), refetchInterval: 30000 })
  const prices = useTradingStore((s) => s.prices)

  const acct = (portfolio as any)?.account
  const portfolioError = (portfolio as any)?.error
  const positions = (portfolio as any)?.positions ?? []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold mb-3">Dashboard</h1>
        <ExplainBox>
          Live overview of your paper-trading account. <strong className="text-gray-300">Portfolio Value</strong> and <strong className="text-gray-300">Open Positions</strong> refresh every 30 seconds via Alpaca.
          <strong className="text-gray-300"> Recent Signals</strong> are the latest AI decisions from the scanner (NLP + quant).
          When <strong className="text-gray-300">Autopilot</strong> is on (Settings), signals above ±0.30 automatically place orders — you'll see them appear in Recent Orders within seconds.
        </ExplainBox>
      </div>

      {/* Portfolio error banner */}
      {portfolioError && (
        <div className="bg-red-900/30 border border-red-700 rounded-lg px-4 py-3 text-sm text-red-300">
          <span className="font-semibold">Alpaca connection error: </span>{portfolioError}
        </div>
      )}

      {/* Account cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
          <div className="text-xs text-gray-500 mb-1 flex items-center gap-1"><DollarSign size={12} /> Portfolio Value</div>
          <div className="text-2xl font-bold text-white">${acct ? acct.portfolio_value.toLocaleString('en-US', { maximumFractionDigits: 0 }) : '—'}</div>
        </div>
        <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
          <div className="text-xs text-gray-500 mb-1">Cash</div>
          <div className="text-2xl font-bold text-blue-400">${acct ? acct.cash.toLocaleString('en-US', { maximumFractionDigits: 0 }) : '—'}</div>
        </div>
        <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
          <div className="text-xs text-gray-500 mb-1">Buying Power</div>
          <div className="text-2xl font-bold text-purple-400">${acct ? acct.buying_power.toLocaleString('en-US', { maximumFractionDigits: 0 }) : '—'}</div>
        </div>
        <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
          <div className="text-xs text-gray-500 mb-1 flex items-center gap-1"><Activity size={12} /> Open Positions</div>
          <div className="text-2xl font-bold text-yellow-400">{positions.length}</div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top positions */}
        <div className="bg-gray-900 rounded-xl border border-gray-800">
          <div className="px-4 py-3 border-b border-gray-800 text-sm font-medium flex items-center gap-2">
            <TrendingUp size={14} /> Open Positions
          </div>
          <div className="divide-y divide-gray-800">
            {positions.slice(0, 5).map((p: any) => {
              const live = prices[p.ticker]?.close ?? p.current_price
              const pnl = (live - p.avg_entry_price) * p.qty
              return (
                <div key={p.ticker} className="px-4 py-3 flex items-center justify-between">
                  <div>
                    <div className="font-medium">{p.ticker}</div>
                    <div className="text-xs text-gray-500">{p.qty} shares @ ${p.avg_entry_price.toFixed(2)}</div>
                  </div>
                  <div className="text-right">
                    <div className="font-medium">${live?.toFixed(2) ?? '—'}</div>
                    <div className={`text-xs ${pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
                    </div>
                  </div>
                </div>
              )
            })}
            {positions.length === 0 && <div className="px-4 py-6 text-center text-gray-500 text-sm">No open positions</div>}
          </div>
        </div>

        {/* Signal feed */}
        <div className="bg-gray-900 rounded-xl border border-gray-800">
          <div className="px-4 py-3 border-b border-gray-800 text-sm font-medium flex items-center gap-2">
            <Activity size={14} /> Recent Signals
          </div>
          <div className="divide-y divide-gray-800">
            {(signals ?? []).map((s) => (
              <div key={s.id} className="px-4 py-3 flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{s.ticker}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      s.direction === 'BUY' ? 'bg-green-900 text-green-300' :
                      s.direction === 'SELL' ? 'bg-red-900 text-red-300' :
                      'bg-gray-800 text-gray-400'
                    }`}>{s.direction}</span>
                  </div>
                  <div className="text-xs text-gray-500 mt-0.5">{dayjs(s.created_at).format('HH:mm:ss')}</div>
                </div>
                <div className={`text-sm font-mono ${s.composite_score >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {s.composite_score >= 0 ? '+' : ''}{s.composite_score.toFixed(3)}
                </div>
              </div>
            ))}
            {(!signals || signals.length === 0) && <div className="px-4 py-6 text-center text-gray-500 text-sm">No signals yet</div>}
          </div>
        </div>
      </div>

      {/* Recent orders */}
      <div className="bg-gray-900 rounded-xl border border-gray-800">
        <div className="px-4 py-3 border-b border-gray-800 text-sm font-medium">Recent Orders</div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 border-b border-gray-800">
                <th className="px-4 py-2 text-left">Ticker</th>
                <th className="px-4 py-2 text-left">Side</th>
                <th className="px-4 py-2 text-left">Qty</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-left">Fill Price</th>
                <th className="px-4 py-2 text-left">Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {(orders ?? []).map((o) => (
                <tr key={o.id}>
                  <td className="px-4 py-2 font-medium">{o.ticker}</td>
                  <td className={`px-4 py-2 ${o.side === 'buy' ? 'text-green-400' : 'text-red-400'}`}>{o.side.toUpperCase()}</td>
                  <td className="px-4 py-2">{o.qty}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs ${
                      o.status === 'filled' ? 'bg-green-900 text-green-300' :
                      o.status === 'cancelled' ? 'bg-gray-800 text-gray-400' :
                      'bg-yellow-900 text-yellow-300'
                    }`}>{o.status}</span>
                  </td>
                  <td className="px-4 py-2">{o.filled_avg_price ? `$${o.filled_avg_price.toFixed(2)}` : '—'}</td>
                  <td className="px-4 py-2 text-gray-400">{dayjs(o.submitted_at).format('HH:mm:ss')}</td>
                </tr>
              ))}
              {(!orders || orders.length === 0) && (
                <tr><td colSpan={6} className="px-4 py-6 text-center text-gray-500">No orders yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
