import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { SlidersHorizontal, RotateCcw, AlertTriangle, CheckCircle2, ArrowRight, Save, Trash2, Play } from 'lucide-react'
import {
  getTradingConfig, saveTradingConfig, resetTradingConfig, configErrors,
  getProfiles, saveProfile, applyProfile, deleteProfile,
  type ConfigField, type ConfigValue,
} from '../../api/tradingConfig'
import { TradeStrip } from './TradeVisuals'

// Percent-type fields are stored as fractions (0.01) but edited as percents (1%)
const toDisplay = (f: ConfigField, v: ConfigValue) => (f.pct && typeof v === 'number' ? +(v * 100).toFixed(4) : v)
const fromDisplay = (f: ConfigField, v: number) => (f.pct ? +(v / 100).toFixed(6) : v)

function fmtValue(f: ConfigField, v: ConfigValue | null): string {
  if (v == null) return '—'
  if (typeof v === 'boolean') return v ? 'On' : 'Off'
  if (typeof v === 'number') return f.pct ? `${(v * 100).toFixed(2)}%` : String(v)
  return String(v)
}

function Toggle({ on, onChange, danger }: { on: boolean; onChange: (v: boolean) => void; danger?: boolean }) {
  return (
    <button type="button" onClick={() => onChange(!on)} role="switch" aria-checked={on}
      className={`relative inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full transition-colors ${on ? (danger ? 'bg-red-600' : 'bg-blue-600') : 'bg-gray-600'}`}>
      <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${on ? 'translate-x-6' : 'translate-x-1'}`} />
    </button>
  )
}

function FieldRow({
  f, draftValue, error, onChange, onReset,
}: {
  f: ConfigField
  draftValue: ConfigValue
  error?: string
  onChange: (v: ConfigValue) => void
  onReset: () => void
}) {
  const dirty = draftValue !== f.value
  return (
    <div className={`px-4 py-3 ${dirty ? 'bg-blue-950/20' : ''}`}>
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-sm ${f.danger ? 'text-red-300' : 'text-gray-200'}`}>{f.label}</span>
            {f.customized && <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-900/60 text-purple-300">custom</span>}
            {f.restart && <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">applies on next start</span>}
            {dirty && <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-900/60 text-blue-300">unsaved</span>}
          </div>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          {f.type === 'bool' && <Toggle on={draftValue as boolean} danger={f.danger} onChange={onChange} />}
          {(f.type === 'float' || f.type === 'int') && (
            <div className="flex items-center gap-2">
              <input
                type="range" className="w-28 accent-blue-500 hidden sm:block"
                min={toDisplay(f, f.min as number) as number} max={toDisplay(f, f.max as number) as number}
                step={f.pct && f.step ? f.step * 100 : f.step ?? 0.01}
                value={toDisplay(f, draftValue) as number}
                onChange={(e) => onChange(fromDisplay(f, parseFloat(e.target.value)))}
              />
              <div className="flex items-center">
                <input
                  type="number"
                  className="w-20 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-right font-mono focus:outline-none focus:border-blue-500"
                  min={toDisplay(f, f.min as number) as number} max={toDisplay(f, f.max as number) as number}
                  step={f.pct && f.step ? f.step * 100 : f.step ?? 0.01}
                  value={toDisplay(f, draftValue) as number}
                  onChange={(e) => e.target.value !== '' && onChange(fromDisplay(f, parseFloat(e.target.value)))}
                />
                {f.pct && <span className="text-xs text-gray-500 ml-1">%</span>}
              </div>
            </div>
          )}
          {f.type === 'time' && (
            <input type="time" min={f.min as string} max={f.max as string} value={draftValue as string}
              onChange={(e) => e.target.value && onChange(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm font-mono focus:outline-none focus:border-blue-500" />
          )}
          <button type="button" onClick={onReset} disabled={!f.customized}
            title={f.customized ? `Reset to ${fmtValue(f, f.default as ConfigValue)}` : 'Already at the default'}
            className="text-gray-500 hover:text-white disabled:opacity-20 disabled:hover:text-gray-500">
            <RotateCcw size={13} />
          </button>
        </div>
      </div>
      <div className="text-xs text-gray-500 mt-1 pr-6">{f.help}</div>
      {f.type !== 'bool' && f.min != null && f.max != null && (
        <div className="text-[11px] text-gray-600 mt-0.5">
          allowed {f.pct ? `${(+f.min * 100).toFixed(2)}–${(+f.max * 100).toFixed(2)}%` : `${f.min}–${f.max}`}
          {f.default != null && <> · default {fmtValue(f, f.default as ConfigValue)}</>}
        </div>
      )}
      {error && <div className="text-xs text-red-400 mt-1">{error}</div>}
    </div>
  )
}

function ProfilesBar({ onApplied }: { onApplied: (fresh: unknown) => void }) {
  const qc = useQueryClient()
  const { data: profiles = [] } = useQuery({ queryKey: ['tradingProfiles'], queryFn: getProfiles })
  const [name, setName] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const done = (m: string) => { setMsg(m); setErr(null); setTimeout(() => setMsg(null), 5000) }
  const fail = (e: unknown) => { setErr(configErrors(e).general ?? 'Failed'); setMsg(null) }

  const save = useMutation({
    mutationFn: (n: string) => saveProfile(n),
    onSuccess: (list, n) => { qc.setQueryData(['tradingProfiles'], list); setName(''); done(`Saved profile "${n}" from the current settings.`) },
    onError: fail,
  })
  const apply = useMutation({
    mutationFn: (n: string) => applyProfile(n),
    onSuccess: (fresh, n) => { onApplied(fresh); done(`Loaded "${n}" — active on the next scan.`) },
    onError: fail,
  })
  const remove = useMutation({
    mutationFn: (n: string) => deleteProfile(n),
    onSuccess: (list) => { qc.setQueryData(['tradingProfiles'], list); done('Profile deleted.') },
    onError: fail,
  })
  const exists = profiles.some((p) => p.name.toLowerCase() === name.trim().toLowerCase())

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
      <div className="px-4 py-2.5 border-b border-gray-800 text-sm font-medium">Saved profiles</div>
      <div className="p-4 space-y-3">
        <p className="text-xs text-gray-500">
          Save the settings below as a named profile (e.g. "Cautious" or "Aggressive") and load it with one click. Save any unsaved edits first.
          Profiles never change the live-shorting safety lock.
        </p>
        <div className="flex gap-2">
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={40} placeholder="Profile name"
            onKeyDown={(e) => e.key === 'Enter' && name.trim() && save.mutate(name.trim())}
            className="flex-1 min-w-0 bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500" />
          <button onClick={() => save.mutate(name.trim())} disabled={!name.trim() || save.isPending}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-sm flex items-center gap-1.5 disabled:opacity-40">
            <Save size={13} /> {exists ? 'Overwrite' : 'Save current'}
          </button>
        </div>
        {profiles.length === 0 ? (
          <div className="text-xs text-gray-600">No profiles yet.</div>
        ) : (
          <div className="divide-y divide-gray-800 border border-gray-800 rounded-lg">
            {profiles.map((p) => (
              <div key={p.name} className="flex items-center justify-between gap-3 px-3 py-2">
                <div className="min-w-0">
                  <div className="text-sm text-gray-200 truncate">{p.name}</div>
                  <div className="text-[11px] text-gray-500">
                    min score {String(p.values.day_trade_min_score ?? '—')} · stop {String(p.values['learned.stop_atr'] ?? '—')} ATR ·
                    day-only {p.values.day_trade_only ? 'on' : 'off'}
                    {p.saved_at && <> · saved {new Date(p.saved_at).toLocaleDateString()}</>}
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <button onClick={() => apply.mutate(p.name)} disabled={apply.isPending}
                    className="px-2.5 py-1 bg-gray-800 hover:bg-gray-700 rounded text-xs flex items-center gap-1"><Play size={11} /> Load</button>
                  <button onClick={() => window.confirm(`Delete profile "${p.name}"?`) && remove.mutate(p.name)}
                    title="Delete" className="text-gray-500 hover:text-red-400"><Trash2 size={14} /></button>
                </div>
              </div>
            ))}
          </div>
        )}
        {msg && <div className="flex items-center gap-2 text-xs text-green-400"><CheckCircle2 size={14} /> {msg}</div>}
        {err && <div className="text-xs text-red-400">{err}</div>}
      </div>
    </div>
  )
}

export default function TradingConfigPanel() {
  const qc = useQueryClient()
  const { data, isLoading, isError } = useQuery({ queryKey: ['tradingConfig'], queryFn: getTradingConfig })
  const [draft, setDraft] = useState<Record<string, ConfigValue>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [general, setGeneral] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [confirmText, setConfirmText] = useState('')

  const afterWrite = (fresh: unknown) => {
    qc.setQueryData(['tradingConfig'], fresh)
    // anything on screen that reads these settings
    for (const k of ['dayTrading', 'tradingMode', 'riskSettings', 'adaptiveParams', 'llmStatus', 'strategyContext']) qc.invalidateQueries({ queryKey: [k] })
  }

  const save = useMutation({
    mutationFn: ({ values, confirm }: { values: Record<string, ConfigValue>; confirm: boolean }) => saveTradingConfig(values, confirm),
    onSuccess: (res) => {
      afterWrite(res)
      const n = Object.keys(res.changed).length
      setSaved(`Saved ${n} setting${n === 1 ? '' : 's'} — active on the next scan.`)
      setDraft({}); setErrors({}); setGeneral(null); setConfirmOpen(false); setConfirmText('')
      setTimeout(() => setSaved(null), 6000)
    },
    onError: (err) => {
      const e = configErrors(err)
      setErrors(e.fields); setGeneral(e.general); setSaved(null); setConfirmOpen(false)
    },
  })
  const reset = useMutation({
    mutationFn: (keys?: string[]) => resetTradingConfig(keys),
    onSuccess: (res, keys) => {
      afterWrite(res)
      setDraft((d) => (keys ? Object.fromEntries(Object.entries(d).filter(([k]) => !keys.includes(k))) : {}))
      setErrors({}); setGeneral(null)
    },
  })

  if (isLoading) return <div className="text-sm text-gray-500">Loading trading settings…</div>
  if (isError || !data) return <div className="text-sm text-red-400">Could not load trading settings from the backend.</div>

  const fields = data.groups.flatMap((g) => g.fields)
  const byKey = Object.fromEntries(fields.map((f) => [f.key, f]))
  const dirtyKeys = Object.keys(draft).filter((k) => byKey[k] && draft[k] !== byKey[k].value)
  const needsConfirm = dirtyKeys.some((k) => byKey[k].requires_confirm && draft[k] === true)
  const anyCustom = fields.some((f) => f.customized)

  function submit() {
    const values = Object.fromEntries(dirtyKeys.map((k) => [k, draft[k]]))
    if (needsConfirm) setConfirmOpen(true)
    else save.mutate({ values, confirm: false })
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium flex items-center gap-2"><SlidersHorizontal size={15} className="text-blue-400" /> Trading settings</div>
        <div className="flex items-center gap-3 text-xs">
          <Link to="/day-trading" className="text-blue-400 hover:text-blue-300 flex items-center gap-1">Monitor results <ArrowRight size={12} /></Link>
          <button onClick={() => reset.mutate(undefined)} disabled={!anyCustom || reset.isPending}
            className="text-gray-400 hover:text-white disabled:opacity-30 flex items-center gap-1"><RotateCcw size={12} /> Reset all</button>
        </div>
      </div>

      <p className="text-xs text-gray-500">
        Changes apply to the running bot immediately (the next scan uses them) and are remembered across restarts — they override <code>backend/.env</code>.
        Bounds are enforced so a typo can't turn a safeguard off.
      </p>

      {data.trading_mode === 'live' && (
        <div className="flex items-center gap-2 bg-red-900/30 border border-red-700 rounded-lg px-3 py-2 text-xs text-red-300">
          <AlertTriangle size={14} /> LIVE trading is active — edits here affect real money.
        </div>
      )}

      <div className="bg-gray-800/40 rounded-lg px-3 py-2.5">
        <div className="text-[11px] text-gray-500 mb-1.5">Recent day-trade results (green = win, red = loss)</div>
        <TradeStrip limit={50} />
      </div>

      <ProfilesBar onApplied={(fresh) => { afterWrite(fresh); setDraft({}); setErrors({}); setGeneral(null) }} />

      {data.groups.map((g) => (
        <div key={g.id} className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
          <div className="px-4 py-2.5 border-b border-gray-800 text-sm font-medium">{g.label}</div>
          <div className="divide-y divide-gray-800">
            {g.fields.map((f) => (
              <FieldRow key={f.key} f={f} draftValue={draft[f.key] ?? f.value} error={errors[f.key]}
                onChange={(v) => { setDraft((d) => ({ ...d, [f.key]: v })); setErrors((e) => { const { [f.key]: _, ...rest } = e; return rest }) }}
                onReset={() => reset.mutate([f.key])} />
            ))}
          </div>
        </div>
      ))}

      {general && <div className="text-xs text-red-400">{general}</div>}
      {saved && <div className="flex items-center gap-2 text-xs text-green-400"><CheckCircle2 size={14} /> {saved}</div>}

      <div className="flex items-center gap-3 sticky bottom-3">
        <button onClick={submit} disabled={dirtyKeys.length === 0 || save.isPending}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium disabled:opacity-40 shadow-lg">
          {save.isPending ? 'Saving…' : `Save ${dirtyKeys.length || ''} change${dirtyKeys.length === 1 ? '' : 's'}`}
        </button>
        {dirtyKeys.length > 0 && (
          <button onClick={() => { setDraft({}); setErrors({}); setGeneral(null) }} className="px-3 py-2 bg-gray-800 hover:bg-gray-700 rounded text-sm">Discard</button>
        )}
      </div>

      {confirmOpen && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-gray-900 border border-red-700 rounded-xl p-6 max-w-sm w-full mx-4">
            <div className="flex items-center gap-2 text-red-400 font-bold mb-3"><AlertTriangle size={18} /> Allow shorting in LIVE mode?</div>
            <p className="text-sm text-gray-300 mb-4">
              A short position's loss is limited only by its stop order — price can keep rising. This lets the bot short with <strong>real money</strong> when you switch to live.
              Type <strong>CONFIRM</strong> to proceed.
            </p>
            <input className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mb-4 focus:outline-none focus:border-red-500"
              placeholder="Type CONFIRM" value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />
            <div className="flex gap-3">
              <button onClick={() => { setConfirmOpen(false); setConfirmText('') }} className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm">Cancel</button>
              <button disabled={confirmText !== 'CONFIRM' || save.isPending}
                onClick={() => save.mutate({ values: Object.fromEntries(dirtyKeys.map((k) => [k, draft[k]])), confirm: true })}
                className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 rounded text-sm font-medium disabled:opacity-50">Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
