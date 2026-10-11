import { useEffect, useMemo, useState } from 'react'
import { History, PanelRightOpen } from 'lucide-react'
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

export default function HistoryList({ refreshKey, activeId, onOpen, openingId, onReview, reviewId }) {
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
            <li
              key={item.id}
              className={`flex flex-wrap items-center gap-3 rounded-xl px-3 py-2 transition hover:bg-slate-50 ${
                activeId === item.id || reviewId === item.id ? 'bg-indigo-50 hover:bg-indigo-50' : ''
              }`}
            >
              <button
                type="button"
                onClick={() => onOpen(item.id)}
                disabled={openingId === item.id}
                title="Show this analysis on the page"
                className="flex w-full min-w-0 flex-wrap items-center gap-x-4 gap-y-2 py-1 text-left disabled:opacity-60 sm:w-auto sm:flex-1"
              >
                <span className="font-medium text-slate-900 sm:w-32 sm:shrink-0">{item.symbol}</span>
                <DecisionBadge decision={item.decision} label={item.decision_label} />
                <ConfidenceBar value={item.confidence} />
                <span className="text-xs text-slate-500 sm:ml-auto">{formatDateTime(item.created_at)}</span>
              </button>
              <button
                type="button"
                onClick={() => onReview(item.id)}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-indigo-200 bg-white px-3 py-1.5 text-xs font-semibold text-indigo-700 shadow-sm transition hover:border-indigo-300 hover:bg-indigo-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300"
              >
                <PanelRightOpen size={14} />
                Detail review
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
