import { useEffect, useMemo, useState } from 'react'
import { History } from 'lucide-react'
import { getErrorMessage } from '../../api/client'
import { listRecommendations } from '../../api/recommendations'
import Card from '../../components/Card'
import ConfidenceBar from '../../components/ConfidenceBar'
import DecisionBadge from '../../components/DecisionBadge'
import EmptyState from '../../components/EmptyState'
import ErrorBanner from '../../components/ErrorBanner'
import Spinner from '../../components/Spinner'
import { formatDateTime } from '../../utils/format'

const FILTERS = ['All', 'Buy', 'Hold', 'Sell', 'Avoid']

export default function HistoryList({ refreshKey, activeId, onOpen, openingId }) {
  const [items, setItems] = useState(null)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('All')
  const [reloadCount, setReloadCount] = useState(0)

  useEffect(() => {
    let active = true
    listRecommendations({ limit: 100 })
      .then((data) => {
        if (!active) return
        setItems(data)
        setError('')
      })
      .catch((err) => {
        if (active) setError(getErrorMessage(err))
      })
    return () => {
      active = false
    }
  }, [refreshKey, reloadCount])

  const visible = useMemo(
    () => (items || []).filter((item) => filter === 'All' || item.decision_label === filter),
    [items, filter],
  )

  return (
    <Card
      title="Analysis history"
      actions={
        <select
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm"
          aria-label="Filter by decision"
        >
          {FILTERS.map((option) => (
            <option key={option} value={option}>
              {option === 'All' ? 'All decisions' : option}
            </option>
          ))}
        </select>
      }
    >
      {error && <ErrorBanner message={error} onRetry={() => setReloadCount((count) => count + 1)} />}
      {!error && items === null && <Spinner label="Loading history" />}
      {!error && items !== null && visible.length === 0 && (
        <EmptyState
          icon={History}
          title={items.length === 0 ? 'No analysis yet' : 'No results for this filter'}
          message={items.length === 0 ? 'Analyze a stock above to start your history.' : undefined}
        />
      )}
      {!error && visible.length > 0 && (
        <ul className="divide-y divide-slate-100">
          {visible.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onOpen(item.id)}
                disabled={openingId === item.id}
                className={`flex w-full flex-wrap items-center gap-x-4 gap-y-2 rounded-xl px-3 py-3 text-left hover:bg-slate-50 disabled:opacity-60 ${
                  activeId === item.id ? 'bg-indigo-50' : ''
                }`}
              >
                <span className="font-medium text-slate-900 sm:w-32 sm:shrink-0">{item.symbol}</span>
                <DecisionBadge decision={item.decision} label={item.decision_label} />
                <ConfidenceBar value={item.confidence} />
                <span className="text-xs text-slate-500 sm:ml-auto">{formatDateTime(item.created_at)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
