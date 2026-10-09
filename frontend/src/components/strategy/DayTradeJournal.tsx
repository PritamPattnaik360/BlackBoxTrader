import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import dayjs from 'dayjs'
import { Zap } from 'lucide-react'

interface DayTradeRow {
  id: number; ticker: string; status: 'open' | 'closed'; qty: number
  entry_price: number; stop_price: number | null; target_price: number | null
  entry_time: string | null; exit_price: number | null; exit_time: string | null
  pnl: number | null; pnl_pct: number | null; exit_reason: string | null
  held_minutes: number | null; bias: string | null
}
interface DayTradeResponse {
  today: { trades: number; open: number; closed: number; wins: number; win_rate: number | null; pnl: number }
  trades: DayTradeRow[]
}

const getDayTrades = () =>
  axios.get<DayTradeResponse>('/api/v1/strategy/day-trades').then((r) => r.data)

const REASON_STYLE: Record<string, string> = {
  take_profit: 'bg-green-900 text-green-300',
  stop: 'bg-red-900 text-red-300',
  eod: 'bg-blue-900 text-blue-300',
  signal: 'bg-gray-800 text-gray-300',
}

export default function DayTradeJournal() {
  const { data } = useQuery({ queryKey: ['dayTrades'], queryFn: getDayTrades, refetchInterval: 30_000 })
  const t = data?.today
  const pnlClass = (v: number) => (v >= 0 ? 'text-green-400' : 'text-red-400')

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800">
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <div className="text-sm font-medium flex items-center gap-2">
          <Zap size={14} className="text-yellow-400" /> Day-Trade Journal
          <span className="text-xs text-gray-500 font-normal">same-day round trips · never held overnight</span>
        </div>
        {t && (
          <div className="text-xs text-gray-400 flex gap-4">
            <span>Today: {t.trades} trades ({t.open} open)</span>
            <span>Win rate: {t.win_rate != null ? `${(t.win_rate * 100).toFixed(0)}%` : '—'}</span>
            <span className={pnlClass(t.pnl)}>P&amp;L: {t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(2)}</span>
          </div>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-gray-500 border-b border-gray-800">
              <th className="px-4 py-2 text-left">Ticker</th>
              <th className="px-4 py-2 text-left">Entry</th>
              <th className="px-4 py-2 text-left">Exit</th>
              <th className="px-4 py-2 text-left">Qty</th>
              <th className="px-4 py-2 text-left">P&amp;L</th>
              <th className="px-4 py-2 text-left">Held</th>
              <th className="px-4 py-2 text-left">Closed by</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {(data?.trades ?? []).map((d) => (
              <tr key={d.id}>
                <td className="px-4 py-2 font-medium">{d.ticker}</td>
                <td className="px-4 py-2">
                  ${d.entry_price.toFixed(2)}
                  <div className="text-xs text-gray-500">{d.entry_time ? dayjs(d.entry_time).format('MMM D HH:mm') : ''}</div>
                </td>
                <td className="px-4 py-2">
                  {d.status === 'open' ? (
                    <span className="text-xs px-2 py-0.5 rounded bg-yellow-900 text-yellow-300">OPEN</span>
                  ) : (
                    <>
                      ${d.exit_price?.toFixed(2)}
                      <div className="text-xs text-gray-500">{d.exit_time ? dayjs(d.exit_time).format('HH:mm') : ''}</div>
                    </>
                  )}
                </td>
                <td className="px-4 py-2">{d.qty}</td>
                <td className={`px-4 py-2 font-medium ${d.pnl != null ? pnlClass(d.pnl) : 'text-gray-500'}`}>
                  {d.pnl != null ? `${d.pnl >= 0 ? '+' : ''}$${d.pnl.toFixed(2)} (${((d.pnl_pct ?? 0) * 100).toFixed(2)}%)` : '—'}
                </td>
                <td className="px-4 py-2 text-gray-400">{d.held_minutes != null ? `${d.held_minutes}m` : '—'}</td>
                <td className="px-4 py-2">
                  {d.exit_reason && (
                    <span className={`text-xs px-2 py-0.5 rounded ${REASON_STYLE[d.exit_reason] ?? 'bg-gray-800 text-gray-300'}`}>
                      {d.exit_reason.replace('_', ' ')}
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {(!data || data.trades.length === 0) && (
              <tr><td colSpan={7} className="px-4 py-6 text-center text-gray-500">
                No day trades yet — they're logged here when autopilot opens one during market hours
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
