import { DatabaseZap, ExternalLink, ShieldCheck } from 'lucide-react'
import Card from '../Card'
import EmptyState from '../EmptyState'
import AsyncBlock from './AsyncBlock'
import useApi from '../../hooks/useApi'
import { getQuarantine } from '../../api/security'
import { formatDateTime, timeAgo } from '../../utils/format'

export default function QuarantineTab() {
  const { data, loading, error, reload } = useApi(() => getQuarantine({ limit: 100 }))

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3 rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">
        <DatabaseZap size={18} className="mt-0.5 shrink-0" />
        <p>
          Quarantined articles never enter the vector database and are never seen by the agents. They are kept here only
          for review, with the reason they were pulled.
        </p>
      </div>

      <AsyncBlock loading={loading} error={error} onRetry={reload} label="Loading quarantine">
        {data && data.length === 0 && (
          <Card>
            <EmptyState icon={ShieldCheck} title="Quarantine is empty" message="No articles have been flagged as poisoned so far." />
          </Card>
        )}
        {data && data.length > 0 && (
          <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Title</th>
                    <th className="px-4 py-3">Source domain</th>
                    <th className="px-4 py-3">Reason</th>
                    <th className="px-4 py-3">Quarantined</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.map((item) => (
                    <tr key={item.id} className="align-top hover:bg-slate-50">
                      <td className="max-w-sm px-4 py-3">
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="group font-medium text-slate-900 hover:text-indigo-700"
                        >
                          {item.title}
                          <ExternalLink size={12} className="ml-1 inline text-slate-400 group-hover:text-indigo-600" />
                        </a>
                        {item.affected_symbols.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {item.affected_symbols.map((symbol) => (
                              <span key={symbol} className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
                                {symbol}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-slate-600">{item.source_domain || '-'}</td>
                      <td className="max-w-md px-4 py-3 text-slate-700">{item.quarantine_reason}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-slate-600" title={formatDateTime(item.quarantined_at)}>
                        {timeAgo(item.quarantined_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </AsyncBlock>
    </div>
  )
}
