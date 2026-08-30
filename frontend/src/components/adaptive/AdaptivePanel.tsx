import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getAdaptiveParams, getAdaptivePerf, getAdaptiveEvents, getAdaptiveHistory,
  triggerOptimize, resetAdaptiveParams,
} from '../../api/adaptive'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import { Brain, RefreshCw, RotateCcw, TrendingUp, TrendingDown, Activity } from 'lucide-react'

const REGIME_COLORS: Record<string, string> = {
  normal:                'bg-gray-700 text-gray-200',
  high_volatility:       'bg-red-900 text-red-300',
  low_volatility:        'bg-blue-900 text-blue-300',
  trending_up:           'bg-green-900 text-green-300',
  trending_down:         'bg-orange-900 text-orange-300',
  volatile_trending_up:  'bg-emerald-900 text-emerald-300',
  volatile_trending_down: 'bg-rose-900 text-rose-300',
}

const PARAM_LABELS: Record<string, string> = {
  buy_signal_threshold:  'BUY threshold',
  sell_signal_threshold: 'SELL threshold',
  risk_per_trade_pct:    'Risk / trade',
  atr_stop_multiplier:   'ATR stop ×',
}

function pct(v: number | null | undefined) {
  if (v == null) return '—'
  return (v * 100).toFixed(1) + '%'
}

function fmt(name: string, v: number) {
  if (name.includes('pct')) return pct(v)
  if (name.includes('weight') || name.includes('threshold')) return v.toFixed(3)
  return v.toFixed(2)
}

function deltaClass(d: number) {
  if (Math.abs(d) < 0.0001) return 'text-gray-500'
  return d > 0 ? 'text-green-400' : 'text-red-400'
}

