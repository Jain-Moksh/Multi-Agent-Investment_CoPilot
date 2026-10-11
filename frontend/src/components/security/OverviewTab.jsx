import { Activity, Database, FileWarning, Newspaper, ShieldBan, ShieldCheck, ShieldHalf } from 'lucide-react'
import Card from '../Card'
import StatCard from '../StatCard'
import AsyncBlock from './AsyncBlock'
import { EVENT_TYPES } from './SecurityBadges'
import useApi from '../../hooks/useApi'
import { getSecurityStats } from '../../api/security'

const LAYERS = [
  {
    icon: ShieldHalf,
    title: 'Layer 1: Prompt Injection and Agent Hijacking Defense',
    accent: 'bg-violet-100 text-violet-700',
    points: [
      'Every chat message and news article is scanned by a text scanner: fast rule patterns first, then an LLM classifier only when a rule matches.',
      'BLOCKED text never reaches the assistant or the agents; SUSPICIOUS text gets a restricted, general answer.',
      'Agent permission checks: each agent may only read and write the tables on its allow-list, enforced in code before any database call.',
    ],
  },
  {
    icon: Database,
    title: 'Layer 2: RAG Poisoning Detection',
    accent: 'bg-sky-100 text-sky-700',
    points: [
      'Source trust: articles are weighed by how trusted their source domain is.',
      'Duplicate-cluster detection: many near-identical stories pushing the same claim are treated as a coordinated campaign.',
      'Quarantine before the vector database: flagged articles are moved aside and never embedded, so the agents cannot retrieve them.',
    ],
  },
]

export default function OverviewTab() {
  const { data, loading, error, reload } = useApi(getSecurityStats)
  const byType = data?.events_by_type || {}
  const maxType = Math.max(1, ...Object.values(byType))

  return (
    <div className="space-y-6">
      <AsyncBlock loading={loading} error={error} onRetry={reload} label="Loading security stats">
        {data && (
          <>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard label="Security events" value={data.events_total} icon={Activity} sub={<span className="text-slate-500">All types, all time</span>} />
              <StatCard label="Blocked" value={data.blocked_count} valueClass="text-red-600" icon={ShieldBan} sub={<span className="text-slate-500">Events where the action was stopped</span>} />
              <StatCard label="Quarantined articles" value={data.quarantine_count} valueClass="text-amber-600" icon={FileWarning} sub={<span className="text-slate-500">Kept out of the vector database</span>} />
              <StatCard label="SAFE articles" value={data.safe_news_count} valueClass="text-emerald-600" icon={Newspaper} sub={<span className="text-slate-500">Passed the scan, visible to agents</span>} />
            </div>

            <Card title="Events by type">
              <div className="space-y-3">
                {Object.keys({ ...EVENT_TYPES, ...byType }).map((type) => {
                  const count = byType[type] ?? 0
                  return (
                    <div key={type} className="grid grid-cols-[140px_1fr_48px] items-center gap-3 text-sm">
                      <span className="text-slate-700">{EVENT_TYPES[type]?.label || type}</span>
                      <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
                        <div className="h-full rounded-full bg-indigo-500" style={{ width: `${(count / maxType) * 100}%` }} />
                      </div>
                      <span className="text-right font-semibold text-slate-900">{count}</span>
                    </div>
                  )
                })}
              </div>
            </Card>
          </>
        )}
      </AsyncBlock>

      <div className="grid gap-4 lg:grid-cols-2">
        {LAYERS.map(({ icon: Icon, title, accent, points }) => (
          <Card key={title}>
            <div className="mb-3 flex items-center gap-3">
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${accent}`}>
                <Icon size={20} />
              </div>
              <h3 className="text-base font-semibold text-slate-900">{title}</h3>
            </div>
            <ul className="space-y-2 text-sm text-slate-600">
              {points.map((point) => (
                <li key={point} className="flex gap-2">
                  <ShieldCheck size={16} className="mt-0.5 shrink-0 text-emerald-500" />
                  {point}
                </li>
              ))}
            </ul>
          </Card>
        ))}
      </div>
    </div>
  )
}
