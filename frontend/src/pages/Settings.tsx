import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getTradingMode, setTradingMode, getRiskSettings, updateRiskSettings, getWatchlist, addToWatchlist, removeFromWatchlist } from '../api/settings'
import { useState } from 'react'
import { Plus, Trash2, AlertTriangle, Info } from 'lucide-react'
import AdaptivePanel from '../components/adaptive/AdaptivePanel'
import AutoTradeStatus from '../components/autonomous/AutoTradeStatus'
import CircuitBreakerPanel from '../components/autonomous/CircuitBreakerPanel'
import LlmStatusPanel from '../components/advisor/LlmStatusPanel'

function ExplainBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-3 bg-blue-950/30 border border-blue-900/50 rounded-xl px-4 py-3 text-xs text-gray-400 leading-relaxed">
      <Info size={14} className="text-blue-400 flex-shrink-0 mt-0.5" />
      <div>{children}</div>
    </div>
  )
}

export default function Settings() {
  const qc = useQueryClient()
  const { data: mode } = useQuery({ queryKey: ['tradingMode'], queryFn: getTradingMode })
  const { data: risk } = useQuery({ queryKey: ['riskSettings'], queryFn: getRiskSettings })
  const { data: watchlist } = useQuery({ queryKey: ['watchlist'], queryFn: getWatchlist })

  const [confirmModal, setConfirmModal] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [newTicker, setNewTicker] = useState('')
  const [riskForm, setRiskForm] = useState<Record<string, string>>({})

  const switchMode = useMutation({
    mutationFn: ({ m, confirm, exec }: { m: 'paper' | 'live'; confirm: boolean; exec: boolean }) =>
      setTradingMode(m, confirm, exec),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['tradingMode'] }); setConfirmModal(false); setConfirmText('') },
  })

  const updateRisk = useMutation({
    mutationFn: updateRiskSettings,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['riskSettings'] }),
  })

  const addTicker = useMutation({
    mutationFn: addToWatchlist,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['watchlist'] }); setNewTicker('') },
  })

  const removeTicker = useMutation({
    mutationFn: removeFromWatchlist,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist'] }),
  })

  const isLive = mode?.trading_mode === 'live'

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-xl font-semibold mb-3">Settings</h1>
        <ExplainBox>
          Control how the bot behaves. <strong className="text-gray-300">Autopilot</strong> is the on/off switch for autonomous trading — turn it on and the bot will automatically open and close day trades based on its signals.
          {mode?.auto_start_autonomous
            ? ' Autopilot is set to resume automatically after a restart (AUTO_START_AUTONOMOUS=true).'
            : ' It resets to OFF every time the backend restarts, so re-enable it after each restart (or set AUTO_START_AUTONOMOUS=true in backend/.env).'}
          <strong className="text-gray-300"> Watchlist</strong> lists the stocks always scanned; the bot also scans the best S&amp;P 500 / growth-stock picks each cycle.
          <strong className="text-gray-300"> Risk Parameters</strong> set position sizing and kill-switch thresholds.
          <strong className="text-gray-300"> Paper mode</strong> (default) uses fake money via Alpaca's paper trading sandbox — safe to experiment with.
        </ExplainBox>
      </div>

      {/* Autonomous trading — primary feature */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
        <div className="text-sm font-medium mb-1">Auto Pilot</div>
        <p className="text-xs text-gray-500 mb-4">
          When ON, the bot places orders automatically whenever a signal clears the current (adaptive) BUY threshold. Scans run every 5 min and orders are only placed during NYSE hours.
          {mode?.day_trade_only !== false && ' Day-trade-only mode is on: every position is closed by 15:50 ET.'}
          {mode?.auto_start_autonomous
            ? <span className="text-green-500 ml-1">Resumes automatically after a backend restart.</span>
            : <span className="text-yellow-500 ml-1">⚠ Resets to OFF on every backend restart — re-enable after restarting.</span>}
        </p>
        <AutoTradeStatus />
      </div>

      {/* Trading Mode */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
        <div className="text-sm font-medium mb-4">Trading Mode</div>
        <div className={`flex items-center justify-between p-4 rounded-lg border ${isLive ? 'border-red-700 bg-red-900/20' : 'border-green-700 bg-green-900/20'}`}>
          <div>
            <div className={`font-bold ${isLive ? 'text-red-300' : 'text-green-300'}`}>
              {isLive ? '⚠ LIVE TRADING — Real Money' : '✓ PAPER TRADING — Fake Money'}
            </div>
            <div className="text-xs text-gray-400 mt-1">{mode?.alpaca_base_url ?? '—'}</div>
          </div>
          <button
            onClick={() => {
              if (!isLive) setConfirmModal(true)
              else switchMode.mutate({ m: 'paper', confirm: false, exec: false })
            }}
            className={`px-4 py-2 rounded text-sm font-medium ${isLive ? 'bg-green-600 hover:bg-green-700' : 'bg-red-600 hover:bg-red-700'}`}
          >
            Switch to {isLive ? 'Paper' : 'Live'}
          </button>
        </div>
        <div className="mt-3 text-xs text-gray-500">
          Auto-execution is {mode?.execution_live ? <span className="text-green-400">ENABLED</span> : <span className="text-gray-400">disabled (dry-run)</span>}.
          {mode?.execution_live
            ? ' Orders are being submitted to Alpaca.'
            : ' Enable Auto Pilot above to start submitting paper orders automatically.'}
        </div>
      </div>

      {/* Confirm live mode modal */}
      {confirmModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-gray-900 border border-red-700 rounded-xl p-6 max-w-sm w-full mx-4">
            <div className="flex items-center gap-2 text-red-400 font-bold mb-3">
              <AlertTriangle size={18} /> Enable Live Trading?
            </div>
            <p className="text-sm text-gray-300 mb-4">
              This will switch to your <strong>real Alpaca brokerage account</strong>. All orders will use real money. Type <strong>CONFIRM</strong> to proceed.
            </p>
            <input
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm mb-4 focus:outline-none focus:border-red-500"
              placeholder="Type CONFIRM"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
            />
            <div className="flex gap-3">
              <button onClick={() => { setConfirmModal(false); setConfirmText('') }} className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm">Cancel</button>
              <button
                disabled={confirmText !== 'CONFIRM' || switchMode.isPending}
                onClick={() => switchMode.mutate({ m: 'live', confirm: true, exec: true })}
                className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 rounded text-sm font-medium disabled:opacity-50"
              >
                Enable Live
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Watchlist */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
        <div className="text-sm font-medium mb-1">Watchlist</div>
        <p className="text-xs text-gray-500 mb-4">
          Tickers always scanned every 5 minutes, in addition to the S&amp;P 500 / growth-stock picks the bot screens each cycle. Add any NYSE/NASDAQ stock. These are also the tickers streamed for live prices.
        </p>
        <div className="flex gap-2 mb-3">
          <input
            className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm uppercase focus:outline-none focus:border-blue-500"
            placeholder="Add ticker (e.g. TSLA)"
            value={newTicker}
            onChange={(e) => setNewTicker(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === 'Enter' && newTicker && addTicker.mutate(newTicker)}
          />
          <button
            onClick={() => newTicker && addTicker.mutate(newTicker)}
            className="px-3 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm"
          >
            <Plus size={16} />
          </button>
        </div>
        <div className="space-y-1">
          {(watchlist ?? []).map((w) => (
            <div key={w.ticker} className="flex items-center justify-between px-3 py-2 bg-gray-800 rounded">
              <span className="font-medium text-sm">{w.ticker}</span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500">{w.asset_type}</span>
                <button onClick={() => removeTicker.mutate(w.ticker)} className="text-gray-500 hover:text-red-400">
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          ))}
          {(!watchlist || watchlist.length === 0) && <div className="text-sm text-gray-500 py-2">No tickers in watchlist</div>}
        </div>
      </div>

      {/* Local LLM signal */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
        <LlmStatusPanel />
      </div>

      {/* Adaptive learning */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
        <AdaptivePanel />
      </div>

      <CircuitBreakerPanel />

      {/* Risk settings */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
        <div className="text-sm font-medium mb-1">Risk Parameters</div>
        <p className="text-xs text-gray-500 mb-4">
          Position size = (equity × risk_per_trade_pct × market-bias multiplier) ÷ stop distance, where the stop is an ATR multiple (day trades use a tight ~0.6 ATR stop). The halt percentages and max-loss percentages below drive the Circuit Breaker above (0.05 = 5%).
        </p>
        <div className="grid grid-cols-2 gap-4">
          {risk && Object.entries(risk).map(([key, value]) => (
            <div key={key}>
              <label className="text-xs text-gray-500 block mb-1">{key.replace(/_/g, ' ')}</label>
              <input
                type="number" step="0.001"
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
                defaultValue={String(value)}
                onChange={(e) => setRiskForm(f => ({ ...f, [key]: e.target.value }))}
              />
            </div>
          ))}
        </div>
        <button
          onClick={() => updateRisk.mutate(Object.fromEntries(Object.entries(riskForm).map(([k, v]) => [k, parseFloat(v)])))}
          className="mt-4 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm"
          disabled={Object.keys(riskForm).length === 0}
        >
          Save Risk Settings
        </button>
      </div>
    </div>
  )
}
