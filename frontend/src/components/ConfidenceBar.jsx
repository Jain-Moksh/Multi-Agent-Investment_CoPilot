import { clamp } from '../utils/format'

export default function ConfidenceBar({ value }) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return <span className="text-sm text-slate-500">-</span>
  }
  const percent = Math.round(clamp(Number(value), 0, 1) * 100)
  const color = percent >= 70 ? 'bg-green-500' : percent >= 40 ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-2 w-24 overflow-hidden rounded-full bg-slate-200"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className={`h-full rounded-full ${color}`} style={{ width: `${percent}%` }} />
      </div>
      <span className="text-xs font-medium text-slate-600">{percent}%</span>
    </div>
  )
}
