import api from './client'
import type { TradingMode } from '../types'

export const getTradingMode = () =>
  api.get<TradingMode>('/settings/mode').then((r) => r.data)

export const setTradingMode = (mode: 'paper' | 'live', confirm: boolean, enableExecution: boolean) =>
  api.post('/settings/mode', { mode, confirm, enable_execution: enableExecution }).then((r) => r.data)

export const getRiskSettings = () =>
  api.get('/settings/risk').then((r) => r.data)

export const updateRiskSettings = (data: Record<string, number>) =>
  api.post('/settings/risk', data).then((r) => r.data)

export const getWatchlist = () =>
  api.get<Array<{ ticker: string; asset_type: string }>>('/watchlist').then((r) => r.data)

export const addToWatchlist = (ticker: string) =>
  api.post('/watchlist', { ticker }).then((r) => r.data)

export const removeFromWatchlist = (ticker: string) =>
  api.delete(`/watchlist/${ticker}`).then((r) => r.data)

export const setAutonomousMode = (enabled: boolean, confirm = false) =>
  api.post('/settings/autonomous', { enabled, confirm }).then((r) => r.data)

export interface BreakerStatus {
  halted: boolean
  reason: 'daily_loss' | 'drawdown' | 'market_crash' | 'manual' | null
  detail: string | null
  tripped_at: string | null
  peak_equity: number
  day_start_equity: number
  flatten_on_halt: boolean
}

export const getBreakerStatus = () =>
  api.get<BreakerStatus>('/settings/risk/breaker').then((r) => r.data)

export const killSwitch = () =>
  api.post('/settings/risk/kill').then((r) => r.data)

export const resumeTrading = () =>
  api.post('/settings/risk/resume').then((r) => r.data)
