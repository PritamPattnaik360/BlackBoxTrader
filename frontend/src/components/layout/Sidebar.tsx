import { NavLink } from 'react-router-dom'
import { LayoutDashboard, TrendingUp, BookOpen, Zap, FlaskConical, Settings } from 'lucide-react'

const links = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/portfolio', label: 'Portfolio', icon: TrendingUp },
  { to: '/orders', label: 'Orders', icon: BookOpen },
  { to: '/signals', label: 'Signals', icon: Zap },
  { to: '/backtest', label: 'Backtest', icon: FlaskConical },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export default function Sidebar() {
  return (
    <aside className="w-56 bg-gray-900 border-r border-gray-800 flex flex-col">
      <div className="px-5 py-4 border-b border-gray-800">
        <span className="text-lg font-bold tracking-tight text-white">BlackBox<span className="text-blue-400">Trader</span></span>
      </div>
      <nav className="flex-1 py-4 space-y-1 px-2">
        {links.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                isActive
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-400 hover:bg-gray-800 hover:text-white'
              }`
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="px-5 py-3 border-t border-gray-800 text-xs text-gray-500">v0.1.0</div>
    </aside>
  )
}
