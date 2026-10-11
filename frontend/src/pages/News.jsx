import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Briefcase, Hammer, Newspaper, Search, ShieldCheck, X } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import ErrorBanner from '../components/ErrorBanner'
import NewsCard from '../components/NewsCard'
import { getNews } from '../api/news'
import { getErrorMessage, isNotBuilt } from '../api/client'
import { sentimentBucket } from '../utils/format'

const PAGE_SIZE = 20

function useDebounced(value, delay = 400) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

function StatTile({ label, value, children }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      {value !== undefined && <p className="mt-1 text-2xl font-semibold text-slate-900">{value}</p>}
      {children}
    </div>
  )
}

function SentimentSplit({ counts }) {
  const scored = counts.positive + counts.neutral + counts.negative
  const segments = [
    { key: 'positive', label: 'Positive', bar: 'bg-emerald-500', text: 'text-emerald-700' },
    { key: 'neutral', label: 'Neutral', bar: 'bg-slate-400', text: 'text-slate-600' },
    { key: 'negative', label: 'Negative', bar: 'bg-red-500', text: 'text-red-700' },
  ]
  return (
    <>
      <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-slate-100">
        {scored > 0 &&
          segments.map((segment) => (
            <div
              key={segment.key}
              className={segment.bar}
              style={{ width: `${(counts[segment.key] / scored) * 100}%` }}
            />
          ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
        {segments.map((segment) => (
          <span key={segment.key} className={segment.text}>
            {segment.label} {counts[segment.key]}
          </span>
        ))}
        {counts.unscored > 0 && <span className="text-slate-400">Not scored {counts.unscored}</span>}
      </div>
    </>
  )
}

function SkeletonCard() {
  return (
    <div className="animate-pulse rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-3 h-3 w-1/3 rounded bg-slate-200" />
      <div className="mb-2 h-4 w-11/12 rounded bg-slate-200" />
      <div className="mb-4 h-4 w-2/3 rounded bg-slate-200" />
      <div className="mb-2 h-3 w-full rounded bg-slate-100" />
      <div className="mb-2 h-3 w-full rounded bg-slate-100" />
      <div className="mb-4 h-3 w-4/5 rounded bg-slate-100" />
      <div className="flex gap-2">
        <div className="h-5 w-16 rounded-full bg-slate-200" />
        <div className="h-5 w-20 rounded-full bg-slate-200" />
        <div className="h-5 w-14 rounded bg-slate-100" />
      </div>
    </div>
  )
}

export default function News() {
  const [symbolInput, setSymbolInput] = useState('')
  const [sector, setSector] = useState('')
  const [portfolioOnly, setPortfolioOnly] = useState(false)
  const [search, setSearch] = useState('')
  const symbol = useDebounced(symbolInput.trim())

  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const [loadMoreError, setLoadMoreError] = useState('')
  const [notBuilt, setNotBuilt] = useState(false)
  const [knownSectors, setKnownSectors] = useState([])
  const requestId = useRef(0)

  const rememberSectors = useCallback((newItems) => {
    setKnownSectors((previous) => {
      const next = new Set(previous)
      newItems.forEach((item) => item.affected_sector && next.add(item.affected_sector))
      return next.size === previous.length ? previous : [...next].sort((a, b) => a.localeCompare(b))
    })
  }, [])

  const loadFirstPage = useCallback(async () => {
    const id = ++requestId.current
    setLoading(true)
    setLoadingMore(false)
    setError('')
    setLoadMoreError('')
    setNotBuilt(false)
    try {
      const page = await getNews({ symbol, sector, portfolioOnly, limit: PAGE_SIZE, offset: 0 })
      if (id !== requestId.current) return
      setItems(page.items)
      setTotal(page.total)
      rememberSectors(page.items)
    } catch (err) {
      if (id !== requestId.current) return
      setItems([])
      setTotal(0)
      if (isNotBuilt(err)) setNotBuilt(true)
      else setError(getErrorMessage(err, 'Could not load news.'))
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }, [symbol, sector, portfolioOnly, rememberSectors])

  useEffect(() => {
    loadFirstPage()
  }, [loadFirstPage])

  const loadMore = async () => {
    const id = requestId.current
    setLoadingMore(true)
    setLoadMoreError('')
    try {
      const page = await getNews({ symbol, sector, portfolioOnly, limit: PAGE_SIZE, offset: items.length })
      if (id !== requestId.current) return
      setItems((previous) => {
        const seen = new Set(previous.map((item) => item.id))
        return [...previous, ...page.items.filter((item) => !seen.has(item.id))]
      })
      setTotal(page.total)
      rememberSectors(page.items)
    } catch (err) {
      if (id === requestId.current) setLoadMoreError(getErrorMessage(err, 'Could not load more news.'))
    } finally {
      if (id === requestId.current) setLoadingMore(false)
    }
  }

  const visibleItems = useMemo(() => {
    const term = search.trim().toLowerCase()
    return term ? items.filter((item) => item.title.toLowerCase().includes(term)) : items
  }, [items, search])

  const stats = useMemo(() => {
    const counts = { positive: 0, neutral: 0, negative: 0, unscored: 0 }
    let affecting = 0
    visibleItems.forEach((item) => {
      counts[sentimentBucket(item.sentiment)] += 1
      if (item.affects_my_portfolio) affecting += 1
    })
    return { counts, affecting }
  }, [visibleItems])

  const hasServerFilters = Boolean(symbol || sector || portfolioOnly)
  const hasMore = items.length < total

  const clearFilters = () => {
    setSymbolInput('')
    setSector('')
    setPortfolioOnly(false)
    setSearch('')
  }

  const sectorOptions = sector && !knownSectors.includes(sector) ? [...knownSectors, sector] : knownSectors

  return (
    <div>
      <PageHeader title="Market News" subtitle="Latest market news, matched to the sectors and stocks it affects." />

      <div className="mb-4 flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm text-emerald-800">
        <ShieldCheck size={18} className="mt-0.5 shrink-0" />
        <p>Only articles that passed the security scan are shown.</p>
      </div>

      <Card className="mb-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-[1fr_1fr_auto_1.4fr]">
          <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
            Symbol
            <input
              type="text"
              value={symbolInput}
              onChange={(event) => setSymbolInput(event.target.value.toUpperCase())}
              placeholder="e.g. INFY or INFY.NS"
              maxLength={32}
              className="rounded-xl border border-slate-300 px-3 py-2 text-sm font-normal text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
            />
          </label>

          <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
            Sector
            <select
              value={sector}
              onChange={(event) => setSector(event.target.value)}
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-normal text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
            >
              <option value="">All sectors</option>
              {sectorOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          <div className="flex flex-col gap-1 text-xs font-medium text-slate-600">
            <span>Portfolio</span>
            <button
              type="button"
              role="switch"
              aria-checked={portfolioOnly}
              onClick={() => setPortfolioOnly((value) => !value)}
              className="flex items-center gap-2 rounded-xl border border-slate-300 px-3 py-2 text-sm font-normal text-slate-700 hover:bg-slate-50"
            >
              <span
                className={`relative inline-flex h-5 w-9 shrink-0 rounded-full transition ${portfolioOnly ? 'bg-indigo-600' : 'bg-slate-300'}`}
              >
                <span
                  className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition ${portfolioOnly ? 'left-4' : 'left-0.5'}`}
                />
              </span>
              <span className="text-left xl:whitespace-nowrap">Only news affecting my portfolio</span>
            </button>
          </div>

          <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
            Search titles
            <div className="relative">
              <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Filter loaded articles by title"
                className="w-full rounded-xl border border-slate-300 py-2 pl-9 pr-3 text-sm font-normal text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
              />
            </div>
          </label>
        </div>

        {(hasServerFilters || search) && (
          <button
            type="button"
            onClick={clearFilters}
            className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-800"
          >
            <X size={14} />
            Clear filters
          </button>
        )}
      </Card>

      {!notBuilt && !error && (
        <div className="mb-4 grid gap-3 sm:grid-cols-3">
          <StatTile label="Articles shown" value={loading ? '-' : visibleItems.length}>
            {!loading && <p className="mt-1 text-xs text-slate-500">{total} matching in total</p>}
          </StatTile>
          <StatTile label="Affect your portfolio" value={loading ? '-' : stats.affecting}>
            <p className="mt-1 flex items-center gap-1 text-xs text-slate-500">
              <Briefcase size={12} />
              of the articles shown
            </p>
          </StatTile>
          <StatTile label="Sentiment split">
            {loading ? (
              <div className="mt-3 h-2 animate-pulse rounded-full bg-slate-200" />
            ) : (
              <SentimentSplit counts={stats.counts} />
            )}
          </StatTile>
        </div>
      )}

      {error && <ErrorBanner message={error} onRetry={loadFirstPage} />}

      {notBuilt && (
        <Card>
          <EmptyState icon={Hammer} title="Not built yet" message="The news endpoint is not available on this backend." />
        </Card>
      )}

      {loading && !error && !notBuilt && (
        <div className="grid gap-4 lg:grid-cols-2">
          {Array.from({ length: 6 }, (_, index) => (
            <SkeletonCard key={index} />
          ))}
        </div>
      )}

      {!loading && !error && !notBuilt && items.length === 0 && (
        <Card>
          <EmptyState
            icon={Newspaper}
            title={hasServerFilters ? 'No news matches these filters' : 'No news yet'}
            message={
              portfolioOnly
                ? 'No recent articles mention a stock you hold. News is ingested every 10 minutes, so check back soon.'
                : 'News is ingested every 10 minutes. Check back shortly for fresh articles.'
            }
            actionLabel={hasServerFilters ? 'Clear filters' : 'Refresh'}
            onAction={hasServerFilters ? clearFilters : loadFirstPage}
          />
        </Card>
      )}

      {!loading && !error && items.length > 0 && visibleItems.length === 0 && (
        <Card>
          <EmptyState
            icon={Search}
            title="No loaded titles match your search"
            message={hasMore ? 'Try a different word, or load more articles first.' : 'Try a different word.'}
            actionLabel="Clear search"
            onAction={() => setSearch('')}
          />
        </Card>
      )}

      {!loading && visibleItems.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-2">
          {visibleItems.map((item) => (
            <NewsCard key={item.id} item={item} onSymbolClick={setSymbolInput} />
          ))}
        </div>
      )}

      {!loading && !error && items.length > 0 && (
        <div className="mt-6 flex flex-col items-center gap-3">
          {loadMoreError && <ErrorBanner message={loadMoreError} onRetry={loadMore} />}
          {hasMore ? (
            <button
              type="button"
              onClick={loadMore}
              disabled={loadingMore}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-5 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loadingMore && (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-200 border-t-indigo-600" />
              )}
              {loadingMore ? 'Loadingâ€¦' : `Load more (${total - items.length} left)`}
            </button>
          ) : (
            <p className="text-xs text-slate-400">You have reached the end. News is ingested every 10 minutes.</p>
          )}
        </div>
      )}
    </div>
  )
}
