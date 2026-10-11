import { Briefcase, CalendarClock, Layers, TrendingUp } from 'lucide-react'
import Card from '../../components/Card'
import ErrorBanner from '../../components/ErrorBanner'
import { formatINR, formatPct } from '../../utils/format'
import { plClass, signedINR } from './helpers'

function Kpi({ icon: Icon, label, request, render }) {
  let body
  if (request.loading && !request.data) {
    body = <div className="h-8 w-32 animate-pulse rounded-lg bg-slate-100" />
  } else if (request.error) {
    body = <ErrorBanner message={request.error} onRetry={request.reload} />
  } else if (request.data) {
    body = render(request.data)
  } else {
    body = <p className="text-2xl font-semibold text-slate-900">-</p>
  }
  return (
    <Card>
      <div className="mb-3 flex items-center gap-2 text-sm text-slate-500">
        <Icon size={16} />
        {label}
      </div>
      {body}
    </Card>
  )
}

export default function KpiCards({ summary }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Kpi
        icon={Briefcase}
        label="Total portfolio value"
        request={summary}
        render={({ totals }) => (
          <>
            <p className="text-2xl font-semibold text-slate-900">{formatINR(totals.total_current_value)}</p>
            <p className="mt-1 text-xs text-slate-500">Invested {formatINR(totals.total_invested)}</p>
          </>
        )}
      />
      <Kpi
        icon={CalendarClock}
        label="Today's P/L"
        request={summary}
        render={({ totals }) => (
          <>
            <p className={`text-2xl font-semibold ${plClass(totals.todays_pl)}`}>{signedINR(totals.todays_pl)}</p>
            <p className="mt-1 text-xs text-slate-500">
              {totals.todays_pl === null ? 'No price change available today' : 'From the latest price change'}
            </p>
          </>
        )}
      />
      <Kpi
        icon={TrendingUp}
        label="Overall return"
        request={summary}
        render={({ totals }) => (
          <>
            <p className={`text-2xl font-semibold ${plClass(totals.total_pl)}`}>{signedINR(totals.total_pl)}</p>
            <p className={`mt-1 text-xs font-medium ${plClass(totals.total_pl_pct)}`}>{formatPct(totals.total_pl_pct)}</p>
          </>
        )}
      />
      <Kpi
        icon={Layers}
        label="Holdings"
        request={summary}
        render={(data) => (
          <>
            <p className="text-2xl font-semibold text-slate-900">{data.holdings_count}</p>
            <p className="mt-1 text-xs text-slate-500">{data.priced_holdings} with a live price</p>
          </>
        )}
      />
    </div>
  )
}
