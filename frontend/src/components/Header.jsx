import { useAuth } from '../context/AuthContext'

export default function Header({ onMenuToggle }) {
  const { employee, logout } = useAuth()

  const displayName = employee?.full_name || employee?.email || 'User'
  const displayEmail = employee?.email || ''
  const initial = displayName.charAt(0).toUpperCase()

  return (
    <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-5 shrink-0 z-10">
      {/* Left: hamburger + title */}
      <div className="flex items-center gap-3">
        <button
          onClick={onMenuToggle}
          className="lg:hidden p-2 rounded-md text-slate-500 hover:bg-slate-100 transition-colors"
          aria-label="Toggle sidebar"
        >
          <span className="block w-5 h-0.5 bg-current mb-1" />
          <span className="block w-5 h-0.5 bg-current mb-1" />
          <span className="block w-5 h-0.5 bg-current" />
        </button>
        <span className="text-base font-semibold text-slate-700 hidden sm:block">
          Espial Article Publishing
        </span>
      </div>

      {/* Right: user info + logout */}
      <div className="flex items-center gap-3">
        <div className="text-right hidden sm:block">
          <p className="text-sm font-medium text-slate-700 leading-tight">{displayName}</p>
          <p className="text-xs text-slate-400 leading-tight">{displayEmail}</p>
        </div>
        <div className="w-9 h-9 rounded-full bg-indigo-600 flex items-center justify-center text-white text-sm font-bold select-none">
          {initial}
        </div>
        <button
          onClick={logout}
          className="text-xs text-slate-500 hover:text-red-600 font-medium transition-colors px-2 py-1 rounded hover:bg-red-50"
          title="Sign out"
        >
          Logout
        </button>
      </div>
    </header>
  )
}
