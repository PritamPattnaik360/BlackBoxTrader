import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getTradingMode, setAutonomousMode } from '../../api/settings'
import { useState } from 'react'
import { Bot, AlertTriangle, CheckCircle, Clock, XCircle } from 'lucide-react'

export default function AutoTradeStatus() {
  const qc = useQueryClient()
  const { data: mode } = useQuery({ queryKey: ['tradingMode'], queryFn: getTradingMode, refetchInterval: 5_000 })

  const [liveConfirmModal, setLiveConfirmModal] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [toggleError, setToggleError] = useState<string | null>(null)

  const toggle = useMutation({
    mutationFn: ({ enabled, confirm }: { enabled: boolean; confirm?: boolean }) =>
      setAutonomousMode(enabled, confirm),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tradingMode'] })
      setLiveConfirmModal(false)
      setConfirmText('')
      setToggleError(null)
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.detail ?? err?.message ?? 'Unknown error'
      setToggleError(msg)
    },
  })

  const autonomous = mode?.autonomous ?? false
  const isLive     = mode?.trading_mode === 'live'

  function handleToggle() {
    if (!autonomous) {
      if (isLive) {
        setLiveConfirmModal(true)
      } else {
        toggle.mutate({ enabled: true })
      }
    } else {
      toggle.mutate({ enabled: false })
    }
  }

  return (
    <>
      <div className="space-y-4">
        {/* Status header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Bot size={16} className={autonomous ? 'text-blue-400' : 'text-gray-500'} />
            <span className="text-sm font-medium">Autonomous Trading</span>
            {toggle.isPending && <span className="text-xs text-gray-400 animate-pulse">Saving…</span>}
          </div>
          {/* Toggle switch */}
          <button
            onClick={handleToggle}
            disabled={toggle.isPending}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors disabled:opacity-50
              ${autonomous ? 'bg-blue-600' : 'bg-gray-600'}`}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform
              ${autonomous ? 'translate-x-6' : 'translate-x-1'}`} />
          </button>
        </div>

        {/* Error feedback */}
        {toggleError && (
          <div className="flex items-center gap-2 bg-red-900/30 border border-red-700 rounded-lg px-3 py-2 text-xs text-red-300">
            <XCircle size={13} />
            <span>{toggleError}</span>
            <button onClick={() => setToggleError(null)} className="ml-auto text-red-400 hover:text-red-200">✕</button>
          </div>
        )}

        {/* Mode banner */}
        {autonomous ? (
          <div className={`rounded-lg border p-3 text-sm
            ${isLive
              ? 'border-red-700 bg-red-900/20 text-red-300'
              : 'border-blue-700 bg-blue-900/20 text-blue-300'}`}>
            <div className="flex items-center gap-2 font-semibold mb-1">
              <CheckCircle size={14} />
              {isLive ? '⚠ AUTO PILOT — LIVE (real money)' : 'AUTO PILOT ACTIVE — Paper money'}
            </div>
            <p className="text-xs opacity-80">
              BlackBoxTrader is scanning signals every 15 min during market hours and
              submitting orders automatically using the quant model.
              You can still place manual trades below.
            </p>
          </div>
        ) : (
          <div className="rounded-lg border border-gray-700 bg-gray-800/50 p-3 text-sm text-gray-400">
            <div className="flex items-center gap-2 mb-1">
              <Clock size={14} />
              <span className="font-medium text-gray-300">Manual mode — signals only</span>
            </div>
            <p className="text-xs">
              Signals are generated every 15 min but <strong>no orders are placed automatically</strong>.
              Enable Auto Pilot to let the quant model trade for you.
            </p>
          </div>
        )}

        {/* What the quant model uses */}
        <div className="bg-gray-800 rounded-lg p-3">
          <div className="text-xs font-medium text-gray-400 mb-2">Quant model signal weights</div>
          <div className="space-y-1.5">
            {[
              { label: 'News sentiment (NLP)', pct: 35, color: 'bg-purple-500' },
              { label: 'Momentum (12-1 month)', pct: 30, color: 'bg-blue-500' },
              { label: 'Mean reversion (Bollinger/OU)', pct: 20, color: 'bg-green-500' },
              { label: 'Technical (RSI + MACD + EMA)', pct: 15, color: 'bg-yellow-500' },
            ].map(row => (
              <div key={row.label} className="flex items-center gap-2">
                <div className="w-28 text-xs text-gray-400 shrink-0">{row.label}</div>
                <div className="flex-1 bg-gray-700 rounded-full h-1.5">
                  <div className={`${row.color} h-1.5 rounded-full`} style={{ width: `${row.pct}%` }} />
                </div>
                <div className="text-xs text-gray-400 w-8 text-right">{row.pct}%</div>
              </div>
            ))}
          </div>
          <div className="mt-2 text-xs text-gray-500">
            Position size: Kelly criterion (adaptive from trade history) · Stop: 2× ATR trailing
          </div>
        </div>

        {/* Manual trade form */}
        <ManualTradeForm />
      </div>

      {/* Confirm live autonomous modal */}
      {liveConfirmModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-gray-900 border border-red-700 rounded-xl p-6 max-w-sm w-full mx-4">
            <div className="flex items-center gap-2 text-red-400 font-bold mb-3">
              <AlertTriangle size={18} /> Enable Auto Pilot in Live Mode?
            </div>
            <p className="text-sm text-gray-300 mb-4">
              This will allow BlackBoxTrader to autonomously submit orders using your
              <strong> real Alpaca account</strong>. Real money will be at risk.
              Type <strong>CONFIRM</strong> to proceed.
            </p>
            <input
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mb-4 focus:outline-none focus:border-red-500"
              placeholder="Type CONFIRM"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
            />
            <div className="flex gap-3">
              <button onClick={() => { setLiveConfirmModal(false); setConfirmText('') }}
                className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm">Cancel</button>
              <button
                disabled={confirmText !== 'CONFIRM' || toggle.isPending}
                onClick={() => toggle.mutate({ enabled: true, confirm: true })}
                className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 rounded text-sm font-medium disabled:opacity-50"
              >Enable</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}


