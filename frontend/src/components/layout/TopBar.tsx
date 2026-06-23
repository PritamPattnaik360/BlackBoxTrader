import { useQuery } from '@tanstack/react-query'
import { getTradingMode } from '../../api/settings'
import { useTradingStore } from '../../store/tradingStore'
import { Wifi, WifiOff, Bot } from 'lucide-react'

export default function TopBar() {
  const wsConnected = useTradingStore((s) => s.wsConnected)
  const { data: mode } = useQuery({ queryKey: ['tradingMode'], queryFn: getTradingMode, refetchInterval: 10_000 })

  const isLive      = mode?.trading_mode === 'live'
  const isAuto      = mode?.autonomous   ?? false

  return (
    <header className="h-12 bg-gray-900 border-b border-gray-800 flex items-center px-6 gap-3">

      {/* Live trading banner */}
      {isLive && (
        <div className="flex items-center gap-2 bg-red-900/60 border border-red-500 text-red-300 text-xs font-bold px-3 py-1 rounded-full animate-pulse">
          ⚠ LIVE TRADING — REAL MONEY
        </div>
      )}

      {/* Autonomous pilot badge */}
      {isAuto && (
        <div className={`flex items-center gap-1.5 text-xs font-bold px-3 py-1 rounded-full animate-pulse
          ${isLive
            ? 'bg-red-900/80 border border-red-400 text-red-300'
            : 'bg-blue-900/60 border border-blue-500 text-blue-300'}`}>
          <Bot size={11} />
          AUTO PILOT{isLive ? ' • LIVE' : ' • PAPER'}
        </div>
      )}

      {/* Paper mode badge (only when not live and not auto) */}
      {!isLive && !isAuto && mode && (
        <div className="flex items-center gap-2 bg-green-900/30 border border-green-700 text-green-400 text-xs px-3 py-1 rounded-full">
          PAPER MODE
        </div>
      )}

      {/* Paper mode label when auto is off */}
      {!isLive && !isAuto && !mode && null}

      <div className="ml-auto flex items-center gap-2 text-xs text-gray-400">
        {wsConnected ? (
          <><Wifi size={14} className="text-green-400" /> Live</>
        ) : (
          <><WifiOff size={14} className="text-red-400" /> Offline</>
        )}
      </div>
    </header>
  )
}
