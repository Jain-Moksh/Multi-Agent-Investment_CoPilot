import { Link } from 'react-router-dom'
import { ExternalLink, Newspaper } from 'lucide-react'
import { getNews } from '../../api/news'
import Card from '../../components/Card'
import EmptyState from '../../components/EmptyState'
import { timeAgo } from '../../utils/format'
import CardState from './CardState'
import useRequest from './useRequest'

const LIMIT = 5

async function fetchImportantNews() {
  const mine = await getNews({ portfolioOnly: true, limit: LIMIT })
  if (mine.items.length > 0) return { items: mine.items, fallback: false }
  const latest = await getNews({ limit: LIMIT })
  return { items: latest.items, fallback: true }
}

function SentimentPill({ value }) {
  if (value === null || value === undefined) {
    return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">Not scored</span>
  }
  if (value > 0.15) {
    return <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">Positive</span>
  }
  if (value < -0.15) {
    return <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">Negative</span>
  }
  return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">Neutral</span>
}

export default function NewsCard() {
  const request = useRequest(fetchImportantNews)
  return (
    <Card
      title="Important market news"
      actions={
        <Link to="/news" className="text-sm font-medium text-indigo-600 hover:underline">
          View all
        </Link>
      }
    >
      <CardState request={request} loadingLabel="Loading news">
        {({ items, fallback }) =>
          items.length === 0 ? (
            <EmptyState icon={Newspaper} title="No news yet" message="News is collected automatically every 10 minutes." />
          ) : (
            <>
              {fallback && (
                <p className="mb-2 text-xs text-slate-500">No news mentions your holdings yet, so here is the latest news.</p>
              )}
              <ul className="divide-y divide-slate-100">
                {items.map((item) => (
                  <li key={item.id} className="py-3">
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group flex items-start gap-2 font-medium text-slate-900 hover:text-indigo-700"
                    >
                      <span className="flex-1">{item.title}</span>
                      <ExternalLink size={14} className="mt-1 shrink-0 text-slate-400 group-hover:text-indigo-600" />
                    </a>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <span>{item.source_name || item.source_domain || '-'}</span>
                      <span>·</span>
                      <span>{timeAgo(item.seen_at)}</span>
                      <SentimentPill value={item.sentiment} />
                      {item.affects_my_portfolio && (
                        <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-700">
                          Affects your portfolio
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )
        }
      </CardState>
    </Card>
  )
}
