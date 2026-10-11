import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Briefcase,
  ChevronDown,
  LayoutDashboard,
  Lightbulb,
  LogOut,
  MessageSquare,
  Newspaper,
  Server,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  User,
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import Disclaimer from './Disclaimer'
import NotificationBell from './NotificationBell'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/portfolio', label: 'Portfolio', icon: Briefcase },
  { to: '/insights', label: 'AI Insights', icon: Lightbulb },
  { to: '/news', label: 'Market News', icon: Newspaper },
  { to: '/assistant', label: 'AI Assistant', icon: MessageSquare },
  { to: '/opportunities', label: 'Opportunities', icon: Sparkles },
  { to: '/security', label: 'Security Center', icon: ShieldCheck },
  { to: '/system', label: 'System Check', icon: Server },
  { to: '/profile', label: 'Profile', icon: User },
]

const EXTRA_TITLES = { '/notifications': 'Notifications' }

function navClass({ isActive }) {
  const base = 'flex items-center justify-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors lg:justify-start'
  return isActive
    ? `${base} bg-indigo-50 text-indigo-700`
    : `${base} text-slate-600 hover:bg-slate-100 hover:text-slate-900`
}

function pageTitle(pathname) {
  const match = NAV_ITEMS.find((item) => item.to === pathname)
  return match ? match.label : EXTRA_TITLES[pathname] || 'Investment Copilot'
}

function UserMenu() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const containerRef = useRef(null)

  useEffect(() => {
    function handleClick(event) {
      if (containerRef.current && !containerRef.current.contains(event.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  async function handleLogout() {
    setOpen(false)
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex items-center gap-2 rounded-xl px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-indigo-100 text-xs font-semibold uppercase text-indigo-700">
          {user?.email?.charAt(0)}
        </span>
        <span className="hidden max-w-48 truncate md:inline">{user?.email}</span>
        <ChevronDown size={16} />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-2 w-56 rounded-xl border border-slate-200 bg-white p-1 shadow-lg"
        >
          <p className="truncate px-3 py-2 text-xs text-slate-500">{user?.email}</p>
          <button
            type="button"
            role="menuitem"
            onClick={handleLogout}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"
          >
            <LogOut size={16} />
            Log out
          </button>
        </div>
      )}
    </div>
  )
}

export default function Layout() {
  const { pathname } = useLocation()

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-16 shrink-0 flex-col border-r border-slate-200 bg-white p-3 lg:w-60 lg:p-4">
        <div className="mb-6 flex items-center justify-center gap-2 lg:justify-start lg:px-2">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white">
            <TrendingUp size={20} />
          </div>
          <span className="hidden text-lg font-semibold lg:inline">Investment Copilot</span>
        </div>

        <nav className="flex flex-1 flex-col gap-1 overflow-y-auto">
          {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={navClass} title={label}>
              <Icon size={18} className="shrink-0" />
              <span className="hidden lg:inline">{label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur sm:px-6 lg:px-8">
          <h2 className="truncate text-lg font-semibold text-slate-900">{pageTitle(pathname)}</h2>
          <div className="flex items-center gap-2">
            <NotificationBell />
            <UserMenu />
          </div>
        </header>

        <main className="flex-1 p-4 sm:p-6 lg:p-8">
          <Outlet />
        </main>

        <footer className="border-t border-slate-200 px-4 py-4 text-center sm:px-6 lg:px-8">
          <Disclaimer />
        </footer>
      </div>
    </div>
  )
}
