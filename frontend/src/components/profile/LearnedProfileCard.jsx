import { Brain, Info } from 'lucide-react'
import Card from '../Card'
import EmptyState from '../EmptyState'
import { formatDateTime, formatNumber } from '../../utils/format'
import { BASIS_LABELS, HORIZON_OPTIONS, MIN_TRADES, RISK_OPTIONS, optionLabel } from '../../utils/profile'

function present(value) {
  return value !== null && value !== undefined
}

function Metric({ label, value }) {
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-base font-semibold text-slate-900">{value}</p>
    </div>
  )
}

function Classification({ label, value, basis }) {
  return (
    <div className="rounded-xl border border-slate-200 p-4">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold text-slate-900">{value}</p>
      <p className="mt-1 text-xs text-slate-500">Based on: {BASIS_LABELS[basis] || '-'}</p>
    </div>
  )
}

export default function LearnedProfileCard({ profile }) {
  const metrics = profile?.behavior_metrics || {}
  const basis = profile?.profile_basis || {}
  const classified = Boolean(profile?.classified_at)
  const trades = metrics.transactions_count
  const insufficient = classified && (!present(trades) || trades < MIN_TRADES)

  if (!classified) {
    return (
      <Card title="What the system learned about you">
        <EmptyState
          icon={Brain}
          title="Not classified yet"
          message="The system classifies you the first time you run an analysis on the AI Insights page. Import your trade history or add holdings so it can learn your behaviour."
        />
      </Card>
    )
  }

  const pct = (value) => (present(value) ? `${formatNumber(value, 1)}%` : '-')

  return (
    <Card
      title="What the system learned about you"
      actions={<span className="text-xs text-slate-500">Classified {formatDateTime(profile.classified_at)}</span>}
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Classification
          label="Risk appetite"
          value={optionLabel(RISK_OPTIONS, profile.risk_appetite)}
          basis={basis.risk}
        />
        <Classification
          label="Investment horizon"
          value={optionLabel(HORIZON_OPTIONS, profile.investment_horizon)}
          basis={basis.horizon}
        />
      </div>

      {insufficient && (
        <div className="mt-4 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <Info size={18} className="mt-0.5 shrink-0" />
          <p>
            Only {present(trades) ? trades : 0} trade{trades === 1 ? '' : 's'} on record (at least {MIN_TRADES} are
            needed). Import your trade history or add holdings so the system can learn your behaviour.
          </p>
        </div>
      )}

      <h3 className="mb-2 mt-5 text-sm font-medium text-slate-700">Behaviour metrics</h3>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
        <Metric
          label="Trades per month"
          value={present(metrics.trades_per_month) ? formatNumber(metrics.trades_per_month, 2) : '-'}
        />
        <Metric
          label="Average holding period"
          value={present(metrics.avg_holding_days) ? `${formatNumber(metrics.avg_holding_days, 1)} days` : '-'}
        />
        <Metric label="Quick flips (sold within 30 days)" value={pct(metrics.quick_flip_pct)} />
        <Metric label="Equity share" value={pct(metrics.equity_share_pct)} />
        <Metric label="Largest position" value={pct(metrics.max_position_pct)} />
        <Metric label="Distinct stocks" value={present(metrics.distinct_stocks) ? metrics.distinct_stocks : '-'} />
      </div>
      <p className="mt-3 text-xs text-slate-400">
        Shares are measured at cost. Trades on record: {present(trades) ? trades : '-'}.
      </p>
    </Card>
  )
}
