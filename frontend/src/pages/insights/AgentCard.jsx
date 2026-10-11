import { Ban } from 'lucide-react'
import ConfidenceBar from '../../components/ConfidenceBar'
import { AGENT_LABELS, TONES, keyFacts, signed, statusInfo } from './helpers'

function SignalBar({ value }) {
  if (value === null || value === undefined) return <span className="text-sm text-slate-500">-</span>
  const number = Math.max(-1, Math.min(1, Number(value)))
  const width = `${Math.abs(number) * 50}%`
  const color = number > 0 ? 'bg-green-500' : number < 0 ? 'bg-red-500' : 'bg-slate-400'
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-2 w-24 rounded-full bg-slate-200" title="-1 bearish .. +1 bullish">
        <div className="absolute inset-y-0 left-1/2 w-px bg-slate-400" />
        <div
          className={`absolute inset-y-0 rounded-full ${color}`}
          style={number >= 0 ? { left: '50%', width } : { right: '50%', width }}
        />
      </div>
      <span className="text-xs font-medium text-slate-600">{signed(number)}</span>
    </div>
  )
}

export default function AgentCard({ agent, data, excludedReason }) {
  const info = statusInfo(data?.status)
  const facts = keyFacts(agent, data?.facts)
  const isProfile = agent === 'user_profiling_agent'
  return (
    <div
      className={`flex flex-col rounded-2xl border p-4 ${
        excludedReason ? 'border-dashed border-slate-300 bg-slate-50' : 'border-slate-200 bg-white'
      }`}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <h3 className="font-semibold text-slate-900">{AGENT_LABELS[agent]}</h3>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${TONES[info.tone]}`}>{info.label}</span>
      </div>

      {!data ? (
        <p className="text-sm text-slate-500">This agent produced no output for this analysis.</p>
      ) : (
        <>
          <div className="mb-3 grid grid-cols-2 gap-2 text-xs text-slate-500">
            <div>
              <p className="mb-1">{isProfile ? 'Signal (not a vote)' : 'Signal'}</p>
              <SignalBar value={data.signal} />
            </div>
            <div>
              <p className="mb-1">Confidence</p>
              <ConfidenceBar value={data.confidence} />
            </div>
          </div>
          {facts.length > 0 && (
            <div className="mb-3 flex flex-wrap gap-1.5">
              {facts.map((fact) => (
                <span key={fact.key} className="rounded-lg bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
                  {fact.text}
                </span>
              ))}
            </div>
          )}
          <p className="text-sm leading-relaxed text-slate-700">{data.summary || '-'}</p>
        </>
      )}

      {info.text && <p className="mt-3 text-xs text-slate-500">{info.text}</p>}
      {isProfile && (
        <p className="mt-3 text-xs text-slate-500">This agent does not vote; your risk profile changes how much the others weigh.</p>
      )}
      {excludedReason && (
        <p className="mt-3 inline-flex items-start gap-1 text-xs font-medium text-slate-600">
          <Ban size={14} className="mt-px shrink-0" />
          Not used in the decision ({excludedReason})
        </p>
      )}
    </div>
  )
}
