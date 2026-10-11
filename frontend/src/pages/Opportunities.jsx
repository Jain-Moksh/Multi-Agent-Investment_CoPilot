import { useNavigate } from 'react-router-dom'
import { Hammer, Search, Sparkles, UserCheck } from 'lucide-react'
import { getOpportunities } from '../api/opportunities'
import Button from '../components/Button'
import Card from '../components/Card'
import Disclaimer from '../components/Disclaimer'
import EmptyState from '../components/EmptyState'
import ErrorBanner from '../components/ErrorBanner'
import PageHeader from '../components/PageHeader'
import Spinner from '../components/Spinner'
import useApi from '../hooks/useApi'
import { formatINR, formatPct, plClass } from '../utils/format'

const fetchOpportunities = () => getOpportunities()

function toList(data) {
  if (Array.isArray(data)) return data
  return Array.isArray(data?.items) ? data.items : []
}

function OpportunityCard({ item }) {
  const navigate = useNavigate()
  const price = item.current_price ?? item.price
  const reasons = Array.isArray(item.reasons) ? item.reasons.slice(0, 3) : []
  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-lg font-semibold text-slate-900">{item.symbol || '-'}</p>
          {item.company_name && <p className="text-sm text-slate-500">{item.company_name}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="rounded-full bg-indigo-100 px-2.5 py-1 text-xs font-semibold text-indigo-700">Worth a look</span>
          {item.fits_profile && (
            <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-1 text-xs font-semibold text-green-700">
              <UserCheck size={12} />
              Fits your profile
            </span>
          )}
        </div>
      </div>
      <div className="mb-3 flex flex-wrap gap-6 text-sm">
        <div>
          <p className="text-xs text-slate-500">Price</p>
          <p className="font-medium text-slate-900">{formatINR(price)}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Day change</p>
          <p className={`font-medium ${plClass(item.change_pct)}`}>{formatPct(item.change_pct)}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Score</p>
          <p className="font-medium text-slate-900">{item.score ?? '-'}</p>
        </div>
      </div>
      {reasons.length > 0 && (
        <ul className="mb-3 list-disc space-y-1 pl-5 text-sm text-slate-700">
          {reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      <p className="mb-4 text-sm text-slate-600">{item.explanation || '-'}</p>
      <Button
        icon={Search}
        onClick={() => navigate(`/insights?symbol=${encodeURIComponent(item.symbol)}`)}
        disabled={!item.symbol}
      >
        Analyze in detail
      </Button>
      <Disclaimer className="mt-3" />
    </Card>
  )
}

export default function Opportunities() {
  const { data, error, loading, reload } = useApi(fetchOpportunities)
  const notBuilt = error?.raw?.response?.status === 404
  const items = toList(data)

  return (
    <div className="space-y-6">
      <PageHeader title="Opportunities" subtitle="Stocks you do not hold that may be worth a closer look." />
      {loading && <Spinner label="Scanning for opportunities" />}
      {!loading && notBuilt && (
        <Card>
          <EmptyState
            icon={Hammer}
            title="Opportunity Scanner is not built yet"
            message="When it is ready, it will find stocks with strongly positive news on its own and match them to your risk profile, so you can analyse them in detail."
          />
        </Card>
      )}
      {!loading && error && !notBuilt && <ErrorBanner message={error.message} onRetry={() => reload()} />}
      {!loading && !error && items.length === 0 && (
        <Card>
          <EmptyState icon={Sparkles} title="No opportunities right now" message="Check again after the next news update." />
        </Card>
      )}
      {!loading && !error && items.length > 0 && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {items.map((item) => (
            <OpportunityCard key={item.symbol || item.id} item={item} />
          ))}
        </div>
      )}
    </div>
  )
}
