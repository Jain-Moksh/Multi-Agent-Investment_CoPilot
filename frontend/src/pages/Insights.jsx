import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Loader2, Search, Sparkles } from 'lucide-react'
import { getErrorMessage } from '../api/client'
import { createRecommendation, getRecommendation } from '../api/recommendations'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import ErrorBanner from '../components/ErrorBanner'
import PageHeader from '../components/PageHeader'
import ExplainPanel from './insights/ExplainPanel'
import HistoryList from './insights/HistoryList'
import ResultCard from './insights/ResultCard'
import { SYMBOL_PATTERN } from './insights/helpers'

const LOADING_TEXT = 'Running 5 AI agents and the confidence module (can take up to 30 seconds)'
const FORMAT_HELP = 'Enter an NSE/BSE ticker such as INFY, INFY.NS or TCS.BO.'

function errorMessage(err) {
  const status = err?.response?.status
  const detail = getErrorMessage(err)
  if (status === 404) return `Symbol not found or no price data: ${detail}`
  if (status === 422) return `Bad ticker format. ${detail}`
  if (status === 429) return 'This stock was analysed a moment ago. Please wait for the countdown to finish.'
  return detail
}

export default function Insights() {
  const [params, setParams] = useSearchParams()
  const [input, setInput] = useState(params.get('symbol') || '')
  const [result, setResult] = useState(null)
  const [origin, setOrigin] = useState(null)
  const [running, setRunning] = useState(false)
  const [openingId, setOpeningId] = useState(null)
  const [error, setError] = useState('')
  const [cooldownUntil, setCooldownUntil] = useState(0)
  const [now, setNow] = useState(() => Date.now())
  const [historyKey, setHistoryKey] = useState(0)
  const autoRan = useRef(null)

  const secondsLeft = Math.max(0, Math.ceil((cooldownUntil - now) / 1000))

  useEffect(() => {
    if (!cooldownUntil) return undefined
    const timer = setInterval(() => {
      setNow(Date.now())
      if (Date.now() >= cooldownUntil) setCooldownUntil(0)
    }, 1000)
    return () => clearInterval(timer)
  }, [cooldownUntil])

  const analyze = useCallback(async (symbol) => {
    setRunning(true)
    setError('')
    try {
      const data = await createRecommendation(symbol)
      setResult(data)
      setOrigin('new')
      setHistoryKey((key) => key + 1)
    } catch (err) {
      if (err?.response?.status === 429) {
        const seconds = Number(err.response.headers?.['retry-after']) || 30
        setNow(Date.now())
        setCooldownUntil(Date.now() + seconds * 1000)
      }
      setError(errorMessage(err))
    } finally {
      setRunning(false)
    }
  }, [])

  useEffect(() => {
    const symbol = (params.get('symbol') || '').trim().toUpperCase()
    if (!symbol || autoRan.current === symbol) return
    autoRan.current = symbol
    if (!SYMBOL_PATTERN.test(symbol)) {
      setError(`Bad ticker format. ${FORMAT_HELP}`)
      return
    }
    analyze(symbol)
  }, [params, analyze])

  function handleSubmit(event) {
    event.preventDefault()
    const symbol = input.trim().toUpperCase()
    if (!SYMBOL_PATTERN.test(symbol)) {
      setError(`Bad ticker format. ${FORMAT_HELP}`)
      return
    }
    autoRan.current = symbol
    setParams({ symbol }, { replace: true })
    analyze(symbol)
  }

  async function openSaved(id) {
    setOpeningId(id)
    setError('')
    try {
      const data = await getRecommendation(id)
      setResult(data)
      setOrigin('saved')
      setInput(data.symbol)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setOpeningId(null)
    }
  }

  const disabled = running || secondsLeft > 0 || !input.trim()

  return (
    <div className="space-y-6">
      <PageHeader
        title="AI Insights"
        subtitle="Five agents analyse a stock in parallel; a confidence module turns their views into Buy, Hold or Sell."
      />

      <Card>
        <form onSubmit={handleSubmit} className="flex flex-wrap items-center gap-3">
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Stock symbol, e.g. INFY or INFY.NS"
            aria-label="Stock symbol"
            className="min-w-0 flex-1 rounded-xl border border-slate-300 px-4 py-2.5 text-sm uppercase outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
          />
          <button
            type="submit"
            disabled={disabled}
            className="flex items-center gap-2 rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {running ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
            {running ? 'Analyzing...' : secondsLeft > 0 ? `Try again in ${secondsLeft}s` : 'Analyze'}
          </button>
        </form>
        {error && (
          <div className="mt-3">
            <ErrorBanner message={secondsLeft > 0 ? `${error} (${secondsLeft}s)` : error} />
          </div>
        )}
      </Card>

      {running && (
        <Card>
          <div className="flex flex-col items-center gap-3 py-10 text-center" role="status">
            <Loader2 size={32} className="animate-spin text-indigo-600" />
            <p className="font-medium text-slate-800">{LOADING_TEXT}</p>
            <p className="text-xs text-slate-500">News, Market, Portfolio, User Profile and Fundamental agents run at the same time.</p>
          </div>
        </Card>
      )}

      {!running && result && (
        <>
          <ResultCard result={result} origin={origin} />
          <ExplainPanel result={result} />
        </>
      )}

      {!running && !result && !error && (
        <Card>
          <EmptyState
            icon={Sparkles}
            title="Analyze a stock"
            message="Type a symbol above, or open a saved analysis from your history below."
          />
        </Card>
      )}

      <HistoryList refreshKey={historyKey} activeId={result?.id} onOpen={openSaved} openingId={openingId} />
    </div>
  )
}
