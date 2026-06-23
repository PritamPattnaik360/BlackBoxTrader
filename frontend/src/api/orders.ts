import api from './client'
import type { Order } from '../types'

export const getOrders = (limit = 100) =>
  api.get<Order[]>(`/orders?limit=${limit}`).then((r) => r.data)

export const placeOrder = (order: {
  ticker: string
  side: string
  qty: number
  order_type?: string
}) => api.post('/orders', order).then((r) => r.data)

export const cancelOrder = (id: string) =>
  api.delete(`/orders/${id}`).then((r) => r.data)
