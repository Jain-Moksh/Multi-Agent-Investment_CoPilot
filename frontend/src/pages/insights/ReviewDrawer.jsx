import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ArrowUpRight,
  Ban,
  Bot,
  CircleCheck,
  CircleX,
  Clock,
  FileText,
  Gauge,
  Lightbulb,
  ListChecks,
  Scale,
  Star,
  TriangleAlert,
  Users,
  X,
} from 'lucide-react'
import { getErrorMessage } from '../../api/client'
import { getRecommendation } from '../../api/recommendations'
import DecisionBadge from '../../components/DecisionBadge'
import Disclaimer from '../../components/Disclaimer'
import ErrorBanner from '../../components/ErrorBanner'
import { formatDateTime } from '../../utils/format'
import AgentCard from './AgentCard'
import { ConfidenceStrip } from './ExplainPanel'
import { ConfidenceRing, LeanGauge } from './ResultCard'
import {
  AGENT_LABELS,
  AGENT_ORDER,
  TONES,
  decisionRule,
  explanationSourceLabel,
  percentText,
  signed,
  statusInfo,
} from './helpers'

const CLOSE_MS = 250
const DIRECTIONAL = AGENT_ORDER.filter((agent) => agent !== 'user_profiling_agent')

const HERO = {
  buy: 'from-green-50 to-white ring-green-200',
  hold: 'from-amber-50 to-white ring-amber-200',
  sell: 'from-red-50 to-white ring-red-200',
}

function Section({ icon: Icon, title, subtitle, children }) {
  return (
    <section className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <div className="mb-4 flex items-start gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
          <Icon size={16} />
        </span>
        <div>
          <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
        </div>
      </div>
      {children}
    </section>
  )
}

function Stat({ label, value, tone = 'text-slate-900' }) {
  return (
    <div className="rounded-xl bg-white/70 px-3 py-2 ring-1 ring-slate-200">
      <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-0.5 text-sm font-semibold ${tone}`}>{value}</p>
    </div>
  )
}

function DivergingBar({ value }) {
  const number = Math.max(-1, Math.min(1, Number(value) || 0))
  const width = `${Math.abs(number) * 50}%`
  const color = number > 0 ? 'bg-green-500' : number < 0 ? 'bg-red-500' : 'bg-slate-300'
  return (
    <div className="relative h-2 w-full rounded-full bg-slate-100">
      <div className="absolute inset-y-0 left-1/2 w-px bg-slate-300" />
      <div
        className={`absolute inset-y-0 rounded-full ${color}`}
        style={number >= 0 ? { left: '50%', width } : { right: '50%', width }}
      />
    </div>
  )
}

function Contributions({ result }) {
  const agreement = result.details?.agreement || {}
  const excluded = result.excluded || agreement.excluded || {}
  const agents = result.agents || {}
  const driver = result.main_driver?.agent
  const rows = DIRECTIONAL.map((agent) => {
    const lean = agreement.leans?.[agent] ?? agents[agent]?.signal ?? null
    const weight = agreement.weights?.[agent] ?? null
    const contribution = lean !== null && weight !== null ? lean * weight : null
    return { agent, lean, weight, contribution, status: agents[agent]?.status, excluded: excluded[agent] }
  }).sort((a, b) => Math.abs(b.contribution ?? 0) - Math.abs(a.contribution ?? 0))

  return (
    <div className="space-y-3">
      {rows.map((row) => {
        const info = statusInfo(row.status)
        return (
          <div
            key={row.agent}
            className={`rounded-xl px-3 py-3 ${
              row.excluded
                ? 'border border-dashed border-slate-300 bg-slate-50'
                : row.agent === driver
                  ? 'bg-indigo-50/60 ring-1 ring-indigo-200'
                  : 'ring-1 ring-slate-200'
            }`}
          >
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-slate-900">{AGENT_LABELS[row.agent]}</span>
                {row.agent === driver && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-indigo-600 px-2 py-0.5 text-[11px] font-semibold text-white">
                    <Star size={10} />
                    Main factor
                  </span>
                )}
                {row.status && row.status !== 'ok' && (
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${TONES[info.tone]}`}>{info.label}</span>
                )}
              </div>
              <span
                className={`font-mono text-sm font-semibold ${
                  (row.contribution ?? 0) > 0 ? 'text-green-700' : (row.contribution ?? 0) < 0 ? 'text-red-700' : 'text-slate-500'
                }`}
              >
                {row.contribution === null ? '-' : signed(row.contribution, 3)}
              </span>
            </div>
            <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 text-xs text-slate-500">
              <DivergingBar value={row.lean} />
              <span className="w-24 text-right">Lean {signed(row.lean)}</span>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                <div className="h-full rounded-full bg-sky-500" style={{ width: percentText(row.weight ?? 0) }} />
              </div>
              <span className="w-24 text-right">Weight {percentText(row.weight)}</span>
            </div>
            {row.excluded && (
              <p className="mt-2 inline-flex items-start gap-1 text-xs text-slate-500">
                <Ban size={12} className="mt-0.5 shrink-0" />
                Not used in the decision ({row.excluded})
              </p>
            )}
          </div>
        )
      })}
      <p className="text-xs text-slate-500">
        Contribution = lean × weight. Positive values pushed towards Buy, negative values towards Sell.
      </p>
    </div>
  )
}

