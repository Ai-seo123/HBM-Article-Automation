import { NavLink } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function Sidebar({ open, onClose }) {
  const { isAdmin } = useAuth()

  const navItems = [
    { label: 'Workflow', to: '/', icon: '▦', exact: true },
    { label: 'Reports', to: '/reports', icon: '📊', exact: true },
    ...(isAdmin ? [{ label: 'Activity Logs', to: '/admin/activity', icon: '🛡️', exact: true }] : []),
    { label: 'Settings', to: '/settings', icon: '⚙️', exact: true },
  ]
  return (
    <>
      {/* Mobile backdrop */}
      {open && (
        <div
          className="fixed inset-0 bg-black/40 z-20 lg:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar panel */}
      <aside
        className={[
          'fixed top-0 left-0 h-full w-64 bg-slate-900 text-white z-30 flex flex-col transition-transform duration-300 ease-in-out',
          'lg:static lg:translate-x-0 lg:z-auto',
          open ? 'translate-x-0' : '-translate-x-full',
        ].join(' ')}
      >
        {/* Brand */}
        <div className="px-5 py-5 border-b border-slate-700 flex items-center gap-3">
          <span className="text-indigo-400 text-2xl font-bold leading-none">E</span>
          <div>
            <p className="text-sm font-semibold leading-tight text-white">Espial Article</p>
            <p className="text-xs text-slate-400 leading-tight">Publishing</p>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto py-4 px-3">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider px-2 mb-2">
            Main Menu
          </p>
          <ul className="space-y-0.5">
            {navItems.map(({ label, to, icon, exact }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={exact}
                  onClick={onClose}
                  className={({ isActive }) =>
                    [
                      'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                      isActive
                        ? 'bg-indigo-600 text-white'
                        : 'text-slate-300 hover:bg-slate-800 hover:text-white',
                    ].join(' ')
                  }
                >
                  <span className="text-base leading-none w-5 text-center">{icon}</span>
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-slate-700">
          <p className="text-xs text-slate-500">v1.1.0 — Espial</p>
        </div>
      </aside>
    </>
  )
}
