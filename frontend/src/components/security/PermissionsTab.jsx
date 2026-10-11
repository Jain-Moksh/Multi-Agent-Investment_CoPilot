import { Lock } from 'lucide-react'
import Card from '../Card'
import EmptyState from '../EmptyState'
import AsyncBlock from './AsyncBlock'
import useApi from '../../hooks/useApi'
import { getPermissions } from '../../api/security'

function prettyAgent(name) {
  return name.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function Cell({ read, write }) {
  if (!read && !write) return <span className="text-slate-300">–</span>
  return (
    <span className="inline-flex gap-1">
      {read && (
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-emerald-100 text-xs font-bold text-emerald-700" title="Read">
          R
        </span>
      )}
      {write && (
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-orange-100 text-xs font-bold text-orange-700" title="Write">
          W
        </span>
      )}
    </span>
  )
}

export default function PermissionsTab() {
  const { data, loading, error, reload } = useApi(getPermissions)
  const agents = Object.keys(data || {})
  const tables = [
    ...new Set(agents.flatMap((agent) => [...(data[agent].read || []), ...(data[agent].write || [])])),
  ].sort()

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3 rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-900">
        <Lock size={18} className="mt-0.5 shrink-0" />
        <p>
          Every agent action is checked against this list in code, so even a tricked agent cannot act outside its scope.
          Anything not listed is denied, and each refused attempt is logged as an agent hijack event.
        </p>
      </div>

      <AsyncBlock loading={loading} error={error} onRetry={reload} label="Loading agent permissions">
        {data && agents.length === 0 && (
          <Card>
            <EmptyState icon={Lock} title="No agents registered" message="The permission list is empty." />
          </Card>
        )}
        {data && agents.length > 0 && (
          <Card
            title="Agent permission matrix"
            actions={
              <div className="flex items-center gap-3 text-xs text-slate-500">
                <span className="flex items-center gap-1">
                  <Cell read /> Read
                </span>
                <span className="flex items-center gap-1">
                  <Cell write /> Write
                </span>
                <span className="flex items-center gap-1">
                  <Cell /> None
                </span>
              </div>
            }
          >
            <div className="-mx-5 overflow-x-auto px-5">
              <table className="w-full border-separate border-spacing-0 text-sm">
                <thead>
                  <tr>
                    <th className="sticky left-0 z-10 bg-white px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Agent
                    </th>
                    {tables.map((table) => (
                      <th key={table} className="h-36 w-10 px-1 align-bottom">
                        <div className="mx-auto w-6 [writing-mode:vertical-rl] rotate-180 whitespace-nowrap text-left font-mono text-xs font-medium text-slate-600">
                          {table}
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {agents.map((agent) => {
                    const read = data[agent].read || []
                    const write = data[agent].write || []
                    return (
                      <tr key={agent} className="hover:bg-slate-50">
                        <td className="sticky left-0 z-10 whitespace-nowrap border-t border-slate-100 bg-white px-3 py-2.5">
                          <p className="font-medium text-slate-900">{prettyAgent(agent)}</p>
                          <p className="font-mono text-[11px] text-slate-400">
                            {agent} · {write.length ? `writes ${write.length}` : 'read-only'}
                          </p>
                        </td>
                        {tables.map((table) => (
                          <td key={table} className="border-t border-slate-100 px-1 py-2.5 text-center">
                            <Cell read={read.includes(table)} write={write.includes(table)} />
                          </td>
                        ))}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </AsyncBlock>
    </div>
  )
}
