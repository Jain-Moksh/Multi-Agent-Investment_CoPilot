import { Info } from 'lucide-react'
import { getSummary } from '../api/portfolio'
import PageHeader from '../components/PageHeader'
import { useAuth } from '../context/AuthContext'
import AllocationCard from './dashboard/AllocationCard'
import KpiCards from './dashboard/KpiCards'
import NewsCard from './dashboard/NewsCard'
import QuickAnalysis from './dashboard/QuickAnalysis'
import RecommendationsCard from './dashboard/RecommendationsCard'
import WeightsCard from './dashboard/WeightsCard'
import useRequest from './dashboard/useRequest'

const fetchSummary = () => getSummary()

function MissingPriceBanner({ summary }) {
  const missing = summary.data?.holdings?.some((holding) => holding.price_missing)
  if (!missing) return null
  return (
    <div className="flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
      <Info size={16} className="shrink-0" />
      Some prices are unavailable, values use your buy price.
    </div>
  )
}

export default function Dashboard() {
  const { user } = useAuth()
  const summary = useRequest(fetchSummary)

  return (
    <div className="space-y-6">
      <PageHeader title="Dashboard" subtitle={user?.email ? `Welcome back, ${user.email}` : undefined} />
      <MissingPriceBanner summary={summary} />
      <KpiCards summary={summary} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <AllocationCard summary={summary} />
        <WeightsCard summary={summary} />
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6">
          <QuickAnalysis />
          <RecommendationsCard />
        </div>
        <div className="lg:col-span-2">
          <NewsCard />
        </div>
      </div>
    </div>
  )
}
