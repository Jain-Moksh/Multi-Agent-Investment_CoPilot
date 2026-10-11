import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Briefcase,
  ChevronDown,
  LayoutDashboard,
  Lightbulb,
  LogOut,
  MessageSquare,
  Moon,
  Newspaper,
  Server,
  ShieldCheck,
  Sparkles,
  Sun,
  TrendingUp,
  User,
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useTheme } from '../context/ThemeContext'
import { isSuperAdmin } from '../utils/admin'
import Disclaimer from './Disclaimer'
import NotificationBell from './NotificationBell'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/portfolio', label: 'Portfolio', icon: Briefcase },
  { to: '/insights', label: 'AI Insights', icon: Lightbulb },
  { to: '/news', label: 'Market News', icon: Newspaper },
  { to: '/assistant', label: 'AI Assistant', icon: MessageSquare },
  { to: '/opportunities', label: 'Opportunities', icon: Sparkles },
  { to: '/security', label: 'Security Center', icon: ShieldCheck, adminOnly: true },
  { to: '/system', label: 'System Check', icon: Server, adminOnly: true },
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

function ThemeToggle() {
  const { isDark, toggleTheme } = useTheme()
  const label = isDark ? 'Light mode' : 'Dark mode'
  const Icon = isDark ? Sun : Moon
  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-pressed={isDark}
      aria-label={`Switch to ${label.toLowerCase()}`}
      title={`Switch to ${label.toLowerCase()}`}
      className="flex w-full items-center justify-center gap-3 rounded-xl px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 lg:justify-between"
    >
      <span className="flex items-center gap-3">
        <Icon size={18} className="shrink-0" />
        <span className="hidden lg:inline">{label}</span>
      </span>
      <span
        className={`relative hidden h-5 w-9 shrink-0 rounded-full transition-colors lg:inline-flex ${isDark ? 'bg-indigo-600' : 'bg-slate-300'}`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-[#fff] shadow transition-all ${isDark ? 'left-4' : 'left-0.5'}`}
        />
      </span>
    </button>
  )
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
  const { user } = useAuth()
  const navItems = NAV_ITEMS.filter((item) => !item.adminOnly || isSuperAdmin(user))

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
          {navItems.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={navClass} title={label}>
              <Icon size={18} className="shrink-0" />
              <span className="hidden lg:inline">{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="mt-3 border-t border-slate-200 pt-3">
          <ThemeToggle />
        </div>
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
