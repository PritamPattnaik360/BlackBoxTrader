import { useQuery } from '@tanstack/react-query'
import { Brain } from 'lucide-react'
import { getPatterns, type PatternBucket } from '../../api/dayTrading'

const DIM_LABEL: Record<string, string> = {
  hour: 'Entry hour (ET)', score: 'Signal score', bias: 'Market bias', side: 'Side',
  ticker: 'Ticker', rvol: 'Relative volume', vix: 'VIX at entry',
}
const money = (v: number) => `${v < 0 ? '-' : '+'}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`

function Row({ b }: { b: PatternBucket }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5 text-sm">
      <div className="flex items-center gap-2 min-w-0">
        <span className="font-mono text-gray-200">{b.bucket}</span>
        {b.avoid && <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/60 text-red-300">avoid</span>}
      </div>
      <div className="flex items-center gap-4 text-xs flex-shrink-0">
        <span className="text-gray-500">{b.n} trades</span>
        <span className="text-gray-400 w-12 text-right">{(b.win_rate * 100).toFixed(0)}% win</span>
        <span className={`w-16 text-right font-mono ${b.net >= 0 ? 'text-green-400' : 'text-red-400'}`}>{money(b.net)}</span>
      </div>
    </div>
  )
}

export default function PatternsPanel() {
  const { data } = useQuery({ queryKey: ['dayPatterns'], queryFn: getPatterns, refetchInterval: 120_000 })
  if (!data) return null
  const dims = Object.keys(DIM_LABEL).filter((d) => data.buckets.some((b) => b.dim === d))

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
      <div className="text-sm font-medium mb-1 flex items-center gap-2"><Brain size={15} className="text-purple-400" /> What the bot is learning from its trades</div>
      <div className="text-xs text-gray-500 mb-3">
        {data.n} closed trades, {data.with_features} with a full entry snapshot (relative volume, VIX and signal scores are recorded from now on).
        A group appears once it has {data.min_bucket}+ trades. It is only marked <em>avoid</em> if it lost in both the older 70% of trades and the latest 30%.
      </div>
      {data.blocked_hours.length > 0 ? (
        <div className="text-xs bg-red-900/20 border border-red-800 text-red-300 rounded px-3 py-2 mb-3">
          Currently skipping new entries during: {data.blocked_hours.map((h) => `${String(h).padStart(2, '0')}:00`).join(', ')} ET (re-checked every night).
        </div>
      ) : (
        <div className="text-xs text-gray-500 mb-3">No time windows are blocked — nothing has lost consistently enough yet.</div>
      )}
      {dims.length === 0 ? (
        <div className="text-xs text-gray-600">Not enough trades yet to show any pattern.</div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-8 gap-y-4">
          {dims.map((d) => (
            <div key={d}>
              <div className="text-[11px] uppercase tracking-wide text-gray-500 mb-1">{DIM_LABEL[d]}</div>
              <div className="divide-y divide-gray-800">
                {data.buckets.filter((b) => b.dim === d).map((b) => <Row key={d + b.bucket} b={b} />)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
