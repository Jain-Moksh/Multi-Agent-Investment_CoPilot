import { Bot, ChevronRight, CloudOff, Crosshair, Globe, RotateCcw, ShieldAlert, ShieldCheck, ShieldX } from 'lucide-react'
import Markdown from './Markdown'
import { formatDateTime } from '../../utils/format'

const REFUSED_STATUSES = ['refused', 'refused_unverified']

const SHIELDS = {
  SAFE: {
    icon: ShieldCheck,
    label: 'Security scan passed',
    className: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  },
  SUSPICIOUS: {
    icon: ShieldAlert,
    label: 'Flagged as suspicious',
    className: 'bg-amber-50 text-amber-800 ring-amber-200',
  },
  BLOCKED: {
    icon: ShieldX,
    label: 'Blocked',
    className: 'bg-red-50 text-red-700 ring-red-200',
  },
}

function Badge({ icon: Icon, className, title, children }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${className}`}
    >
      {Icon && <Icon size={12} />}
      {children}
    </span>
  )
}

function ModeBadge({ meta }) {
  if (!meta) {
    return (
      <Badge className="bg-white text-slate-400 ring-slate-200" title="Mode is not stored with past messages">
        Mode -
      </Badge>
    )
  }
  if (meta.mode === 'symbol') {
    return (
      <Badge icon={Crosshair} className="bg-indigo-50 text-indigo-700 ring-indigo-200" title="Answered with your data for this stock">
        Grounded in {meta.detected_symbols.length ? meta.detected_symbols.join(', ') : '-'}
      </Badge>
    )
  }
  if (meta.mode === 'general') {
    return (
      <Badge icon={Globe} className="bg-slate-100 text-slate-600 ring-slate-200" title="No held stock was named">
        General
      </Badge>
    )
  }
  return null
}

function ShieldBadge({ verdict, reason }) {
  const shield = verdict && SHIELDS[verdict.toUpperCase()]
  if (!shield) return null
  return (
    <Badge icon={shield.icon} className={shield.className} title={reason || shield.label}>
      {shield.label}
    </Badge>
  )
}

function UsedPanel({ meta }) {
  const symbols = meta.detected_symbols || []
  const sources = meta.sources || []
  return (
    <details className="group mt-2 rounded-xl border border-slate-200 bg-slate-50 text-xs text-slate-600">
      <summary className="flex cursor-pointer list-none items-center gap-1 px-3 py-2 font-medium text-slate-700 hover:text-indigo-700">
        <ChevronRight size={14} className="transition group-open:rotate-90" />
        What did the assistant use?
      </summary>
      <div className="space-y-3 border-t border-slate-200 px-3 py-3">
        <div>
          <p className="mb-1 font-semibold text-slate-700">Mode</p>
          {meta.mode === 'symbol' ? (
            <p>Symbol mode: stock-specific lookups for the holdings you named.</p>
          ) : (
            <p>General mode: your overall profile and holdings overview, no stock-specific lookups.</p>
          )}
        </div>
        <div>
          <p className="mb-1 font-semibold text-slate-700">Held stocks detected</p>
          {symbols.length ? (
            <div className="flex flex-wrap gap-1">
              {symbols.map((symbol) => (
                <span key={symbol} className="rounded-md bg-white px-2 py-0.5 font-mono ring-1 ring-slate-200">
                  {symbol}
                </span>
              ))}
            </div>
          ) : (
            <p>None</p>
          )}
        </div>
        <div>
          <p className="mb-1 font-semibold text-slate-700">News articles shown to the AI</p>
          {sources.length ? (
            <ul className="space-y-1">
              {sources.map((source) => (
                <li key={source.news_event_id} className="flex gap-2">
                  <span className="shrink-0 font-mono text-slate-400">#{source.news_event_id}</span>
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-indigo-600 hover:underline"
                  >
                    {source.title}
                  </a>
                  {source.source_domain && <span className="shrink-0 text-slate-400">{source.source_domain}</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p>None</p>
          )}
        </div>
      </div>
    </details>
  )
}

function WarningBody({ tone, icon: Icon, title, children }) {
  const tones = {
    red: 'border-red-200 bg-red-50 text-red-800',
    amber: 'border-amber-200 bg-amber-50 text-amber-900',
  }
  return (
    <div className={`rounded-2xl rounded-tl-sm border px-4 py-3 text-sm ${tones[tone]}`}>
      <p className="mb-1 flex items-center gap-2 font-semibold">
        <Icon size={16} />
        {title}
      </p>
      {children}
    </div>
  )
}

function AssistantBody({ message, retryDisabled, onRetry }) {
  const { meta } = message
  const status = meta?.status
  const reason = meta?.security?.reason

  if (REFUSED_STATUSES.includes(status) || (!meta && message.inferredVerdict === 'blocked')) {
    return (
      <WarningBody tone="red" icon={ShieldX} title="Blocked by the security layer">
        {status === 'refused_unverified' && (
          <p className="mb-1">The safety check was unavailable, so this flagged message was not sent to the AI.</p>
        )}
        {reason && (
          <p className="mb-1">
            <span className="font-medium">Reason:</span> {reason}
          </p>
        )}
        <p className="text-red-700/80">{message.content}</p>
      </WarningBody>
    )
  }

  if (status === 'llm_unavailable') {
    return (
      <WarningBody tone="amber" icon={CloudOff} title="AI service temporarily unavailable">
        <p className="mb-2">
          The AI provider is out of quota or not responding right now. Your message was received; please try again in a
          minute.
        </p>
        {message.question && (
          <button
            type="button"
            onClick={() => onRetry(message.question)}
            disabled={retryDisabled}
            className="inline-flex items-center gap-1 rounded-lg border border-amber-300 bg-white px-3 py-1 text-xs font-medium text-amber-800 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RotateCcw size={12} />
            Retry
          </button>
        )}
      </WarningBody>
    )
  }

  if (status === 'blocked_output') {
    return (
      <WarningBody tone="red" icon={ShieldX} title="Reply withheld by the security layer">
        <p>{message.content}</p>
      </WarningBody>
    )
  }

  return (
    <div className="rounded-2xl rounded-tl-sm border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <Markdown>{message.content}</Markdown>
    </div>
  )
}

export function TypingIndicator() {
  return (
    <div className="flex items-start gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-white">
        <Bot size={16} />
      </div>
      <div className="rounded-2xl rounded-tl-sm border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <div className="flex items-center gap-1" aria-label="Assistant is typing">
          <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.3s]" />
          <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.15s]" />
          <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400" />
        </div>
        <p className="mt-1 text-[11px] text-slate-400">Thinking… this can take up to 30 seconds</p>
      </div>
    </div>
  )
}

export default function MessageBubble({ message, retryDisabled, onRetry }) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%]">
          <div className="whitespace-pre-wrap break-words rounded-2xl rounded-tr-sm bg-indigo-600 px-4 py-2.5 text-sm text-white shadow-sm">
            {message.content}
          </div>
          <p className="mt-1 text-right text-[11px] text-slate-400">{formatDateTime(message.created_at)}</p>
        </div>
      </div>
    )
  }

  const { meta } = message
  const verdict = meta?.security?.verdict || message.inferredVerdict
  const refused = REFUSED_STATUSES.includes(meta?.status) || (!meta && message.inferredVerdict === 'blocked')

  return (
    <div className="flex items-start gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-white">
        <Bot size={16} />
      </div>
      <div className="min-w-0 max-w-[85%] flex-1">
        <AssistantBody message={message} retryDisabled={retryDisabled} onRetry={onRetry} />
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {!refused && <ModeBadge meta={meta} />}
          <ShieldBadge verdict={verdict} reason={meta?.security?.reason} />
          <span className="text-[11px] text-slate-400">{formatDateTime(message.created_at)}</span>
        </div>
        {meta && !refused && <UsedPanel meta={meta} />}
      </div>
    </div>
  )
}
