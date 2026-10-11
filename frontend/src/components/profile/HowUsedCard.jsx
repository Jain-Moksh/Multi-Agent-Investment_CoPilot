import Card from '../Card'

const POINTS = [
  'Your effective risk appetite is the more cautious of what you stated and how you actually trade.',
  'Short-term investors: price action (technicals) counts 1.5 times more and fundamentals count less.',
  'Long-term investors: fundamentals count 1.3 times more and short-term price action counts less.',
  'Conservative investors hear warnings louder: bearish signals count 1.5 times (aggressive: 0.75 times).',
  'The Buy / Hold / Sell thresholds are the same for everyone; only these weights change.',
]

export default function HowUsedCard() {
  return (
    <Card title="How this is used">
      <p className="text-sm text-slate-600">
        Your profile changes how much each analysis agent counts in the final recommendation.
      </p>
      <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-slate-600">
        {POINTS.map((point) => (
          <li key={point}>{point}</li>
        ))}
      </ul>
    </Card>
  )
}
