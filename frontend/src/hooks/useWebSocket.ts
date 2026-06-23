import { useEffect, useRef } from 'react'
import { useTradingStore } from '../store/tradingStore'
import type { LivePrice } from '../types'

export function useWebSocket() {
  const ws = useRef<WebSocket | null>(null)
  const setPrice = useTradingStore((s) => s.setPrice)
  const setConnected = useTradingStore((s) => s.setWsConnected)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>()

  const connect = () => {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    ws.current = new WebSocket(`${protocol}://${window.location.host}/ws/live`)

    ws.current.onopen = () => setConnected(true)
    ws.current.onclose = () => {
      setConnected(false)
      reconnectTimer.current = setTimeout(connect, 3000)
    }
    ws.current.onerror = () => ws.current?.close()
    ws.current.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.type === 'ping') return
        if (data.ticker && data.close != null) {
          setPrice(data as LivePrice)
        }
      } catch {}
    }
  }

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      ws.current?.close()
    }
  }, [])
}