// ── Manual trade form ─────────────────────────────────────────────────────────

function ManualTradeForm() {
  const [ticker, setTicker]   = useState('')
  const [side, setSide]       = useState<'buy' | 'sell'>('buy')
  const [qty, setQty]         = useState('')
  const [status, setStatus]   = useState<string | null>(null)

  async function submit() {
    if (!ticker || !qty) return
    try {
      const res = await fetch('/api/v1/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker: ticker.toUpperCase(), side, qty: parseFloat(qty), source: 'manual' }),
      })
      const data = await res.json()
      setStatus(res.ok ? `✓ Order submitted: ${data.action ?? 'ok'}` : `✗ ${data.detail}`)
      if (res.ok) { setTicker(''); setQty('') }
    } catch (e) {
      setStatus(`✗ Network error`)
    }
    setTimeout(() => setStatus(null), 4000)
  }

  return (
    <div>
      <div className="text-xs font-medium text-gray-400 mb-2">Place a manual order</div>
      <div className="flex gap-2 flex-wrap">
        <input
          className="flex-1 min-w-24 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm uppercase focus:outline-none focus:border-blue-500"
          placeholder="Ticker"
          value={ticker}
          onChange={e => setTicker(e.target.value.toUpperCase())}
        />
        <select
          value={side}
          onChange={e => setSide(e.target.value as 'buy' | 'sell')}
          className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="buy">BUY</option>
          <option value="sell">SELL</option>
        </select>
        <input
          type="number" min="1"
          className="w-20 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
          placeholder="Qty"
          value={qty}
          onChange={e => setQty(e.target.value)}
        />
        <button
          onClick={submit}
          disabled={!ticker || !qty}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium disabled:opacity-50"
        >
          Submit
        </button>
      </div>
      {status && <div className="text-xs mt-2 text-gray-300">{status}</div>}
    </div>
  )
}
