import api from './client'
import type { BacktestRun } from '../types'

export const submitBacktest = (req: {
  tickers: string[]
  start_date: string
  end_date: string
  initial_capital?: number
  strategy_name?: string
}) => api.post<{ run_id: number; status: string }>('/backtest', req).then((r) => r.data)

export const getBacktestResult = (runId: number) =>
  api.get<BacktestRun>(`/backtest/${runId}`).then((r) => r.data)
