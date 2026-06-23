import api from './client'
import type { Account, Position } from '../types'

export const getPortfolio = () =>
  api.get<{ account: Account; positions: Position[] }>('/portfolio').then((r) => r.data)

export const getPortfolioHistory = () =>
  api.get<Array<{ ts: string; equity: number; day_pnl: number; day_pnl_pct: number }>>('/portfolio/history').then((r) => r.data)