export default function AdaptivePanel() {
  const qc = useQueryClient()

  const { data: paramsData } = useQuery({ queryKey: ['adaptiveParams'], queryFn: getAdaptiveParams, refetchInterval: 30_000 })
  const { data: perf }       = useQuery({ queryKey: ['adaptivePerf'],   queryFn: getAdaptivePerf,   refetchInterval: 30_000 })
  const { data: events }     = useQuery({ queryKey: ['adaptiveEvents'],  queryFn: getAdaptiveEvents, refetchInterval: 30_000 })
  const { data: history }    = useQuery({ queryKey: ['adaptiveHistory'], queryFn: getAdaptiveHistory })

  const optimize = useMutation({
    mutationFn: triggerOptimize,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['adaptiveParams'] })
      qc.invalidateQueries({ queryKey: ['adaptivePerf'] })
      qc.invalidateQueries({ queryKey: ['adaptiveEvents'] })
      qc.invalidateQueries({ queryKey: ['adaptiveHistory'] })
    },
  })

  const reset = useMutation({
    mutationFn: resetAdaptiveParams,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['adaptiveParams'] }),
  })

  const regime = paramsData?.regime ?? 'normal'
  const gen    = paramsData?.generation ?? 0

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain size={16} className="text-purple-400" />
          <span className="text-sm font-medium">Strategy Learning</span>
          <span className={`text-xs px-2 py-0.5 rounded-full ${REGIME_COLORS[regime] ?? REGIME_COLORS.normal}`}>
            {regime.replace('_', ' ')}
          </span>
          {gen > 0 && <span className="text-xs text-gray-500">gen {gen}</span>}
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => optimize.mutate()}
            disabled={optimize.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-purple-700 hover:bg-purple-600 rounded text-xs disabled:opacity-50"
          >
            <RefreshCw size={12} className={optimize.isPending ? 'animate-spin' : ''} />
            Optimize now
          </button>
          <button
            onClick={() => reset.mutate()}
            disabled={reset.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-xs disabled:opacity-50"
          >
            <RotateCcw size={12} />
            Reset
          </button>
        </div>
      </div>

      {/* Performance stats */}
      {perf && perf.total_outcomes > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {[
            { label: 'Win rate', value: pct(perf.win_rate) },
            { label: 'BUY acc',  value: pct(perf.buy_accuracy) },
            { label: 'SELL acc', value: pct(perf.sell_accuracy) },
            { label: 'Sharpe',   value: perf.recent_sharpe?.toFixed(2) ?? '—' },
            { label: 'Avg P&L',  value: pct(perf.avg_pnl_pct) },
          ].map(s => (
            <div key={s.label} className="bg-gray-800 rounded-lg p-2.5 text-center">
              <div className="text-xs text-gray-400">{s.label}</div>
              <div className="text-sm font-semibold mt-0.5">{s.value}</div>
            </div>
          ))}
        </div>
      )}

      {perf && perf.total_outcomes === 0 && (
        <div className="text-xs text-gray-500 bg-gray-800 rounded-lg p-3">
          <Activity size={12} className="inline mr-1.5" />
          No trade outcomes yet. The system will start learning once positions close.
        </div>
      )}

      {/* Current params vs defaults */}
      <div className="bg-gray-800 rounded-lg overflow-hidden">
        <div className="grid grid-cols-4 text-xs text-gray-500 px-3 py-2 border-b border-gray-700">
          <span>Parameter</span><span className="text-right">Default</span>
          <span className="text-right">Current</span><span className="text-right">Change</span>
        </div>
        {(paramsData?.params ?? []).map(p => (
          <div key={p.name} className="grid grid-cols-4 text-xs px-3 py-2 border-b border-gray-700/50 last:border-0">
            <span className="text-gray-300">{PARAM_LABELS[p.name] ?? p.name}</span>
            <span className="text-right text-gray-500">{fmt(p.name, p.default)}</span>
            <span className="text-right font-medium">{fmt(p.name, p.current)}</span>
            <span className={`text-right ${deltaClass(p.delta)}`}>
              {p.delta > 0 ? '+' : ''}{fmt(p.name, p.delta)}
            </span>
          </div>
        ))}
      </div>

      {/* Evolution chart */}
      {history && history.length > 1 && (
        <div>
          <div className="text-xs text-gray-500 mb-2">Parameter evolution by generation</div>
          <ResponsiveContainer width="100%" height={140}>
            <LineChart data={history} margin={{ top: 4, right: 4, bottom: 4, left: -20 }}>
              <XAxis dataKey="generation" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip
                contentStyle={{ background: '#1f2937', border: '1px solid #374151', fontSize: 11 }}
                formatter={(v: number) => v.toFixed(4)}
              />
              <Legend iconSize={8} wrapperStyle={{ fontSize: 10 }} />
              <Line type="monotone" dataKey="buy_signal_threshold"  stroke="#22c55e" dot={false} name="BUY thr" strokeWidth={1.5} />
              <Line type="monotone" dataKey="news_weight"           stroke="#a78bfa" dot={false} name="News wt" strokeWidth={1.5} />
              <Line type="monotone" dataKey="risk_per_trade_pct"    stroke="#f59e0b" dot={false} name="Risk"    strokeWidth={1.5} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Events log */}
      {events && events.length > 0 && (
        <div>
          <div className="text-xs text-gray-500 mb-2">Adaptation log</div>
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {events.map(ev => (
              <div key={ev.id} className="flex gap-2 text-xs bg-gray-800 rounded px-3 py-2">
                <span className="text-gray-500 shrink-0">
                  {ev.created_at ? new Date(ev.created_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
                </span>
                <span className={
                  ev.event_type === 'reset'            ? 'text-gray-400' :
                  ev.event_type === 'risk_reduced'     ? 'text-red-400' :
                  ev.event_type === 'risk_increased'   ? 'text-green-400' :
                  ev.event_type === 'regime_change'    ? 'text-yellow-400' :
                  ev.event_type === 'threshold_raised' ? 'text-orange-400' :
                  ev.event_type === 'weight_adjusted'  ? 'text-blue-400' :
                  'text-gray-300'
                }>
                  {ev.description}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
