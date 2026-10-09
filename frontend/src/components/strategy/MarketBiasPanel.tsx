import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getStrategyContext, refreshStrategy } from '../../api/strategy'
import { TrendingUp, TrendingDown, Minus, RefreshCw, Zap } from 'lucide-react'

const BIAS_STYLE = {
  bull:    { chip: 'bg-green-900 text-green-300',  Icon: TrendingUp,   text: 'text-green-400' },
  neutral: { chip: 'bg-gray-700 text-gray-200',    Icon: Minus,        text: 'text-gray-300' },
  bear:    { chip: 'bg-red-900 text-red-300',      Icon: TrendingDown, text: 'text-red-400' },
} as const

const WEIGHT_LABELS: Record<string, string> = {
  intraday: 'Intraday', nlp: 'News', momentum: 'Momentum', mean_reversion: 'Mean-rev',
  technical: 'Technical', trendlines: 'Trend lines',
}

function WeightBars({ title, weights }: { title: string; weights: Record<string, number> }) {
  const rows = Object.entries(weights).sort((a, b) => b[1] - a[1])
  return (
    <div>
      <div className="text-xs text-gray-500 mb-1.5">{title}</div>
      <div className="space-y-1">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-center gap-2 text-xs">
            <span className="w-20 text-gray-400">{WEIGHT_LABELS[k] ?? k}</span>
            <div className="flex-1 h-1.5 bg-gray-800 rounded">
              <div className="h-1.5 bg-blue-500 rounded" style={{ width: `${v * 100 / 0.4 > 100 ? 100 : v * 100 / 0.4}%` }} />
            </div>
            <span className="w-8 text-right text-gray-400">{(v * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function MarketBiasPanel() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['strategyContext'], queryFn: getStrategyContext, refetchInterval: 60_000 })
  const refresh = useMutation({
    mutationFn: refreshStrategy,
    onSuccess: (d) => qc.setQueryData(['strategyContext'], d),
  })

  if (!data) return null
  const { context: c, profile: p, universe: u } = data
  const style = BIAS_STYLE[c.bias]
  const pctFmt = (v: number | null | undefined) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`)

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800">
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className={`flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full ${style.chip}`}>
            <style.Icon size={13} /> {c.bias.toUpperCase()} MARKET
          </span>
          <span className="text-sm font-medium">{p.label}</span>
        </div>
        <button
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
          className="text-xs text-gray-400 hover:text-white flex items-center gap-1 disabled:opacity-50"
          title="Recompute market bias and re-screen the S&P 500 + growth universe (≈30s)"
        >
          <RefreshCw size={12} className={refresh.isPending ? 'animate-spin' : ''} />
          {refresh.isPending ? 'Screening…' : 'Refresh'}
        </button>
      </div>

      <div className="p-4 space-y-4">
        <p className="text-xs text-gray-400 leading-relaxed">{p.description}</p>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
          <div><div className="text-gray-500">S&amp;P 500 (SPY)</div><div className={`text-base font-semibold ${style.text}`}>{c.spy_price ? `$${c.spy_price}` : '—'}</div></div>
          <div><div className="text-gray-500">vs 200-day</div><div className="text-base font-semibold">{pctFmt(c.spy_vs_200dma_pct)}</div></div>
          <div><div className="text-gray-500">VIX</div><div className="text-base font-semibold">{c.vix ?? '—'}</div></div>
          <div><div className="text-gray-500">Position size</div><div className="text-base font-semibold">{(p.size_multiplier * 100).toFixed(0)}%</div></div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <WeightBars title="Daily / swing algorithm mix" weights={p.daily_weights} />
          <WeightBars title="Day-trading algorithm mix (market hours)" weights={p.intraday_weights} />
        </div>

        <div className="text-xs text-gray-500">
          BUY threshold {p.buy_threshold_adj >= 0 ? '+' : ''}{p.buy_threshold_adj.toFixed(2)} ·
          SELL threshold {p.sell_threshold_adj >= 0 ? '+' : ''}{p.sell_threshold_adj.toFixed(2)} ·
          ATR stop {p.stop_multiplier_adj >= 0 ? '+' : ''}{p.stop_multiplier_adj.toFixed(1)}×
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <div className="text-xs text-gray-500 mb-1.5">
              Swing picks — S&amp;P 500 + growth ({u.size ?? '…'} screened)
            </div>
            <div className="flex flex-wrap gap-1.5">
              {u.swing.length === 0 && <span className="text-xs text-gray-600">Screen runs with the next scan</span>}
              {u.swing.map((t) => (
                <span key={t} className="text-xs px-2 py-0.5 rounded bg-gray-800 text-gray-200"
                  title={u.details[t] ? `RSI ${u.details[t].rsi.toFixed(0)} · ATR ${(u.details[t].atr_pct * 100).toFixed(1)}% · vol ×${u.details[t].vol_surge.toFixed(1)}` : ''}>
                  {t}
                </span>
              ))}
            </div>
          </div>
          <div>
            <div className="text-xs text-gray-500 mb-1.5 flex items-center gap-1"><Zap size={11} className="text-yellow-400" /> Day-trade picks</div>
            <div className="flex flex-wrap gap-1.5">
              {u.day.length === 0 && <span className="text-xs text-gray-600">—</span>}
              {u.day.map((t) => (
                <span key={t} className="text-xs px-2 py-0.5 rounded bg-yellow-950 text-yellow-200 border border-yellow-900/60"
                  title={u.details[t] ? `RSI ${u.details[t].rsi.toFixed(0)} · ATR ${(u.details[t].atr_pct * 100).toFixed(1)}% · vol ×${u.details[t].vol_surge.toFixed(1)}` : ''}>
                  {t}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
