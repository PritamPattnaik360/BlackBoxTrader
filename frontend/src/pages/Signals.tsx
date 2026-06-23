import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getSignals, triggerScan } from '../api/signals'
import dayjs from 'dayjs'
import { RefreshCw } from 'lucide-react'

export default function Signals() {
  const qc = useQueryClient()
  const { data: signals, isLoading } = useQuery({ queryKey: ['signals', 50], queryFn: () => getSignals(50), refetchInterval: 60000 })
  const scan = useMutation({ mutationFn: triggerScan, onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ['signals'] }), 5000) })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">NLP Signals</h1>
        <button
          onClick={() => scan.mutate()}
          disabled={scan.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-sm rounded-lg disabled:opacity-50"
        >
          <RefreshCw size={14} className={scan.isPending ? 'animate-spin' : ''} />
          Scan Now
        </button>
      </div>

      <div className="bg-gray-900 rounded-xl border border-gray-800">
        {isLoading && <div className="p-8 text-center text-gray-500">Loading signals...</div>}
        <div className="divide-y divide-gray-800">
          {(signals ?? []).map((s) => (
            <div key={s.id} className="px-4 py-4">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-3">
                  <span className="text-lg font-bold">{s.ticker}</span>
                  <span className={`px-3 py-1 rounded-full text-xs font-bold ${
                    s.direction === 'BUY' ? 'bg-green-900/60 text-green-300 border border-green-700' :
                    s.direction === 'SELL' ? 'bg-red-900/60 text-red-300 border border-red-700' :
                    'bg-gray-800 text-gray-400'
                  }`}>{s.direction}</span>
                </div>
                <div className="flex items-center gap-4 text-right">
                  <div>
                    <div className={`text-xl font-bold font-mono ${s.composite_score >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {s.composite_score >= 0 ? '+' : ''}{s.composite_score.toFixed(3)}
                    </div>
                    <div className="text-xs text-gray-500">composite score</div>
                  </div>
                  <div>
                    <div className="text-sm text-white">{(s.confidence * 100).toFixed(0)}%</div>
                    <div className="text-xs text-gray-500">confidence</div>
                  </div>
                </div>
              </div>

              {/* Quant component breakdown */}
              {s.raw_headlines && (s.raw_headlines as any)?._quant && (
                <div className="grid grid-cols-5 gap-2 my-2">
                  {[
                    { label: 'NLP', key: 'nlp' },
                    { label: 'Momentum', key: 'momentum' },
                    { label: 'Mean Rev', key: 'mean_reversion' },
                    { label: 'Technical', key: 'technical' },
                    { label: 'LLM', key: 'llm' },
                  ].map(({ label, key }) => {
                    const quant = (s.raw_headlines as any)._quant
                    const val: number | undefined = quant?.[key]
                    const active = key !== 'llm' || quant?.llm_active
                    return (
                      <div key={key} className={`text-center rounded p-1.5 ${active ? 'bg-gray-800' : 'bg-gray-800/40'}`}>
                        <div className={`text-xs font-mono ${val == null || !active ? 'text-gray-600' : val >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {val != null && active ? `${val >= 0 ? '+' : ''}${val.toFixed(3)}` : '—'}
                        </div>
                        <div className={`text-xs mt-0.5 ${active ? 'text-gray-500' : 'text-gray-700'}`}>{label}</div>
                      </div>
                    )
                  })}
                </div>
              )}

              <div className="flex gap-4 text-xs text-gray-400 mb-2">
                <span>News: <span className={s.news_score != null ? (s.news_score >= 0 ? 'text-green-400' : 'text-red-400') : 'text-gray-500'}>{s.news_score != null ? s.news_score.toFixed(3) : 'n/a'}</span></span>
                <span>{s.source_count} sources</span>
                <span className="ml-auto">{dayjs(s.created_at).format('MMM D HH:mm:ss')}</span>
              </div>

              {s.raw_headlines && s.raw_headlines.length > 0 && (
                <div className="space-y-1 mt-2">
                  {s.raw_headlines.slice(0, 3).map((h, i) => (
                    <div key={i} className="text-xs text-gray-400 flex items-start gap-2">
                      <span className={`mt-0.5 w-2 h-2 rounded-full flex-shrink-0 ${h.score === 'positive' ? 'bg-green-400' : h.score === 'negative' ? 'bg-red-400' : 'bg-gray-500'}`} />
                      <span className="truncate">{h.title}</span>
                      <span className="text-gray-600 flex-shrink-0">{h.source}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
          {(!signals || signals.length === 0) && !isLoading && (
            <div className="px-4 py-12 text-center text-gray-500">
              No signals yet. Add tickers to your watchlist and click "Scan Now".
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
