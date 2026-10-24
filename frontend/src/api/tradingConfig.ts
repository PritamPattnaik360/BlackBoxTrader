import axios from 'axios'

const api = axios.create({ baseURL: '/api/v1' })

export interface ConfigField {
  key: string
  label: string
  type: 'bool' | 'float' | 'int' | 'time'
  help: string
  value: boolean | number | string
  default: boolean | number | string | null
  customized: boolean
  min: number | string | null
  max: number | string | null
  step: number | null
  pct: boolean
  danger: boolean
  requires_confirm: boolean
  restart: boolean
}

export interface ConfigGroup {
  id: string
  label: string
  fields: ConfigField[]
}

export interface TradingConfig {
  groups: ConfigGroup[]
  trading_mode: 'paper' | 'live'
}

export type ConfigValue = boolean | number | string

/** Turn an axios error from the config endpoints into { field: message } plus a general message. */
export function configErrors(err: any): { fields: Record<string, string>; general: string | null } {
  const detail = err?.response?.data?.detail
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) return { fields: detail, general: null }
  return { fields: {}, general: typeof detail === 'string' ? detail : err?.message ?? 'Could not save' }
}

export const getTradingConfig = () => api.get<TradingConfig>('/trading-config').then((r) => r.data)
export const saveTradingConfig = (values: Record<string, ConfigValue>, confirm = false) =>
  api.put<TradingConfig & { changed: Record<string, { from: unknown; to: unknown }> }>('/trading-config', { values, confirm }).then((r) => r.data)
export const resetTradingConfig = (keys?: string[]) =>
  api.post<TradingConfig>('/trading-config/reset', { keys: keys ?? null }).then((r) => r.data)

export interface TradingProfile { name: string; saved_at: string | null; values: Record<string, ConfigValue> }
export const getProfiles = () => api.get<{ profiles: TradingProfile[] }>('/trading-config/profiles').then((r) => r.data.profiles)
export const saveProfile = (name: string) =>
  api.post<{ profiles: TradingProfile[] }>('/trading-config/profiles', { name }).then((r) => r.data.profiles)
export const applyProfile = (name: string) =>
  api.post<TradingConfig>(`/trading-config/profiles/${encodeURIComponent(name)}/apply`).then((r) => r.data)
export const deleteProfile = (name: string) =>
  api.delete<{ profiles: TradingProfile[] }>(`/trading-config/profiles/${encodeURIComponent(name)}`).then((r) => r.data.profiles)