function DecisionChecks({ rule }) {
  return (
    <div className="space-y-2">
      {rule.checks.map((check) => (
        <div key={check.title} className="flex items-start gap-3 rounded-xl px-3 py-2.5 ring-1 ring-slate-200">
          {check.met ? (
            <CircleCheck size={18} className="mt-0.5 shrink-0 text-green-600" />
          ) : (
            <CircleX size={18} className="mt-0.5 shrink-0 text-slate-400" />
          )}
          <div>
            <p className="text-sm font-medium text-slate-900">{check.title}</p>
            <p className="text-xs text-slate-500">{check.text}</p>
          </div>
        </div>
      ))}
      <div className="rounded-xl bg-[#0f172a] px-4 py-3 text-sm text-white">{rule.conclusion}</div>
    </div>
  )
}

function LoadingState() {
  return (
    <div className="space-y-4" role="status" aria-label="Loading the review">
      {[160, 120, 220, 180].map((height) => (
        <div key={height} className="animate-pulse rounded-2xl bg-white p-5 ring-1 ring-slate-200">
          <div className="mb-3 h-4 w-40 rounded bg-slate-200" />
          <div className="rounded-xl bg-slate-100" style={{ height }} />
        </div>
      ))}
    </div>
  )
}

function ReviewBody({ result }) {
  const details = result.details
  const agreement = details?.agreement || {}
  const excluded = result.excluded || agreement.excluded || {}
  const agents = result.agents || {}
  const key = String(result.decision || '').toLowerCase()
  const rule = decisionRule(result)
  const driver = result.main_driver
  const sourceIsAi = result.explanation_source === 'llm'
  const timings = details?.timings_ms || {}
  const agentErrors = details?.agent_errors || {}
  const usedCount = DIRECTIONAL.filter((agent) => !excluded[agent]).length

  return (
    <div className="space-y-5">
      <section className={`rounded-2xl bg-gradient-to-br p-5 ring-1 ${HERO[key] || 'from-slate-50 to-white ring-slate-200'}`}>
        <div className="flex flex-col items-center gap-5 sm:flex-row">
          <ConfidenceRing value={result.confidence} level={result.confidence_level} />
          <div className="grid w-full min-w-0 grid-cols-2 gap-2 sm:flex-1">
            <Stat label="Decision" value={result.decision_label || result.decision || '-'} />
            <Stat
              label="Overall lean"
              value={signed(result.overall_lean)}
              tone={result.overall_lean > 0 ? 'text-green-700' : result.overall_lean < 0 ? 'text-red-700' : 'text-slate-900'}
            />
            <Stat label="Agents used" value={`${usedCount} of ${DIRECTIONAL.length}`} />
            <Stat
              label="Position"
              value={details?.holds_stock === true ? 'You hold it' : details?.holds_stock === false ? 'Not held' : '-'}
            />
          </div>
        </div>
        <div className="mt-5">
          <LeanGauge lean={result.overall_lean} thresholds={details?.thresholds} />
        </div>
      </section>

      <Section icon={Lightbulb} title="Why this judgement" subtitle="The explanation saved with this analysis">
        <span
          className={`mb-3 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
            sourceIsAi ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-200 text-slate-700'
          }`}
        >
          {sourceIsAi ? <Bot size={12} /> : <FileText size={12} />}
          {explanationSourceLabel(result.explanation_source)}
        </span>
        <p className="text-sm leading-relaxed text-slate-700">{result.explanation || '-'}</p>
        {driver && (
          <div className="mt-4 rounded-xl border-l-4 border-indigo-500 bg-indigo-50/60 px-4 py-3">
            <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-indigo-700">
              <Star size={12} />
              Main factor: {AGENT_LABELS[driver.agent] || driver.label || driver.agent}
            </p>
            <p className="mt-1 text-xs text-slate-600">
              Lean {signed(driver.lean)}
              {driver.contribution !== undefined && driver.contribution !== null && ` · contribution ${signed(driver.contribution, 3)}`}
            </p>
            {driver.summary && <p className="mt-2 text-sm text-slate-700">{driver.summary}</p>}
          </div>
        )}
      </Section>

      {rule && (
        <Section icon={ListChecks} title="How the decision rule applied" subtitle="Buy or Sell needs a strong lean and enough confidence">
          <DecisionChecks rule={rule} />
        </Section>
      )}

      {result.conflicts?.length > 0 && (
        <Section icon={TriangleAlert} title="Conflicting signals" subtitle="Where the agents disagreed">
          <ul className="space-y-2">
            {result.conflicts.map((conflict) => (
              <li key={conflict} className="flex items-start gap-2 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-900 ring-1 ring-amber-200">
                <TriangleAlert size={14} className="mt-0.5 shrink-0" />
                {conflict}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section icon={Scale} title="What moved the decision" subtitle="Each agent's lean, its weight, and the resulting push">
        {details ? (
          <Contributions result={result} />
        ) : (
          <p className="text-sm text-slate-500">Weights were not saved for this older analysis.</p>
        )}
      </Section>

      {details && (
        <Section icon={Gauge} title="How confident the system is" subtitle="Confidence = agreement × evidence">
          <ConfidenceStrip agreement={agreement} confidence={result.confidence} thresholds={details.thresholds} title={null} />
        </Section>
      )}

      <Section icon={Users} title="What each agent found" subtitle="Summaries and key numbers from all five agents">
        <div className="space-y-3">
          {AGENT_ORDER.map((agent) => (
            <AgentCard key={agent} agent={agent} data={agents[agent]} excludedReason={excluded[agent]} />
          ))}
        </div>
      </Section>

      {(timings.total || Object.keys(agentErrors).length > 0) && (
        <Section icon={Clock} title="Run details">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
            {timings.total && (
              <div>
                <dt className="text-xs text-slate-500">Total time</dt>
                <dd className="font-medium text-slate-900">{(timings.total / 1000).toFixed(1)} s</dd>
              </div>
            )}
            {AGENT_ORDER.filter((agent) => timings[agent] !== undefined).map((agent) => (
              <div key={agent}>
                <dt className="text-xs text-slate-500">{AGENT_LABELS[agent]}</dt>
                <dd className="font-medium text-slate-900">{(timings[agent] / 1000).toFixed(1)} s</dd>
              </div>
            ))}
          </dl>
          {Object.keys(agentErrors).length > 0 && (
            <ul className="mt-4 space-y-1 text-xs text-red-700">
              {Object.entries(agentErrors).map(([agent, message]) => (
                <li key={agent}>
                  {AGENT_LABELS[agent] || agent}: {String(message)}
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}
    </div>
  )
}

export default function ReviewDrawer({ id, onClose, onShowOnPage }) {
  const [shown, setShown] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const closeRef = useRef(null)
  const closingRef = useRef(false)

  const close = useCallback(() => {
    if (closingRef.current) return
    closingRef.current = true
    setShown(false)
    setTimeout(onClose, CLOSE_MS)
  }, [onClose])

  useEffect(() => {
    const frame = requestAnimationFrame(() => setShown(true))
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeRef.current?.focus()
    return () => {
      cancelAnimationFrame(frame)
      document.body.style.overflow = previousOverflow
    }
  }, [])

  useEffect(() => {
    function handleKey(event) {
      if (event.key === 'Escape') close()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [close])

  useEffect(() => {
    let active = true
    getRecommendation(id)
      .then((data) => {
        if (!active) return
        setResult(data)
        setError('')
      })
      .catch((err) => {
        if (active) setError(getErrorMessage(err, 'Could not load this analysis.'))
      })
    return () => {
      active = false
    }
  }, [id, attempt])

  return (
    <div className="fixed inset-0 z-50" role="presentation">
      <div
        className={`absolute inset-0 bg-slate-900/50 backdrop-blur-[2px] transition-opacity duration-300 ${shown ? 'opacity-100' : 'opacity-0'}`}
        onMouseDown={close}
        aria-hidden="true"
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-drawer-title"
        className={`absolute inset-y-0 right-0 flex w-full flex-col bg-slate-50 shadow-2xl transition-transform duration-300 ease-out sm:max-w-xl lg:max-w-2xl ${
          shown ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <header className="flex items-start justify-between gap-4 border-b border-slate-200 bg-white px-6 py-4">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-indigo-600">Detail review</p>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <h2 id="review-drawer-title" className="truncate text-xl font-semibold text-slate-900">
                {result?.symbol || 'Loading…'}
              </h2>
              {result && <DecisionBadge decision={result.decision} label={result.decision_label} />}
            </div>
            {result && (
              <p className="mt-0.5 text-sm text-slate-500">
                {result.company_name ? `${result.company_name} · ` : ''}
                {formatDateTime(result.created_at)}
              </p>
            )}
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={close}
            aria-label="Close detail review"
            className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300"
          >
            <X size={20} />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-5 sm:px-6">
          {error && <ErrorBanner message={error} onRetry={() => { setError(''); setAttempt((n) => n + 1) }} />}
          {!error && !result && <LoadingState />}
          {!error && result && <ReviewBody result={result} />}
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-white px-6 py-3">
          <Disclaimer />
          <div className="flex gap-2">
            {result && onShowOnPage && (
              <button
                type="button"
                onClick={() => {
                  onShowOnPage(result)
                  close()
                }}
                className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                <ArrowUpRight size={16} />
                Show on page
              </button>
            )}
            <button
              type="button"
              onClick={close}
              className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
            >
              Close
            </button>
          </div>
        </footer>
      </aside>
    </div>
  )
}
