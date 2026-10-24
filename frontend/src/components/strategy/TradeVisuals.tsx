import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import {
  ResponsiveContainer, ComposedChart, BarChart, Bar, Line, XAxis, YAxis, Tooltip, Cell, ReferenceLine,
} from 'recharts'
import { getDayTrading, type DayTradeRow } from '../../api/dayTrading'

const GREEN = '#22c55e'
const RED = '#ef4444'
const AMBER = '#eab308'
const usd = (v: number, signed = true) =>
  `${signed && v > 0 ? '+' : ''}${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const colorOf = (t: DayTradeRow) => (t.outcome === 'win' ? GREEN : t.outcome === 'loss' ? RED : AMBER)

/** Minutes since midnight and calendar day in New York time, for placing a trade on a 9:30–16:00 axis. */
function etParts(iso: string): { day: string; minutes: number } {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(iso))
  const g = (t: string) => parts.find((p) => p.type === t)!.value
  return { day: `${g('year')}-${g('month')}-${g('day')}`, minutes: parseInt(g('hour')) * 60 + parseInt(g('minute')) }
}

const sortedAsc = (trades: DayTradeRow[]) =>
  [...trades].sort((a, b) => (a.entry_time ?? '').localeCompare(b.entry_time ?? ''))

// ── 1. Streak strip ───────────────────────────────────────────────────────────

export function TradeStripView({ trades, limit = 60 }: { trades: DayTradeRow[]; limit?: number }) {
  const recent = sortedAsc(trades).slice(-limit)
  if (recent.length === 0) return <div className="text-xs text-gray-600">No day trades yet</div>
  const closed = recent.filter((t) => t.outcome !== 'open')
  const wins = closed.filter((t) => t.outcome === 'win').length
  let streak = 0
  const last = closed[closed.length - 1]?.outcome
  for (let i = closed.length - 1; i >= 0 && closed[i].outcome === last; i--) streak++
  return (
    <div>
      <div className="flex flex-wrap gap-1">
        {recent.map((t) => (
          <span key={t.id} title={`${t.ticker}${t.side === 'short' ? ' (short)' : ''} ${t.pnl != null ? usd(t.pnl) : 'open'}`}
            className={`inline-block w-3 h-3 rounded-sm ${t.outcome === 'open' ? 'animate-pulse' : ''}`}
            style={{ background: colorOf(t) }} />
        ))}
      </div>
      <div className="text-[11px] text-gray-500 mt-1.5">
        Last {closed.length} closed: {wins} won / {closed.length - wins} lost
        {last && <> · current streak {streak} {last === 'win' ? 'win' : 'loss'}{streak === 1 ? '' : last === 'win' ? 's' : 'es'}</>}
      </div>
    </div>
  )
}

/** Self-fetching version (shares the Day Trading page's query cache). */
export function TradeStrip({ limit = 60 }: { limit?: number }) {
  const { data } = useQuery({ queryKey: ['dayTrading'], queryFn: getDayTrading, refetchInterval: 30_000 })
  return <TradeStripView trades={data?.trades ?? []} limit={limit} />
}

// ── 2. Timeline: when each trade was open during the session ──────────────────

export function TradeTimeline({ trades, maxDays = 10 }: { trades: DayTradeRow[]; maxDays?: number }) {
  const { rows, days } = useMemo(() => {
    const open = 9 * 60 + 30, span = 390
    const byDay: Record<string, Array<{ t: DayTradeRow; x0: number; x1: number }>> = {}
    for (const t of trades) {
      if (!t.entry_time) continue
      const a = etParts(t.entry_time)
      const nowParts = etParts(new Date().toISOString())
      let end = t.exit_time ? etParts(t.exit_time) : nowParts
      const sameDay = end.day === a.day
      const x0 = Math.max(0, Math.min(1, (a.minutes - open) / span))
      const x1 = sameDay ? Math.max(x0 + 0.004, Math.min(1, (end.minutes - open) / span)) : 1
      ;(byDay[a.day] ||= []).push({ t, x0, x1 })
    }
    const days = Object.keys(byDay).sort().reverse().slice(0, maxDays)
    return { rows: byDay, days }
  }, [trades, maxDays])

  if (days.length === 0) return <div className="text-xs text-gray-600 py-6 text-center">No trades to plot yet</div>
  const rowH = 30, left = 62, W = 1000, H = days.length * rowH + 26
  const hours = [10, 11, 12, 13, 14, 15, 16]
  const X = (frac: number) => left + frac * (W - left - 10)

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[640px]" role="img" aria-label="Day-trade timeline">
        {hours.map((h) => {
          const x = X((h * 60 - 570) / 390)
          return (
            <g key={h}>
              <line x1={x} x2={x} y1={0} y2={H - 20} stroke="#1f2937" />
              <text x={x} y={H - 6} fill="#6b7280" fontSize="11" textAnchor="middle">{h}:00</text>
            </g>
          )
        })}
        {/* forced exit at 15:50 */}
        <line x1={X((15 * 60 + 50 - 570) / 390)} x2={X((15 * 60 + 50 - 570) / 390)} y1={0} y2={H - 20} stroke="#7c3aed" strokeDasharray="4 3" />
        {days.map((d, i) => (
          <g key={d} transform={`translate(0 ${i * rowH})`}>
            <text x={left - 8} y={rowH / 2 + 4} fill="#9ca3af" fontSize="11" textAnchor="end">{dayjs(d).format('ddd MM/DD')}</text>
            <line x1={left} x2={W - 10} y1={rowH - 1} y2={rowH - 1} stroke="#111827" />
            {rows[d].map(({ t, x0, x1 }, k) => {
              const lane = k % 2
              return (
                <g key={t.id}>
                  <title>{`${t.ticker}${t.side === 'short' ? ' SHORT' : ''}  ${t.pnl != null ? usd(t.pnl) : 'open'}  ${t.exit_reason ?? ''}`}</title>
                  <rect x={X(x0)} y={4 + lane * 11} width={Math.max(3, X(x1) - X(x0))} height={9} rx={2}
                    fill={colorOf(t)} opacity={0.85} />
                  {X(x1) - X(x0) > 38 && (
                    <text x={X(x0) + 3} y={12 + lane * 11} fontSize="8" fill="#0b1220" fontWeight="700">{t.ticker}</text>
                  )}
                </g>
              )
            })}
          </g>
        ))}
      </svg>
      <div className="flex flex-wrap gap-4 text-[11px] text-gray-500 mt-1 pl-1">
        <span><span className="inline-block w-2.5 h-2.5 rounded-sm mr-1" style={{ background: GREEN }} />win</span>
        <span><span className="inline-block w-2.5 h-2.5 rounded-sm mr-1" style={{ background: RED }} />loss</span>
        <span><span className="inline-block w-2.5 h-2.5 rounded-sm mr-1" style={{ background: AMBER }} />open</span>
        <span><span className="inline-block w-3 border-t border-dashed border-purple-500 mr-1 align-middle" />15:50 forced exit</span>
        <span>Times are New York market hours; bar length = how long the trade was open.</span>
      </div>
    </div>
  )
}

// ── 3. P&L per trade with running total ───────────────────────────────────────

export function TradePnlBars({ trades }: { trades: DayTradeRow[] }) {
  const data = useMemo(() => {
    let run = 0
    return sortedAsc(trades.filter((t) => t.outcome !== 'open' && t.pnl != null)).map((t, i) => {
      run += t.pnl as number
      return { n: i + 1, label: `${t.ticker}${t.side === 'short' ? ' (short)' : ''}`, pnl: t.pnl as number, total: +run.toFixed(2), when: t.exit_time ?? t.entry_time }
    })
  }, [trades])
  if (data.length === 0) return <div className="text-xs text-gray-600 py-6 text-center">No closed trades yet</div>
  return (
    <ResponsiveContainer width="100%" height={220}>
      <ComposedChart data={data}>
        <XAxis dataKey="n" tick={{ fontSize: 10 }} />
        <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `$${v}`} />
        <Tooltip contentStyle={{ background: '#1f2937', border: '1px solid #374151', fontSize: 11 }}
          labelFormatter={(n) => { const d = data[Number(n) - 1]; return d ? `#${n} ${d.label} · ${d.when ? dayjs(d.when).format('MMM D HH:mm') : ''}` : String(n) }}
          formatter={(v: number, name) => [usd(v), name === 'total' ? 'Running total' : 'Trade P&L']} />
        <ReferenceLine y={0} stroke="#4b5563" />
        <Bar dataKey="pnl" radius={[2, 2, 0, 0]}>
          {data.map((d) => <Cell key={d.n} fill={d.pnl > 0 ? GREEN : RED} />)}
        </Bar>
        <Line type="monotone" dataKey="total" stroke="#60a5fa" strokeWidth={2} dot={false} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

