import { create } from 'zustand'
import type { LivePrice, TradingMode } from '../types'

interface TradingStore {
  prices: Record<string, LivePrice>
  wsConnected: boolean
  tradingMode: TradingMode | null
  setPrice: (price: LivePrice) => void
  setWsConnected: (v: boolean) => void
  setTradingMode: (mode: TradingMode) => void
}

export const useTradingStore = create<TradingStore>((set) => ({
  prices: {},
  wsConnected: false,
  tradingMode: null,
  setPrice: (price) =>
    set((state) => ({ prices: { ...state.prices, [price.ticker]: price } })),
  setWsConnected: (wsConnected) => set({ wsConnected }),
  setTradingMode: (tradingMode) => set({ tradingMode }),
}))
