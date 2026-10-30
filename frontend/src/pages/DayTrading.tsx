import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Cell, ReferenceLine, LineChart, Line,
} from 'recharts'
import { Timer, Info, CheckCircle2, XCircle, SlidersHorizontal, Trophy, AlertTriangle } from 'lucide-react'
import { getDayTrading, type PeriodStats, type RuleRow, type DayTradeRow } from '../api/dayTrading'
import PatternsPanel from '../components/strategy/PatternsPanel'
import { TradeStripView, TradeTimeline, TradePnlBars, PnlHistogram, TradeRangeBars } from '../components/strategy/TradeVisuals'

const usd = (v: number | null | undefined, signed = false) =>
  v == null ? '—' : `${signed && v > 0 ? '+' : ''}${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const pctFmt = (v: number | null | undefined, d = 0) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`)
const tone = (v: number | null | undefined) => (v == null || v === 0 ? 'text-gray-300' : v > 0 ? 'text-green-400' : 'text-red-400')

const REASON: Record<string, { label: string; cls: string }> = {
  take_profit: { label: 'Target hit', cls: 'bg-green-900 text-green-300' },
  stop: { label: 'Stopped out', cls: 'bg-red-900 text-red-300' },
  eod: { label: 'End of day', cls: 'bg-blue-900 text-blue-300' },
  signal: { label: 'Signal exit', cls: 'bg-gray-800 text-gray-300' },
  unknown: { label: 'Unknown', cls: 'bg-gray-800 text-gray-400' },
}

function ExplainBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-3 bg-blue-950/30 border border-blue-900/50 rounded-xl px-4 py-3 text-xs text-gray-400 leading-relaxed">
      <Info size={14} className="text-blue-400 flex-shrink-0 mt-0.5" />
      <div>{children}</div>
    </div>
  )
}

