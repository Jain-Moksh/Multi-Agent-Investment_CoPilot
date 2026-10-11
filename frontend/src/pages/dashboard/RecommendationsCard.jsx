import { Link, useNavigate } from 'react-router-dom'
import { ChevronRight, Lightbulb } from 'lucide-react'
import { listRecommendations } from '../../api/recommendations'
import Card from '../../components/Card'
import ConfidenceBar from '../../components/ConfidenceBar'
import DecisionBadge from '../../components/DecisionBadge'
import Disclaimer from '../../components/Disclaimer'
import EmptyState from '../../components/EmptyState'
import { timeAgo } from '../../utils/format'
import CardState from './CardState'
import useRequest from './useRequest'
import { insightsLink, shortSymbol } from './helpers'

const fetchLatest = () => listRecommendations({ limit: 4 })

export default function RecommendationsCard() {
  const request = useRequest(fetchLatest)
  const navigate = useNavigate()
  return (
    <Card
      title="Recent AI recommendations"
      actions={
        <Link to="/insights" className="text-sm font-medium text-indigo-600 hover:underline">
          Open Insights
        </Link>
      }
    >
      <CardState request={request} loadingLabel="Loading recommendations">
        {(items) =>
          items.length === 0 ? (
            <EmptyState
              icon={Lightbulb}
              title="No analysis yet. Analyze one of your stocks."
              actionLabel="Go to Insights"
              onAction={() => navigate('/insights')}
            />
          ) : (
            <ul className="divide-y divide-slate-100">
              {items.slice(0, 4).map((item) => (
                <li key={item.id}>
                  <Link
                    to={insightsLink(item.symbol)}
                    className="flex items-center gap-3 rounded-xl px-2 py-3 hover:bg-slate-50"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-slate-900">{shortSymbol(item.symbol)}</p>
                      <p className="text-xs text-slate-500">{timeAgo(item.created_at)}</p>
                    </div>
                    <DecisionBadge decision={item.decision} label={item.decision_label} />
                    <ConfidenceBar value={item.confidence} />
                    <ChevronRight size={16} className="text-slate-400" />
                  </Link>
                </li>
              ))}
            </ul>
          )
        }
      </CardState>
      <Disclaimer className="mt-3" />
    </Card>
  )
}
