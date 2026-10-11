import { CalendarClock, IndianRupee, TrendingUp, Wallet } from 'lucide-react'
import StatCard from '../StatCard'
import { formatINR, formatPct, plClass } from '../../utils/format'

export default function SummaryCards({ totals }) {
  const todays = totals?.todays_pl
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard label="Total invested" value={formatINR(totals?.total_invested)} icon={Wallet} />
      <StatCard label="Current value" value={formatINR(totals?.total_current_value)} icon={IndianRupee} />
      <StatCard
        label="Total P/L"
        value={formatINR(totals?.total_pl)}
        valueClass={plClass(totals?.total_pl)}
        sub={<span className={plClass(totals?.total_pl_pct)}>{formatPct(totals?.total_pl_pct)}</span>}
        icon={TrendingUp}
      />
      <StatCard
        label="Today's P/L"
        value={todays === null || todays === undefined ? 'n/a' : formatINR(todays)}
        valueClass={todays === null || todays === undefined ? 'text-slate-400' : plClass(todays)}
        icon={CalendarClock}
      />
    </div>
  )
}