function Card({ label, value, sub, cls = 'text-white' }: { label: string; value: string; sub?: string; cls?: string }) {
  return (
    <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className={`text-2xl font-bold ${cls}`}>{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </div>
  )
}

function formatRule(r: RuleRow): string {
  const v = r.value
  if (v == null) return '—'
  if (typeof v === 'boolean') return v ? 'ON' : 'OFF'
  if (typeof v === 'string') return v
  if (r.key === 'risk_per_trade' || r.key === 'max_position_pct' || r.key === 'daily_loss_halt') return `${(v * 100).toFixed(2)}%`
  if (r.key === 'reward_risk') return `${v.toFixed(2)} : 1`
  return String(v)
}

function RuleGroup({ title, rules }: { title: string; rules: RuleRow[] }) {
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800">
      <div className="px-4 py-3 border-b border-gray-800 text-sm font-medium">{title}</div>
      <div className="divide-y divide-gray-800">
        {rules.map((r) => {
          const changed = r.default != null && typeof r.value === 'number' && Math.abs(r.value - r.default) > 1e-9
          const off = r.key === 'day_trade_only' && r.value === false
          return (
            <div key={r.key} className="px-4 py-2.5" title={r.help}>
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-gray-300">{r.label}</span>
                <span className={`text-sm font-mono font-semibold ${off ? 'text-yellow-400' : 'text-white'}`}>
                  {formatRule(r)}
                  {changed && <span className="ml-2 text-xs font-normal text-purple-300">learned (default {r.default})</span>}
                </span>
              </div>
              <div className="text-xs text-gray-500 mt-0.5">
                {r.help}{r.env && <span className="text-gray-600"> · set with <code>{r.env}</code></span>}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

type Filter = 'all' | 'win' | 'loss' | 'open'

export default function DayTrading() {
  const { data, isLoading, isError } = useQuery({ queryKey: ['dayTrading'], queryFn: getDayTrading, refetchInterval: 30_000 })
  const [period, setPeriod] = useState<'today' | 'week' | 'all'>('all')
  const [filter, setFilter] = useState<Filter>('all')

  if (isLoading) return <div className="text-gray-500">Loading day-trading data…</div>
  if (isError || !data) return <div className="text-red-400 text-sm">Could not load day-trading data from the backend.</div>

  const s: PeriodStats = data.stats[period]
  const st = data.settings
  const trades = data.trades.filter((t) => filter === 'all' || t.outcome === filter)
  const counts = {
    all: data.trades.length,
    win: data.trades.filter((t) => t.outcome === 'win').length,
    loss: data.trades.filter((t) => t.outcome === 'loss').length,
    open: data.trades.filter((t) => t.outcome === 'open').length,
  }
  const reasons = Object.entries(data.exit_reasons).sort((a, b) => b[1].count - a[1].count)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold mb-3 flex items-center gap-2"><Timer size={20} className="text-yellow-400" /> Day Trading</h1>
        <ExplainBox>
          A <strong className="text-gray-300">day trade</strong> opens and closes the same day: the bot enters with a stop-loss and a take-profit attached and
          closes whatever is left at the forced exit time. In a <strong className="text-gray-300">bear market</strong> it can also <strong className="text-gray-300">short</strong> breakdowns (stop above, target below) and covers them the same day. A <strong className="text-gray-300">win</strong> is a closed trade with a profit; a <strong className="text-gray-300">loss</strong> is
          a closed trade at breakeven or below. Below you can monitor the active rules, how trades are actually doing, and every individual trade.
          Rules marked <em>learned</em> are re-tuned each night by the self-learning job.
        </ExplainBox>
      </div>

      {/* Status strip */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className={`px-2.5 py-1 rounded-full font-medium ${st.autopilot ? 'bg-blue-900/60 text-blue-300' : 'bg-gray-800 text-gray-400'}`}>
          Autopilot {st.autopilot ? 'ON' : 'OFF'}
        </span>
        <span className={`px-2.5 py-1 rounded-full font-medium ${st.market_open ? 'bg-green-900/50 text-green-300' : 'bg-gray-800 text-gray-400'}`}>
          Market {st.market_open ? 'open' : 'closed'}
        </span>
        <span className={`px-2.5 py-1 rounded-full font-medium ${st.trading_mode === 'live' ? 'bg-red-900/60 text-red-300' : 'bg-green-900/30 text-green-400'}`}>
          {st.trading_mode === 'live' ? 'LIVE — real money' : 'Paper money'}
        </span>
        <span className="px-2.5 py-1 rounded-full bg-yellow-900/40 text-yellow-300 font-medium">{data.open_trades} open day trade{data.open_trades === 1 ? '' : 's'}</span>
        {st.entry_rules.find((r) => r.key === 'day_trade_only')?.value === false && (
          <span className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-yellow-900/40 text-yellow-300 font-medium">
            <AlertTriangle size={12} /> Day-trade-only is OFF — swing positions are allowed
          </span>
        )}
      </div>

      {/* Period selector + headline stats */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          {(['today', 'week', 'all'] as const).map((p) => (
            <button key={p} onClick={() => setPeriod(p)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium ${period === p ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'}`}>
              {p === 'today' ? 'Today' : p === 'week' ? 'Last 7 days' : 'All time'}
            </button>
          ))}
          <span className="text-xs text-gray-500 ml-2">{s.closed} closed trade{s.closed === 1 ? '' : 's'}</span>
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Card label="Net P&L" value={usd(s.net_pnl, true)} cls={tone(s.net_pnl)}
            sub={`${usd(s.gross_profit)} won · ${usd(s.gross_loss)} lost`} />
          <Card label="Win rate" value={pctFmt(s.win_rate, 1)} cls={s.win_rate == null ? 'text-gray-300' : s.win_rate >= 0.5 ? 'text-green-400' : 'text-yellow-400'}
            sub={`${s.wins} winners · ${s.losses} losers`} />
          <Card label="Profit factor" value={s.profit_factor == null ? '—' : s.profit_factor.toFixed(2)}
            cls={s.profit_factor == null ? 'text-gray-300' : s.profit_factor >= 1 ? 'text-green-400' : 'text-red-400'}
            sub="gross profit ÷ gross loss (>1 = profitable)" />
          <Card label="Expectancy / trade" value={usd(s.expectancy, true)} cls={tone(s.expectancy)}
            sub={`avg hold ${s.avg_hold_min != null ? `${Math.round(s.avg_hold_min)}m` : '—'}`} />
          <Card label="Average win" value={usd(s.avg_win)} cls="text-green-400" sub={`best ${usd(s.best)}`} />
          <Card label="Average loss" value={usd(s.avg_loss)} cls="text-red-400" sub={`worst ${usd(s.worst)}`} />
          <Card label="Winners" value={String(s.wins)} cls="text-green-400" />
          <Card label="Losers" value={String(s.losses)} cls="text-red-400" />
        </div>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
          <div className="text-sm font-medium mb-3">Daily P&amp;L</div>
          {data.daily.length === 0 ? <div className="text-xs text-gray-500 py-8 text-center">No closed day trades yet</div> : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={data.daily}>
                <XAxis dataKey="day" tick={{ fontSize: 10 }} tickFormatter={(v) => dayjs(v).format('MM/DD')} />
                <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `$${v}`} />
                <Tooltip contentStyle={{ background: '#1f2937', border: '1px solid #374151', fontSize: 11 }}
                  formatter={(v: number) => [usd(v, true), 'P&L']} labelFormatter={(l) => dayjs(l).format('ddd MMM D')} />
                <ReferenceLine y={0} stroke="#4b5563" />
                <Bar dataKey="pnl" radius={[3, 3, 0, 0]}>
                  {data.daily.map((d) => <Cell key={d.day} fill={d.pnl >= 0 ? '#22c55e' : '#ef4444'} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
          <div className="text-sm font-medium mb-3">Cumulative day-trade P&amp;L</div>
          {data.daily.length === 0 ? <div className="text-xs text-gray-500 py-8 text-center">No closed day trades yet</div> : (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={data.daily}>
                <XAxis dataKey="day" tick={{ fontSize: 10 }} tickFormatter={(v) => dayjs(v).format('MM/DD')} />
                <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `$${v}`} />
                <Tooltip contentStyle={{ background: '#1f2937', border: '1px solid #374151', fontSize: 11 }}
                  formatter={(v: number) => [usd(v, true), 'Cumulative']} labelFormatter={(l) => dayjs(l).format('ddd MMM D')} />
                <ReferenceLine y={0} stroke="#4b5563" />
                <Line type="monotone" dataKey="cumulative" stroke="#3b82f6" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Visual trade view */}
      <div className="space-y-6">
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
          <div className="text-sm font-medium mb-1">Recent results</div>
          <div className="text-xs text-gray-500 mb-3">One square per trade, oldest to newest — hover for the ticker and P&amp;L.</div>
          <TradeStripView trades={data.trades} limit={80} />
        </div>
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
          <div className="text-sm font-medium mb-1">Trade timeline</div>
          <div className="text-xs text-gray-500 mb-3">When each trade was open during the 9:30–16:00 session, by day.</div>
          <TradeTimeline trades={data.trades} />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
            <div className="text-sm font-medium mb-3">P&amp;L per trade <span className="text-xs text-gray-500 font-normal">· blue line = running total</span></div>
            <TradePnlBars trades={data.trades} />
          </div>
          <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
            <div className="text-sm font-medium mb-3">Distribution of results <span className="text-xs text-gray-500 font-normal">· trades per P&amp;L bucket ($)</span></div>
            <PnlHistogram trades={data.trades} />
          </div>
        </div>
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
          <div className="text-sm font-medium mb-1">Where trades ended: stop ↔ target</div>
          <div className="text-xs text-gray-500 mb-3">Last 12 trades — how close each came to its stop or its profit target.</div>
          <TradeRangeBars trades={data.trades} />
        </div>
        <PatternsPanel />
      </div>

      {/* How trades end + tickers */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-gray-900 rounded-xl border border-gray-800">
          <div className="px-4 py-3 border-b border-gray-800 text-sm font-medium">How trades end</div>
          <div className="divide-y divide-gray-800">
            {reasons.length === 0 && <div className="px-4 py-6 text-center text-gray-500 text-sm">No closed trades yet</div>}
            {reasons.map(([k, r]) => {
              const meta = REASON[k] ?? REASON.unknown
              return (
                <div key={k} className="px-4 py-3 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className={`text-xs px-2 py-0.5 rounded ${meta.cls}`}>{meta.label}</span>
                    <span className="text-sm text-gray-300">{r.count} trade{r.count === 1 ? '' : 's'}</span>
                    <span className="text-xs text-gray-500">{r.wins} won · {r.count - r.wins} lost</span>
                  </div>
                  <span className={`text-sm font-mono ${tone(r.pnl)}`}>{usd(r.pnl, true)}</span>
                </div>
              )
            })}
          </div>
        </div>
        <div className="bg-gray-900 rounded-xl border border-gray-800">
          <div className="px-4 py-3 border-b border-gray-800 text-sm font-medium flex items-center gap-2"><Trophy size={14} className="text-yellow-400" /> By ticker</div>
          <div className="grid grid-cols-2 divide-x divide-gray-800">
            {([['Best', data.tickers.best, 'text-green-400'], ['Worst', data.tickers.worst, 'text-red-400']] as const).map(([title, rows, cls]) => (
              <div key={title} className="p-3 space-y-1.5">
                <div className="text-xs text-gray-500">{title}</div>
                {rows.length === 0 && <div className="text-xs text-gray-600">—</div>}
                {rows.map((r) => (
                  <div key={r.ticker} className="flex items-center justify-between text-sm">
                    <span className="font-medium">{r.ticker} <span className="text-xs text-gray-500">{r.wins}/{r.trades}</span></span>
                    <span className={`font-mono text-xs ${cls}`}>{usd(r.pnl, true)}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Settings monitor */}
      <div>
        <div className="flex items-center gap-2 mb-3 text-sm font-medium"><SlidersHorizontal size={15} className="text-blue-400" /> Day-trading settings</div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <RuleGroup title="Entry rules" rules={st.entry_rules} />
          <RuleGroup title="Exit rules" rules={st.exit_rules} />
          <RuleGroup title="Risk limits" rules={st.risk_rules} />
        </div>
        <div className="mt-3 text-xs text-gray-500 space-y-1">
          <div>Settings shown are what the backend is using right now. <Link to="/settings" className="text-blue-400 hover:text-blue-300">Edit them in Settings → Trading settings</Link> — changes apply on the next scan and survive restarts.</div>
          <div>
            Learning: {st.learning.enabled ? 'on' : 'off'} — {st.learning.note}
            {st.learning.last_review && (
              <span className="text-gray-400"> Last review {st.learning.last_review.date}: {st.learning.last_review.notes.join('; ') || 'no changes'}.</span>
            )}
          </div>
        </div>
      </div>

      {/* Trade list */}
      <div className="bg-gray-900 rounded-xl border border-gray-800">
        <div className="px-4 py-3 border-b border-gray-800 flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm font-medium">Trades</div>
          <div className="flex gap-1.5">
            {([
              ['all', `All (${counts.all})`],
              ['win', `Successful (${counts.win})`],
              ['loss', `Failed (${counts.loss})`],
              ['open', `Open (${counts.open})`],
            ] as const).map(([k, label]) => (
              <button key={k} onClick={() => setFilter(k)}
                className={`px-3 py-1 rounded-lg text-xs font-medium ${filter === k
                  ? (k === 'win' ? 'bg-green-700 text-white' : k === 'loss' ? 'bg-red-700 text-white' : 'bg-blue-600 text-white')
                  : 'bg-gray-800 text-gray-400 hover:text-white'}`}>
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 border-b border-gray-800">
                <th className="px-4 py-2 text-left">Result</th>
                <th className="px-4 py-2 text-left">Ticker</th>
                <th className="px-4 py-2 text-left">Entry</th>
                <th className="px-4 py-2 text-left">Exit</th>
                <th className="px-4 py-2 text-right">Qty</th>
                <th className="px-4 py-2 text-right">P&amp;L</th>
                <th className="px-4 py-2 text-right">Held</th>
                <th className="px-4 py-2 text-left">Closed by</th>
                <th className="px-4 py-2 text-left">Market</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {trades.map((t: DayTradeRow) => (
                <tr key={t.id} className={t.outcome === 'win' ? 'bg-green-950/10' : t.outcome === 'loss' ? 'bg-red-950/10' : ''}>
                  <td className="px-4 py-2.5">
                    {t.outcome === 'win' && <span className="flex items-center gap-1 text-green-400 text-xs font-medium"><CheckCircle2 size={14} /> Win</span>}
                    {t.outcome === 'loss' && <span className="flex items-center gap-1 text-red-400 text-xs font-medium"><XCircle size={14} /> Loss</span>}
                    {t.outcome === 'open' && <span className="text-xs px-2 py-0.5 rounded bg-yellow-900 text-yellow-300">OPEN</span>}
                  </td>
                  <td className="px-4 py-2.5 font-medium">{t.ticker}
                    {t.side === 'short' && <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-red-900/60 text-red-300 align-middle">SHORT</span>}
                  </td>
                  <td className="px-4 py-2.5">${t.entry_price.toFixed(2)}
                    <div className="text-xs text-gray-500">{t.entry_time ? dayjs(t.entry_time).format('MMM D HH:mm') : ''}</div></td>
                  <td className="px-4 py-2.5">{t.exit_price != null ? `$${t.exit_price.toFixed(2)}` : '—'}
                    <div className="text-xs text-gray-500">{t.exit_time ? dayjs(t.exit_time).format('HH:mm') : t.target_price ? `target $${t.target_price.toFixed(2)}` : ''}</div></td>
                  <td className="px-4 py-2.5 text-right">{t.qty}</td>
                  <td className={`px-4 py-2.5 text-right font-mono font-medium ${tone(t.pnl)}`}>
                    {t.pnl != null ? `${usd(t.pnl, true)}` : '—'}
                    {t.pnl_pct != null && <div className="text-xs font-normal">{(t.pnl_pct * 100).toFixed(2)}%</div>}
                  </td>
                  <td className="px-4 py-2.5 text-right text-gray-400">{t.held_minutes != null ? `${t.held_minutes}m` : '—'}</td>
                  <td className="px-4 py-2.5">
                    {t.exit_reason && <span className={`text-xs px-2 py-0.5 rounded ${(REASON[t.exit_reason] ?? REASON.unknown).cls}`}>{(REASON[t.exit_reason] ?? REASON.unknown).label}</span>}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-400">{t.bias ?? '—'}</td>
                </tr>
              ))}
              {trades.length === 0 && (
                <tr><td colSpan={9} className="px-4 py-8 text-center text-gray-500">No trades in this view</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
