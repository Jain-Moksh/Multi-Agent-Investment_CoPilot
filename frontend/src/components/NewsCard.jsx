import { Briefcase, ExternalLink } from 'lucide-react'
import SentimentPill from './SentimentPill'
import { formatDateTime, timeAgo } from '../utils/format'

export default function NewsCard({ item, onSymbolClick }) {
  const symbols = item.affected_symbols || []
  return (
    <article className="flex h-full flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:shadow-md">
      <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
        <span className="font-medium text-slate-700">{item.source_name || item.source_domain || '-'}</span>
        <span>·</span>
        <time dateTime={item.seen_at} title={formatDateTime(item.seen_at)}>
          {timeAgo(item.seen_at)}
        </time>
        {item.affects_my_portfolio && (
          <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2.5 py-0.5 font-medium text-indigo-700 ring-1 ring-inset ring-indigo-200">
            <Briefcase size={12} />
            Affects your portfolio
          </span>
        )}
      </div>

      <h3 className="text-base font-semibold leading-snug text-slate-900">
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="group inline hover:text-indigo-700"
        >
          {item.title}
          <ExternalLink size={14} className="ml-1 inline align-baseline text-slate-400 group-hover:text-indigo-600" />
        </a>
      </h3>

      {item.description && <p className="mt-2 line-clamp-3 text-sm text-slate-600">{item.description}</p>}

      <div className="mt-auto flex flex-wrap items-center gap-2 pt-4">
        <SentimentPill value={item.sentiment} />
        <span className="rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-inset ring-amber-200">
          {item.affected_sector || 'No sector'}
        </span>
        {symbols.map((symbol) => (
          <button
            key={symbol}
            type="button"
            onClick={() => onSymbolClick?.(symbol)}
            title={`Show news for ${symbol}`}
            className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-700 hover:bg-indigo-100 hover:text-indigo-700"
          >
            {symbol}
          </button>
        ))}
      </div>
    </article>
  )
}
