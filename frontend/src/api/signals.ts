import api from './client'
import type { Signal } from '../types'

export const getSignals = (limit = 50) =>
  api.get<Signal[]>(`/signals?limit=${limit}`).then((r) => r.data)

export const triggerScan = () =>
  api.post('/signals/scan').then((r) => r.data)
