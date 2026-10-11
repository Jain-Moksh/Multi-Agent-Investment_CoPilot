import { Fragment, useState } from 'react'
import { ChevronRight, RefreshCw, ShieldCheck } from 'lucide-react'
import Button from '../Button'
import Card from '../Card'
import EmptyState from '../EmptyState'
import AsyncBlock from './AsyncBlock'
import { EVENT_TYPES, EventTypeBadge, SeverityBadge } from './SecurityBadges'
import useApi from '../../hooks/useApi'
import { getSecurityEvents } from '../../api/security'
import { formatDateTime, timeAgo } from '../../utils/format'

const SUMMARY_KEYS = ['reason', 'detail', 'kind', 'message', 'title']

function summarize(details) {
  for (const key of SUMMARY_KEYS) {
    const value = details?.[key]
    if (typeof value === 'string' && value.trim()) return value
  }
  return '-'
}

function DetailValue({ value }) {
  if (value === null || value === undefined || value === '') return <span className="text-slate-400">-</span>
  if (typeof value === 'boolean') return <span className="font-mono text-indigo-700">{String(value)}</span>
  if (typeof value === 'number') return <span className="font-mono text-indigo-700">{value}</span>
  if (typeof value === 'string') return <span className="whitespace-pre-wrap break-words text-slate-800">{value}</span>
  if (Array.isArray(value) && value.every((item) => typeof item !== 'object' || item === null)) {
    return value.length ? (
      <div className="flex flex-wrap gap-1">
        {value.map((item, index) => (
          <code key={index} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-800">
            {String(item)}
          </code>
        ))}
      </div>
    ) : (
      <span className="text-slate-400">none</span>
    )
  }
  return (
    <pre className="overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs leading-relaxed text-slate-100">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

function DetailsView({ details }) {
  const entries = Object.entries(details || {})
  if (!entries.length) return <p className="text-sm text-slate-400">No details recorded.</p>
  return (
    <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[180px_minmax(0,1fr)]">
      {entries.map(([key, value]) => (
        <Fragment key={key}>
          <dt className="font-mono text-xs text-slate-500 sm:pt-0.5">{key}</dt>
          <dd className="min-w-0">
            <DetailValue value={value} />
          </dd>
        </Fragment>
      ))}
    </dl>
  )
}

function EventsTable({ type }) {
  const { data, loading, error, reload } = useApi(() => getSecurityEvents({ type, limit: 100 }))
  const [openId, setOpenId] = useState(null)

  return (
    <AsyncBlock loading={loading} error={error} onRetry={reload} label="Loading security events">
      {data && data.length === 0 && (
        <Card>
          <EmptyState
            icon={ShieldCheck}
            title="No security events"
            message={type ? `No ${EVENT_TYPES[type]?.label.toLowerCase() || type} events recorded yet.` : 'Nothing has been flagged yet.'}
          />
        </Card>
      )}
      {data && data.length > 0 && (
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="w-8 px-3 py-3" />
                  <th className="px-3 py-3">Time</th>
                  <th className="px-3 py-3">Type</th>
                  <th className="px-3 py-3">Severity</th>
                  <th className="px-3 py-3">Blocked</th>
                  <th className="px-3 py-3">Summary</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.map((event) => {
                  const open = openId === event.id
                  return (
                    <Fragment key={event.id}>
                      <tr
                        onClick={() => setOpenId(open ? null : event.id)}
                        className={`cursor-pointer hover:bg-slate-50 ${open ? 'bg-slate-50' : ''}`}
                        aria-expanded={open}
                      >
                        <td className="px-3 py-3 text-slate-400">
                          <ChevronRight size={16} className={`transition ${open ? 'rotate-90' : ''}`} />
                        </td>
                        <td className="whitespace-nowrap px-3 py-3 text-slate-700" title={formatDateTime(event.created_at)}>
                          {timeAgo(event.created_at)}
                        </td>
                        <td className="px-3 py-3">
                          <EventTypeBadge type={event.event_type} />
                        </td>
                        <td className="px-3 py-3">
                          <SeverityBadge severity={event.severity} />
                        </td>
                        <td className="px-3 py-3">
                          {event.blocked ? (
                            <span className="font-medium text-red-600">Yes</span>
                          ) : (
                            <span className="text-slate-500">No</span>
                          )}
                        </td>
                        <td className="max-w-md truncate px-3 py-3 text-slate-600" title={summarize(event.details)}>
                          {summarize(event.details)}
                        </td>
                      </tr>
                      {open && (
                        <tr className="bg-slate-50">
                          <td />
                          <td colSpan={5} className="px-3 pb-4 pt-1">
                            <div className="rounded-xl border border-slate-200 bg-white p-4">
                              <p className="mb-3 text-xs text-slate-500">
                                Event #{event.id} · {formatDateTime(event.created_at)}
                              </p>
                              <DetailsView details={event.details} />
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {data && (
        <div className="mt-3 flex justify-end">
          <Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => reload()}>
            Refresh
          </Button>
        </div>
      )}
    </AsyncBlock>
  )
}

export default function EventsTab() {
  const [type, setType] = useState('')
  const filters = [['', 'All'], ...Object.entries(EVENT_TYPES).map(([key, config]) => [key, config.label])]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {filters.map(([key, label]) => (
          <button
            key={key || 'all'}
            type="button"
            onClick={() => setType(key)}
            className={`rounded-full px-3 py-1.5 text-sm font-medium transition ${
              type === key ? 'bg-indigo-600 text-white' : 'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50'
            }`}
          >
            {label}
          </button>
        ))}
        <span className="ml-auto text-xs text-slate-500">Newest 100 events. You see system events and your own chat events.</span>
      </div>
      <EventsTable key={type || 'all'} type={type} />
    </div>
  )
}
