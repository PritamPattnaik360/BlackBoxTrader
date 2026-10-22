import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ShieldAlert, ShieldCheck } from 'lucide-react'
import { getBreakerStatus, killSwitch, resumeTrading } from '../../api/settings'

const REASONS: Record<string, string> = {
  daily_loss: 'Daily loss limit hit',
  drawdown: 'Max drawdown from peak hit',
  market_crash: 'Market crash (SPY sell-off)',
  manual: 'Kill switch pressed',
}

export default function CircuitBreakerPanel() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['breaker'], queryFn: getBreakerStatus, refetchInterval: 15_000 })
  const [confirmKill, setConfirmKill] = useState(false)

  const refresh = () => qc.invalidateQueries({ queryKey: ['breaker'] })
  const kill = useMutation({ mutationFn: killSwitch, onSuccess: () => { setConfirmKill(false); refresh() } })
  const resume = useMutation({ mutationFn: resumeTrading, onSuccess: refresh })

  if (!data) return null
  const halted = data.halted

  return (
    <div className={`rounded-xl border p-5 ${halted ? 'bg-red-950/40 border-red-800' : 'bg-gray-900 border-gray-800'}`}>
      <div className="flex items-center gap-2 text-sm font-medium mb-1">
        {halted ? <ShieldAlert size={16} className="text-red-400" /> : <ShieldCheck size={16} className="text-green-400" />}
        Circuit Breaker — {halted ? <span className="text-red-400">TRIPPED</span> : <span className="text-green-400">armed</span>}
      </div>
      <p className="text-xs text-gray-500 mb-3">
        Stops all new trades{data.flatten_on_halt ? ' and sells every open position' : ''} if the account hits the daily loss or
        max drawdown limit, or SPY crashes on the day. Any single position past its hard-stop loss is also closed automatically.
        Daily-loss and crash halts reset the next trading day; drawdown and kill-switch halts stay until you resume.
      </p>

      {halted && (
        <div className="text-xs text-red-300 mb-3">
          {REASONS[data.reason ?? ''] ?? data.reason}: {data.detail}
          {data.tripped_at && <span className="text-gray-500"> ({new Date(data.tripped_at).toLocaleString()})</span>}
        </div>
      )}

      <div className="flex gap-2">
        {halted ? (
          <button onClick={() => resume.mutate()} disabled={resume.isPending}
            className="px-4 py-2 bg-green-700 hover:bg-green-600 rounded text-sm">
            Resume Trading
          </button>
        ) : confirmKill ? (
          <>
            <button onClick={() => kill.mutate()} disabled={kill.isPending}
              className="px-4 py-2 bg-red-700 hover:bg-red-600 rounded text-sm">
              Confirm: halt{data.flatten_on_halt ? ' & sell everything' : ''}
            </button>
            <button onClick={() => setConfirmKill(false)} className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm">
              Cancel
            </button>
          </>
        ) : (
          <button onClick={() => setConfirmKill(true)} className="px-4 py-2 bg-red-800 hover:bg-red-700 rounded text-sm">
            Kill Switch
          </button>
        )}
      </div>
    </div>
  )
}
