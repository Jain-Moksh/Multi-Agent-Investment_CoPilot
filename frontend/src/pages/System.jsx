import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, ClipboardCopy, ExternalLink, Loader2, Play, RefreshCw } from 'lucide-react'
import { API_URL } from '../api/client'
import Button from '../components/Button'
import Card from '../components/Card'
import PageHeader from '../components/PageHeader'
import { useToast } from '../components/Toast'
import { formatDateTime } from '../utils/format'
import { CHECKS, GROUPS, STATUS_STYLE, createContext, errorResult, markdownReport, summarize, summaryLine } from './system/checks'

const CHEAP_IDS = CHECKS.filter((check) => !check.expensive).map((check) => check.id)

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  const area = document.createElement('textarea')
  area.value = text
  document.body.appendChild(area)
  area.select()
  document.execCommand('copy')
  document.body.removeChild(area)
}

function StatusChip({ result, running }) {
  if (running) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-700">
        <Loader2 size={12} className="animate-spin" />
        Running
      </span>
    )
  }
  if (!result) return <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-500">Not run</span>
  const style = STATUS_STYLE[result.status]
  return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${style.className}`}>{style.label}</span>
}

export default function System() {
  const toast = useToast()
  const [results, setResults] = useState({})
  const [running, setRunning] = useState({})
  const [lastRun, setLastRun] = useState(null)

  const run = useCallback(async (ids) => {
    const ctx = createContext()
    setRunning((current) => ({ ...current, ...Object.fromEntries(ids.map((id) => [id, true])) }))
    await Promise.all(
      CHECKS.filter((check) => ids.includes(check.id)).map(async (check) => {
        let result
        try {
          result = await check.run(ctx)
        } catch (error) {
          result = errorResult(error)
        }
        setResults((current) => ({ ...current, [check.id]: { ...result, ranAt: new Date().toISOString() } }))
        setRunning((current) => ({ ...current, [check.id]: false }))
      }),
    )
    setLastRun(new Date().toISOString())
  }, [])

  useEffect(() => {
    run(CHEAP_IDS)
  }, [run])

  const counts = summarize(results)
  const anyRunning = Object.values(running).some(Boolean)

  async function copyReport() {
    try {
      await copyText(markdownReport(results, formatDateTime(lastRun || new Date().toISOString())))
      toast.success('Report copied to the clipboard as a markdown table.')
    } catch {
      toast.error('Could not copy to the clipboard.')
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="System Check"
        subtitle="What works right now, checked live against the backend."
        actions={
          <>
            <Button icon={RefreshCw} onClick={() => run(CHEAP_IDS)} loading={CHEAP_IDS.some((id) => running[id])}>
              Run all checks
            </Button>
            <Button variant="secondary" icon={ClipboardCopy} onClick={copyReport} disabled={anyRunning}>
              Copy report
            </Button>
          </>
        }
      />

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-base font-semibold text-slate-900">
            <span className="text-green-700">{counts.working} working</span>,{' '}
            <span className="text-amber-700">{counts.partial} partial</span>,{' '}
            <span className="text-slate-600">{counts.not_built} not built</span>,{' '}
            <span className="text-red-700">{counts.failing} failing</span>
          </p>
          <p className="text-xs text-slate-500">
            {anyRunning ? 'Running checks...' : lastRun ? `Last run ${formatDateTime(lastRun)}` : ''}
            <span className="sr-only">{summaryLine(counts)}</span>
          </p>
        </div>
      </Card>

      {GROUPS.map((group) => (
        <Card key={group} title={group}>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                  <th className="py-2 pr-4 font-medium">Check</th>
                  <th className="py-2 pr-4 font-medium">Endpoint</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 font-medium">Detail</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {CHECKS.filter((check) => check.group === group).map((check) => (
                  <tr key={check.id} className="align-top">
                    <td className="py-3 pr-4 font-medium text-slate-900">
                      {check.name}
                      {check.expensive && (
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <Button
                            size="sm"
                            variant="secondary"
                            icon={Play}
                            loading={running[check.id]}
                            onClick={() => run([check.id])}
                          >
                            Run
                          </Button>
                          <span className="inline-flex items-center gap-1 text-xs font-normal text-amber-700">
                            <AlertTriangle size={12} />
                            uses AI quota
                          </span>
                        </div>
                      )}
                    </td>
                    <td className="py-3 pr-4">
                      <code className="whitespace-nowrap rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700">{check.endpoint}</code>
                    </td>
                    <td className="py-3 pr-4">
                      <StatusChip result={results[check.id]} running={running[check.id]} />
                    </td>
                    <td className="py-3 text-slate-600">{results[check.id]?.detail || (check.expensive ? 'Not run (press Run).' : '-')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}

      <Card title="Developer tools">
        <a
          href={`${API_URL}/debug/trace`}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 text-sm font-medium text-indigo-600 hover:underline"
        >
          Open the news ingestion trace page
          <ExternalLink size={14} />
        </a>
        <p className="mt-1 text-xs text-slate-500">
          Development only: works when the backend runs with ENVIRONMENT=development and is opened from this computer.
        </p>
      </Card>
    </div>
  )
}
