import { AlertTriangle, Bot, FileText, Star } from 'lucide-react'
import Card from '../../components/Card'
import Disclaimer from '../../components/Disclaimer'
import { formatDateTime } from '../../utils/format'
import { AGENT_LABELS, explanationSourceLabel, signed } from './helpers'

const BIG_BADGE = {
  buy: 'bg-green-600 text-white',
  hold: 'bg-amber-500 text-white',
  sell: 'bg-red-600 text-white',
}

function ConfidenceRing({ value, level }) {
  const percent = Math.round(Math.max(0, Math.min(1, Number(value) || 0)) * 100)
  const radius = 42
  const circumference = 2 * Math.PI * radius
  const color = percent >= 70 ? '#16a34a' : percent >= 35 ? '#d97706' : '#dc2626'
  return (
    <div className="flex flex-col items-center">
      <svg width="110" height="110" viewBox="0 0 110 110" role="img" aria-label={`Confidence ${percent}%`}>
        <circle cx="55" cy="55" r={radius} fill="none" stroke="#e2e8f0" strokeWidth="10" />
        <circle
          cx="55"
          cy="55"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${(percent / 100) * circumference} ${circumference}`}
          transform="rotate(-90 55 55)"
        />
        <text x="55" y="60" textAnchor="middle" fontSize="22" fontWeight="600" fill="#0f172a">
          {percent}%
        </text>
      </svg>
      <span className="text-xs font-medium uppercase tracking-wide text-slate-500">{level || '-'} confidence</span>
    </div>
  )
}

function position(value) {
  return `${((Math.max(-1, Math.min(1, value)) + 1) / 2) * 100}%`
}

function LeanGauge({ lean, thresholds }) {
  const sell = thresholds?.sell ?? -0.3
  const buy = thresholds?.buy ?? 0.3
  const value = Number(lean) || 0
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs text-slate-500">
        <span>Bearish</span>
        <span className="font-medium text-slate-700">Overall lean {signed(value)}</span>
        <span>Bullish</span>
      </div>
      <div className="relative h-4 overflow-hidden rounded-full">
        <div className="absolute inset-y-0 left-0 bg-red-100" style={{ width: position(sell) }} />
        <div
          className="absolute inset-y-0 bg-amber-100"
          style={{ left: position(sell), width: `calc(${position(buy)} - ${position(sell)})` }}
        />
        <div className="absolute inset-y-0 right-0 bg-green-100" style={{ left: position(buy) }} />
        <div className="absolute inset-y-0 w-px bg-red-500" style={{ left: position(sell) }} />
        <div className="absolute inset-y-0 w-px bg-green-600" style={{ left: position(buy) }} />
      </div>
      <div className="relative h-5">
        <div
          className="absolute -top-5 h-6 w-1.5 -translate-x-1/2 rounded-full bg-slate-900 shadow"
          style={{ left: position(value) }}
          title={`Lean ${signed(value)}`}
        />
      </div>
      <div className="relative h-4 text-[11px] text-slate-500">
        <span className="absolute left-0">-1</span>
        <span className="absolute -translate-x-1/2" style={{ left: position(sell) }}>
          Sell {signed(sell, 1)}
        </span>
        <span className="absolute -translate-x-1/2" style={{ left: '50%' }}>
          0
        </span>
        <span className="absolute -translate-x-1/2" style={{ left: position(buy) }}>
          Buy {signed(buy, 1)}
        </span>
        <span className="absolute right-0">+1</span>
      </div>
    </div>
  )
}

export default function ResultCard({ result, origin }) {
  const details = result.details || {}
  const key = String(result.decision || '').toLowerCase()
  const label = result.decision_label || result.decision || '-'
  const driver = result.main_driver
  const sourceIsAi = result.explanation_source === 'llm'
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <span className={`rounded-2xl px-5 py-2 text-2xl font-bold ${BIG_BADGE[key] || 'bg-slate-200 text-slate-700'}`}>
              {label}
            </span>
            <div>
              <p className="text-xl font-semibold text-slate-900">{result.symbol}</p>
              <p className="text-sm text-slate-500">{result.company_name || '-'}</p>
            </div>
          </div>
          <p className="text-xs text-slate-500">
            {origin === 'saved' ? 'Saved analysis from ' : 'Analysed '}
            {formatDateTime(result.created_at)}
            {details.holds_stock === true && ' · you hold this stock'}
            {details.holds_stock === false && ' · you do not hold this stock'}
          </p>
        </div>
        <ConfidenceRing value={result.confidence} level={result.confidence_level} />
      </div>

      <div className="mt-6">
        <LeanGauge lean={result.overall_lean} thresholds={details.thresholds} />
      </div>

      <div className="mt-6 rounded-xl bg-slate-50 p-4">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
              sourceIsAi ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-200 text-slate-700'
            }`}
          >
            {sourceIsAi ? <Bot size={12} /> : <FileText size={12} />}
            {explanationSourceLabel(result.explanation_source)}
          </span>
          {driver && (
            <span className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-0.5 text-xs font-medium text-slate-700 ring-1 ring-slate-200">
              <Star size={12} />
              Main factor: {AGENT_LABELS[driver.agent] || driver.label || driver.agent}
            </span>
          )}
        </div>
        <p className="leading-relaxed text-slate-800">{result.explanation}</p>
      </div>

      {result.conflicts?.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {result.conflicts.map((conflict) => (
            <span
              key={conflict}
              className="inline-flex items-start gap-1 rounded-xl bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-800 ring-1 ring-amber-200"
            >
              <AlertTriangle size={14} className="mt-px shrink-0" />
              {conflict}
            </span>
          ))}
        </div>
      )}

      <Disclaimer className="mt-4" />
    </Card>
  )
}