// ── 4. Distribution of trade results ──────────────────────────────────────────

export function PnlHistogram({ trades }: { trades: DayTradeRow[] }) {
  const bins = useMemo(() => {
    const p = trades.filter((t) => t.outcome !== 'open' && t.pnl != null).map((t) => t.pnl as number)
    if (p.length < 3) return []
    const lo = Math.min(...p), hi = Math.max(...p)
    const n = Math.min(12, Math.max(5, Math.round(Math.sqrt(p.length))))
    const w = (hi - lo) / n || 1
    const out = Array.from({ length: n }, (_, i) => ({ from: lo + i * w, to: lo + (i + 1) * w, count: 0 }))
    for (const v of p) out[Math.min(n - 1, Math.floor((v - lo) / w))].count++
    return out.map((b) => ({ ...b, mid: (b.from + b.to) / 2, label: `${Math.round(b.from)}…${Math.round(b.to)}` }))
  }, [trades])
  if (bins.length === 0) return <div className="text-xs text-gray-600 py-6 text-center">Needs at least 3 closed trades</div>
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={bins}>
        <XAxis dataKey="label" tick={{ fontSize: 9 }} interval={0} angle={-30} textAnchor="end" height={46} />
        <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
        <Tooltip contentStyle={{ background: '#1f2937', border: '1px solid #374151', fontSize: 11 }}
          formatter={(v: number) => [`${v} trade${v === 1 ? '' : 's'}`, 'Count']} labelFormatter={(l) => `P&L $${l}`} />
        <Bar dataKey="count" radius={[2, 2, 0, 0]}>
          {bins.map((b, i) => <Cell key={i} fill={b.mid > 0 ? GREEN : RED} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

// ── 5. Stop ←→ target range bars: where each trade actually ended ─────────────

export function TradeRangeBars({ trades, limit = 12 }: { trades: DayTradeRow[]; limit?: number }) {
  const rows = sortedAsc(trades).filter((t) => t.stop_price != null && t.target_price != null).slice(-limit).reverse()
  if (rows.length === 0) return <div className="text-xs text-gray-600 py-6 text-center">No trades with a stop and target yet</div>
  return (
    <div className="space-y-2">
      {rows.map((t) => {
        const pts = [t.stop_price!, t.target_price!, t.entry_price, ...(t.exit_price != null ? [t.exit_price] : [])]
        const lo = Math.min(...pts), hi = Math.max(...pts), pad = (hi - lo) * 0.06 || 0.5
        const min = lo - pad, max = hi + pad
        const pct = (p: number) => ((p - min) / (max - min)) * 100
        const entry = pct(t.entry_price), stop = pct(t.stop_price!), tgt = pct(t.target_price!)
        const exit = t.exit_price != null ? pct(t.exit_price) : null
        return (
          <div key={t.id} className="flex items-center gap-3">
            <div className="w-24 flex-shrink-0 text-xs">
              <span className="font-medium text-gray-200">{t.ticker}</span>
              {t.side === 'short' && <span className="ml-1 text-[9px] px-1 py-0.5 rounded bg-red-900/60 text-red-300">SHORT</span>}
              <div className="text-[10px] text-gray-500">{t.entry_time ? dayjs(t.entry_time).format('MM/DD HH:mm') : ''}</div>
            </div>
            <div className="relative flex-1 h-6">
              <div className="absolute top-2.5 h-1 rounded bg-gray-800 left-0 right-0" />
              {/* loss zone: stop → entry, profit zone: entry → target */}
              <div className="absolute top-2 h-2 rounded-l bg-red-900/70" style={{ left: `${Math.min(stop, entry)}%`, width: `${Math.abs(entry - stop)}%` }} />
              <div className="absolute top-2 h-2 rounded-r bg-green-900/70" style={{ left: `${Math.min(entry, tgt)}%`, width: `${Math.abs(tgt - entry)}%` }} />
              <div className="absolute top-0.5 h-5 w-px bg-gray-300" style={{ left: `${entry}%` }} title={`Entry $${t.entry_price.toFixed(2)}`} />
              <div className="absolute top-1 h-4 w-0.5 bg-red-500" style={{ left: `${stop}%` }} title={`Stop $${t.stop_price!.toFixed(2)}`} />
              <div className="absolute top-1 h-4 w-0.5 bg-green-500" style={{ left: `${tgt}%` }} title={`Target $${t.target_price!.toFixed(2)}`} />
              {exit != null && (
                <div className="absolute top-1.5 h-3 w-3 -ml-1.5 rounded-full border-2 border-gray-900" style={{ left: `${exit}%`, background: colorOf(t) }}
                  title={`Exit $${t.exit_price!.toFixed(2)} (${t.exit_reason ?? ''})`} />
              )}
            </div>
            <div className={`w-20 flex-shrink-0 text-right text-xs font-mono ${t.pnl == null ? 'text-yellow-400' : t.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {t.pnl == null ? 'open' : usd(t.pnl)}
            </div>
          </div>
        )
      })}
      <div className="text-[11px] text-gray-500 pt-1">
        <span className="text-red-400">red</span> = stop-to-entry risk zone · <span className="text-green-400">green</span> = entry-to-target reward zone ·
        white tick = entry · dot = where it actually exited. Exits at the middle (not at an end) were closed by the 15:50 forced exit or a signal.
      </div>
    </div>
  )
}
