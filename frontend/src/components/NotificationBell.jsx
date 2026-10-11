import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Bell, BellOff, Loader2 } from 'lucide-react'
import { getErrorMessage } from '../api/client'
import { getNotifications, isNotificationRead, markNotificationRead, notificationList } from '../api/notifications'
import { timeAgo } from '../utils/format'

const POLL_MS = 60000
const DROPDOWN_LIMIT = 8

export default function NotificationBell() {
  const navigate = useNavigate()
  const [state, setState] = useState('loading')
  const [unread, setUnread] = useState(0)
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState(null)
  const [listError, setListError] = useState('')
  const containerRef = useRef(null)

  useEffect(() => {
    let timer = null
    let stopped = false

    async function poll() {
      try {
        const data = await getNotifications({ unread_only: true })
        if (stopped) return
        setUnread(notificationList(data).length)
        setState('ok')
      } catch (error) {
        if (stopped) return
        if (error?.response?.status === 404) {
          setState('disabled')
          return
        }
        setState('error')
      }
      if (!stopped) timer = setTimeout(poll, POLL_MS)
    }

    poll()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [])

  useEffect(() => {
    function handleClick(event) {
      if (containerRef.current && !containerRef.current.contains(event.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  async function toggle() {
    if (open) {
      setOpen(false)
      return
    }
    setOpen(true)
    setItems(null)
    setListError('')
    try {
      setItems(notificationList(await getNotifications({ limit: DROPDOWN_LIMIT })).slice(0, DROPDOWN_LIMIT))
    } catch (error) {
      setListError(getErrorMessage(error))
    }
  }

  async function openItem(item) {
    setOpen(false)
    if (!isNotificationRead(item)) {
      const marked = await markNotificationRead(item.id).then(
        () => true,
        () => false,
      )
      if (marked) setUnread((count) => Math.max(0, count - 1))
    }
    navigate(item.symbol ? `/insights?symbol=${encodeURIComponent(item.symbol)}` : '/notifications')
  }

  if (state === 'disabled') {
    return (
      <span className="rounded-xl p-2 text-slate-400" title="Notifications not enabled yet" aria-label="Notifications not enabled yet">
        <BellOff size={20} />
      </span>
    )
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={toggle}
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : 'Notifications'}
        title={state === 'error' ? 'Could not load notifications' : 'Notifications'}
        className="relative rounded-xl p-2 text-slate-600 hover:bg-slate-100"
      >
        <Bell size={20} />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-red-600 px-1 text-[11px] font-semibold text-white">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-2 w-80 rounded-xl border border-slate-200 bg-white shadow-lg">
          <div className="border-b border-slate-100 px-4 py-2 text-sm font-semibold text-slate-900">Notifications</div>
          {items === null && !listError && (
            <div className="flex items-center justify-center gap-2 py-6 text-sm text-slate-500">
              <Loader2 size={16} className="animate-spin" />
              Loading
            </div>
          )}
          {listError && <p className="px-4 py-4 text-sm text-red-700">{listError}</p>}
          {items && items.length === 0 && <p className="px-4 py-6 text-center text-sm text-slate-500">No notifications yet.</p>}
          {items && items.length > 0 && (
            <ul className="max-h-80 divide-y divide-slate-100 overflow-y-auto">
              {items.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => openItem(item)}
                    className={`w-full px-4 py-3 text-left text-sm hover:bg-slate-50 ${isNotificationRead(item) ? 'text-slate-500' : 'font-medium text-slate-900'}`}
                  >
                    <p>{item.title || item.message || '-'}</p>
                    <p className="mt-0.5 text-xs font-normal text-slate-500">
                      {item.symbol ? `${item.symbol} · ` : ''}
                      {timeAgo(item.created_at)}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <Link
            to="/notifications"
            onClick={() => setOpen(false)}
            className="block border-t border-slate-100 px-4 py-2 text-center text-sm font-medium text-indigo-600 hover:bg-slate-50"
          >
            View all
          </Link>
        </div>
      )}
    </div>
  )
}
