export const EVENT_TYPES = {
  prompt_injection: { label: 'Prompt injection', className: 'bg-violet-50 text-violet-700 ring-violet-200' },
  agent_hijack: { label: 'Agent hijack', className: 'bg-orange-50 text-orange-700 ring-orange-200' },
  rag_poison: { label: 'RAG poisoning', className: 'bg-sky-50 text-sky-700 ring-sky-200' },
}

const SEVERITIES = {
  low: 'bg-slate-100 text-slate-600 ring-slate-200',
  medium: 'bg-amber-50 text-amber-800 ring-amber-200',
  high: 'bg-red-50 text-red-700 ring-red-200',
  critical: 'bg-red-600 text-white ring-red-600',
}

const VERDICTS = {
  SAFE: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  SUSPICIOUS: 'bg-amber-50 text-amber-800 ring-amber-200',
  BLOCKED: 'bg-red-50 text-red-700 ring-red-200',
}

const PILL = 'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset'

export function EventTypeBadge({ type }) {
  const config = EVENT_TYPES[type]
  return <span className={`${PILL} ${config?.className || SEVERITIES.low}`}>{config?.label || type || '-'}</span>
}

export function SeverityBadge({ severity }) {
  return (
    <span className={`${PILL} capitalize ${SEVERITIES[severity] || SEVERITIES.low}`}>{severity || '-'}</span>
  )
}

export function VerdictBadge({ verdict, size = 'sm' }) {
  const key = (verdict || '').toUpperCase()
  const sizing = size === 'lg' ? 'px-5 py-2 text-xl font-bold tracking-wide' : ''
  return <span className={`${PILL} ${sizing} ${VERDICTS[key] || SEVERITIES.low}`}>{key || '-'}</span>
}
