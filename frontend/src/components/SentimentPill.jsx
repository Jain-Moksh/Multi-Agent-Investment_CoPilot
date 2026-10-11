import { sentimentBucket } from '../utils/format'

const STYLES = {
  positive: { label: 'Positive', className: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  neutral: { label: 'Neutral', className: 'bg-slate-100 text-slate-600 ring-slate-200' },
  negative: { label: 'Negative', className: 'bg-red-50 text-red-700 ring-red-200' },
  unscored: { label: 'Not scored', className: 'bg-white text-slate-400 ring-slate-200' },
}

export default function SentimentPill({ value }) {
  const bucket = sentimentBucket(value)
  const { label, className } = STYLES[bucket]
  const tooltip = bucket === 'unscored' ? 'Sentiment not scored yet' : `Sentiment score: ${Number(value).toFixed(2)}`
  return (
    <span
      title={tooltip}
      className={`inline-flex cursor-help items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${className}`}
    >
      {label}
    </span>
  )
}
