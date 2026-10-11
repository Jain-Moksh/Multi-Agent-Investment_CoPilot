import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Legend, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import Card from '../../components/Card'
import AgentCard from './AgentCard'
import { AGENT_LABELS, AGENT_ORDER, signed } from './helpers'

const DIRECTIONAL = AGENT_ORDER.filter((agent) => agent !== 'user_profiling_agent')

function percent(value) {
  return value === null || value === undefined ? '-' : `${Math.round(Number(value) * 100)}%`
}

function LeanWeightChart({ agreement, excluded }) {
  const data = DIRECTIONAL.map((agent) => ({
    name: AGENT_LABELS[agent] + (excluded[agent] ? ' (not used)' : ''),
    lean: agreement.leans?.[agent] ?? 0,
    weight: agreement.weights?.[agent] ?? 0,
  }))
  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ left: 0, right: 8 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="name" fontSize={11} interval={0} />
          <YAxis domain={[-1, 1]} fontSize={11} />
          <ReferenceLine y={0} stroke="#94a3b8" />
          <Tooltip formatter={(value, name) => (name === 'Weight' ? percent(value) : signed(value))} />
          <Legend />
          <Bar dataKey="lean" name="Lean (-1 bearish .. +1 bullish)" fill="#4f46e5" isAnimationActive={false} />
          <Bar dataKey="weight" name="Weight" fill="#0ea5e9" isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function TimingsChart({ timings }) {
  const data = AGENT_ORDER.filter((agent) => timings[agent] !== undefined).map((agent) => ({
    name: AGENT_LABELS[agent],
    seconds: Math.round(timings[agent] / 100) / 10,
  }))
  return (
    <div style={{ height: Math.max(140, data.length * 36) }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24 }}>
          <XAxis type="number" fontSize={11} unit=" s" />
          <YAxis type="category" dataKey="name" width={150} fontSize={11} />
          <Tooltip formatter={(value) => [`${value} s`, 'Time']} />
          <Bar dataKey="seconds" fill="#8b5cf6" radius={[0, 6, 6, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function ConfidenceStrip({ agreement, confidence, thresholds }) {
  return (
    <div className="rounded-xl bg-slate-50 p-4">
      <h3 className="mb-3 text-sm font-semibold text-slate-900">How confidence is computed</h3>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <div className="rounded-xl bg-white px-4 py-2 ring-1 ring-slate-200">
          <p className="text-xs text-slate-500">Agreement</p>
          <p className="text-lg font-semibold text-slate-900">{percent(agreement.agreement)}</p>
        </div>
        <span className="text-xl text-slate-400">×</span>
        <div className="rounded-xl bg-white px-4 py-2 ring-1 ring-slate-200">
          <p className="text-xs text-slate-500">Evidence</p>
          <p className="text-lg font-semibold text-slate-900">{percent(agreement.evidence)}</p>
        </div>
        <span className="text-xl text-slate-400">=</span>
        <div className="rounded-xl bg-indigo-600 px-4 py-2 text-white">
          <p className="text-xs text-indigo-100">Confidence</p>
          <p className="text-lg font-semibold">{percent(confidence)}</p>
        </div>
      </div>
      <ul className="mt-3 space-y-1 text-xs text-slate-600">
        <li>
          <b>Agreement</b>: how much the agents point the same way (100% = all agree, low = they pull in opposite directions).
        </li>
        <li>
          <b>Evidence</b>: how much usable information the agents had (agents with no data count as zero).
        </li>
        {thresholds && (
          <li>
            Buy needs a lean above {signed(thresholds.buy, 2)} and Sell a lean below {signed(thresholds.sell, 2)}, both with
            confidence of at least {percent(thresholds.min_confidence)}; otherwise the decision is Hold.
          </li>
        )}
        {agreement.profile && (
          <li>
            Your profile used for the weights: {String(agreement.profile.risk_appetite).replace('_', ' ')} risk,{' '}
            {String(agreement.profile.investment_horizon).replace('_', ' ')} horizon.
          </li>
        )}
      </ul>
    </div>
  )
}

export default function ExplainPanel({ result }) {
  const [open, setOpen] = useState(true)
  const details = result.details
  const agreement = details?.agreement || {}
  const excluded = result.excluded || agreement.excluded || {}
  const agents = result.agents || details?.agents || {}
  const timings = details?.timings_ms || {}

  return (
    <Card
      title="Why this recommendation"
      actions={
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="flex items-center gap-1 rounded-lg px-2 py-1 text-sm text-slate-600 hover:bg-slate-100"
          aria-expanded={open}
        >
          {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          {open ? 'Hide' : 'Show'}
        </button>
      }
    >
      {open && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {AGENT_ORDER.map((agent) => (
              <AgentCard key={agent} agent={agent} data={agents[agent]} excludedReason={excluded[agent]} />
            ))}
          </div>

          {!details ? (
            <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500">
              The detailed breakdown (weights, agreement, timings) was not saved for this older recommendation.
            </p>
          ) : (
            <>
              <ConfidenceStrip agreement={agreement} confidence={result.confidence} thresholds={details.thresholds} />
              <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-slate-900">Each agent's lean and its weight in the decision</h3>
                  <LeanWeightChart agreement={agreement} excluded={excluded} />
                </div>
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-slate-900">
                    Time per agent {timings.total ? `(total ${(timings.total / 1000).toFixed(1)} s, run in parallel)` : ''}
                  </h3>
                  {Object.keys(timings).filter((key) => key !== 'total').length === 0 ? (
                    <p className="text-sm text-slate-500">-</p>
                  ) : (
                    <TimingsChart timings={timings} />
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </Card>
  )
}
