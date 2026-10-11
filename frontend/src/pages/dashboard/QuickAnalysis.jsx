import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from 'lucide-react'
import Card from '../../components/Card'
import { insightsLink } from './helpers'

const SYMBOL_PATTERN = /^[A-Za-z0-9&-]{1,20}(\.(NS|BO))?$/i

export default function QuickAnalysis() {
  const navigate = useNavigate()
  const [symbol, setSymbol] = useState('')
  const [error, setError] = useState('')

  function handleSubmit(event) {
    event.preventDefault()
    const value = symbol.trim().toUpperCase()
    if (!SYMBOL_PATTERN.test(value)) {
      setError('Enter an NSE/BSE ticker, for example INFY, RELIANCE.NS or TCS.BO.')
      return
    }
    navigate(insightsLink(value))
  }

  return (
    <Card title="Quick analysis">
      <p className="mb-3 text-sm text-slate-500">Get a Buy / Hold / Sell view from all five agents.</p>
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          value={symbol}
          onChange={(event) => {
            setSymbol(event.target.value)
            setError('')
          }}
          placeholder="e.g. INFY"
          aria-label="Stock symbol"
          className="min-w-0 flex-1 rounded-xl border border-slate-300 px-3 py-2 text-sm uppercase outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
        />
        <button
          type="submit"
          disabled={!symbol.trim()}
          className="flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Search size={16} />
          Analyze
        </button>
      </form>
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
    </Card>
  )
}
