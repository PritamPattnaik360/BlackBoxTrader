import axios from 'axios'

const api = axios.create({ baseURL: '/api/v1' })

export interface StrategyContext {
  context: {
    bias: 'bull' | 'neutral' | 'bear'
    score: number
    vix: number | null
    spy_price: number | null
    spy_vs_200dma_pct: number | null
    spy_vs_50dma_pct: number | null
    ret_20d_pct?: number
    ma50_above_ma200: boolean | null
    reason: string
  }
  profile: {
    name: string
    label: string
    description: string
    daily_weights: Record<string, number>
    intraday_weights: Record<string, number>
    buy_threshold_adj: number
    sell_threshold_adj: number
    size_multiplier: number
    stop_multiplier_adj: number
  }
  universe: {
    size: number | null
    swing: string[]
    day: string[]
    details: Record<string, { price: number; rs_63d: number; rsi: number; atr_pct: number; vol_surge: number; pct_from_high: number; above_ma50: boolean }>
    screened_for_bias: string | null
  }
}

export const getStrategyContext = () => api.get<StrategyContext>('/strategy/context').then(r => r.data)
export const refreshStrategy    = () => api.post<StrategyContext>('/strategy/refresh').then(r => r.data)
