import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getOrders, placeOrder, cancelOrder } from '../api/orders'
import dayjs from 'dayjs'
import { useState } from 'react'
import { X } from 'lucide-react'

export default function Orders() {
  const qc = useQueryClient()
  const { data: orders } = useQuery({ queryKey: ['orders', 100], queryFn: () => getOrders(100), refetchInterval: 15000 })
  const cancel = useMutation({ mutationFn: cancelOrder, onSuccess: () => qc.invalidateQueries({ queryKey: ['orders'] }) })
  const place = useMutation({ mutationFn: placeOrder, onSuccess: () => qc.invalidateQueries({ queryKey: ['orders'] }) })

  const [form, setForm] = useState({ ticker: '', side: 'buy', qty: '' })

  const handlePlace = (e: React.FormEvent) => {
    e.preventDefault()
    place.mutate({ ticker: form.ticker.toUpperCase(), side: form.side, qty: parseFloat(form.qty) })
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Orders</h1>

      {/* Manual order form */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
        <div className="text-sm font-medium mb-3">Manual Order</div>
        <form onSubmit={handlePlace} className="flex items-end gap-3">
          <div>
            <label className="text-xs text-gray-500 block mb-1">Ticker</label>
            <input
              className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm w-24 uppercase focus:outline-none focus:border-blue-500"
              value={form.ticker} onChange={(e) => setForm(f => ({ ...f, ticker: e.target.value }))}
              placeholder="AAPL" required
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Side</label>
            <select
              className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
              value={form.side} onChange={(e) => setForm(f => ({ ...f, side: e.target.value }))}
            >
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Shares</label>
            <input
              type="number" min="1" step="1"
              className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm w-24 focus:outline-none focus:border-blue-500"
              value={form.qty} onChange={(e) => setForm(f => ({ ...f, qty: e.target.value }))}
              placeholder="10" required
            />
          </div>
          <button
            type="submit"
            disabled={place.isPending}
            className={`px-4 py-2 rounded text-sm font-medium ${form.side === 'buy' ? 'bg-green-600 hover:bg-green-700' : 'bg-red-600 hover:bg-red-700'} disabled:opacity-50`}
          >
            {place.isPending ? 'Placing...' : `Place ${form.side.toUpperCase()}`}
          </button>
        </form>
        {place.isError && <div className="mt-2 text-xs text-red-400">Failed to place order</div>}
        {place.isSuccess && <div className="mt-2 text-xs text-green-400">Order submitted</div>}
      </div>

      {/* Order table */}
      <div className="bg-gray-900 rounded-xl border border-gray-800">
        <div className="px-4 py-3 border-b border-gray-800 text-sm font-medium">Order History</div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 border-b border-gray-800">
                <th className="px-4 py-2 text-left">Ticker</th>
                <th className="px-4 py-2 text-left">Side</th>
                <th className="px-4 py-2 text-right">Qty</th>
                <th className="px-4 py-2 text-left">Type</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-right">Fill Price</th>
                <th className="px-4 py-2 text-left">Submitted</th>
                <th className="px-4 py-2 text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {(orders ?? []).map((o) => (
                <tr key={o.id} className="hover:bg-gray-800/40">
                  <td className="px-4 py-3 font-medium">{o.ticker}</td>
                  <td className={`px-4 py-3 font-medium ${o.side === 'buy' ? 'text-green-400' : 'text-red-400'}`}>{o.side.toUpperCase()}</td>
                  <td className="px-4 py-3 text-right">{o.qty}</td>
                  <td className="px-4 py-3 text-gray-400">{o.order_type}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-xs ${
                      o.status === 'filled' ? 'bg-green-900 text-green-300' :
                      o.status === 'cancelled' ? 'bg-gray-800 text-gray-400' :
                      o.status === 'pending_new' || o.status === 'new' ? 'bg-yellow-900 text-yellow-300' :
                      'bg-blue-900 text-blue-300'
                    }`}>{o.status}</span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono">{o.filled_avg_price ? `$${o.filled_avg_price.toFixed(2)}` : '—'}</td>
                  <td className="px-4 py-3 text-gray-400">{dayjs(o.submitted_at).format('MM/DD HH:mm')}</td>
                  <td className="px-4 py-3 text-center">
                    {(o.status === 'new' || o.status === 'pending_new' || o.status === 'accepted') && o.alpaca_order_id && (
                      <button
                        onClick={() => cancel.mutate(o.alpaca_order_id!)}
                        className="text-gray-400 hover:text-red-400"
                      >
                        <X size={14} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {(!orders || orders.length === 0) && (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-500">No orders yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
