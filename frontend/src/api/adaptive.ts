import axios from 'axios'

const api = axios.create({ baseURL: '/api/v1' })

export interface AdaptiveParam {
  name: string
  current: number
  default: number
  delta: number
  generation: number
}

export interface AdaptiveParamsResponse {
  params: AdaptiveParam[]
  regime: string
  generation: number
}

export interface PerformanceStats {
  total_outcomes: number
  win_rate: number | null
  buy_accuracy: number | null
  sell_accuracy: number | null
  recent_sharpe: number
  avg_pnl_pct: number
  current_regime: string
}

export interface AdaptiveEvent {
  id: number
  event_type: string
  description: string
  data: Record<string, unknown> | null
  created_at: string
}

export interface HistoryEntry {
  generation: number
  created_at: string
  buy_signal_threshold?: number
  sell_signal_threshold?: number
  news_weight?: number
  risk_per_trade_pct?: number
  atr_stop_multiplier?: number
}

export const getAdaptiveParams  = () => api.get<AdaptiveParamsResponse>('/adaptive/params').then(r => r.data)
export const getAdaptiveHistory  = () => api.get<HistoryEntry[]>('/adaptive/history').then(r => r.data)
export const getAdaptivePerf     = () => api.get<PerformanceStats>('/adaptive/performance').then(r => r.data)
export const getAdaptiveEvents   = () => api.get<AdaptiveEvent[]>('/adaptive/events').then(r => r.data)
export const triggerOptimize     = () => api.post('/adaptive/optimize').then(r => r.data)
export const resetAdaptiveParams = () => api.post('/adaptive/reset').then(r => r.data)
