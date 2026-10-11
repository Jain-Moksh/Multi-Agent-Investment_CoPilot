import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BellOff, CheckCheck, Inbox } from 'lucide-react'
import { getErrorMessage } from '../api/client'
import { getNotifications, isNotificationRead, markNotificationRead, notificationList } from '../api/notifications'
import Button from '../components/Button'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import ErrorBanner from '../components/ErrorBanner'
import PageHeader from '../components/PageHeader'
import Spinner from '../components/Spinner'
import useApi from '../hooks/useApi'
import { formatDateTime, timeAgo } from '../utils/format'

const fetchAll = () => getNotifications({ limit: 100 })

export default function Notifications() {
  const navigate = useNavigate()
  const { data, error, loading, reload } = useApi(fetchAll)
  const [marking, setMarking] = useState(false)
  const [actionError, setActionError] = useState('')
  const items = notificationList(data)
  const unread = items.filter((item) => !isNotificationRead(item))
  const notBuilt = error?.raw?.response?.status === 404

  async function markAll() {
    setMarking(true)
    setActionError('')
    try {
      for (const item of unread) await markNotificationRead(item.id)
      await reload({ silent: true })
    } catch (err) {
      setActionError(getErrorMessage(err))
    } finally {
      setMarking(false)
    }
  }

  async function open(item) {
    if (!isNotificationRead(item)) await markNotificationRead(item.id).catch(() => null)
    navigate(item.symbol ? `/insights?symbol=${encodeURIComponent(item.symbol)}` : '/notifications')
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Notifications"
        subtitle="Alerts about your holdings and new analyses."
        actions={
          !notBuilt &&
          items.length > 0 && (
            <Button variant="secondary" icon={CheckCheck} onClick={markAll} loading={marking} disabled={unread.length === 0}>
              Mark all read
            </Button>
          )
        }
      />
      <Card>
        {loading && <Spinner label="Loading notifications" />}
        {!loading && notBuilt && (
          <EmptyState
            icon={BellOff}
            title="Notifications are not enabled yet"
            message="The backend does not provide notifications yet. When it does, alerts about your holdings will appear here."
          />
        )}
        {!loading && error && !notBuilt && <ErrorBanner message={error.message} onRetry={() => reload()} />}
        {actionError && <ErrorBanner message={actionError} />}
        {!loading && !error && items.length === 0 && (
          <EmptyState icon={Inbox} title="No notifications yet" message="You are all caught up." />
        )}
        {!loading && !error && items.length > 0 && (
          <ul className="divide-y divide-slate-100">
            {items.map((item) => {
              const read = isNotificationRead(item)
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => open(item)}
                    className="flex w-full items-start gap-3 rounded-xl px-3 py-3 text-left hover:bg-slate-50"
                  >
                    <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${read ? 'bg-transparent' : 'bg-indigo-600'}`} />
                    <div className="min-w-0 flex-1">
                      <p className={read ? 'text-slate-600' : 'font-medium text-slate-900'}>{item.title || item.message || '-'}</p>
                      {item.title && item.message && <p className="mt-0.5 text-sm text-slate-500">{item.message}</p>}
                      <p className="mt-1 text-xs text-slate-500">
                        {item.symbol ? `${item.symbol} · ` : ''}
                        <span title={formatDateTime(item.created_at)}>{timeAgo(item.created_at)}</span>
                      </p>
                    </div>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </Card>
    </div>
  )
}
