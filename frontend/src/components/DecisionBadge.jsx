const STYLES = {
  buy: 'bg-green-100 text-green-700',
  hold: 'bg-amber-100 text-amber-700',
  sell: 'bg-red-100 text-red-700',
}

export default function DecisionBadge({ decision, label }) {
  const key = String(decision || '').toLowerCase()
  const text = label || (key ? key.charAt(0).toUpperCase() + key.slice(1) : '-')
  const style = STYLES[key] || 'bg-slate-100 text-slate-600'
  return (
    <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${style}`}>{text}</span>
  )
}
