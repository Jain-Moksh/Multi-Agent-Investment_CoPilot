import { AlertTriangle, BarChart3 } from 'lucide-react'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import Card from '../../components/Card'
import EmptyState from '../../components/EmptyState'
import { formatINR } from '../../utils/format'
import CardState from './CardState'
import { HIGH_CONCENTRATION_PCT, shortSymbol } from './helpers'

const TOP_N = 6

function WeightsChart({ rows }) {
  return (
    <div style={{ height: Math.max(160, rows.length * 44) }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 24 }}>
          <XAxis type="number" domain={[0, 100]} tickFormatter={(value) => `${value}%`} fontSize={12} />
          <YAxis type="category" dataKey="label" width={96} fontSize={12} />
          <Tooltip formatter={(value, name, item) => [`${value}% (${formatINR(item.payload.current_value)})`, 'Weight']} />
          <Bar dataKey="weight" radius={[0, 6, 6, 0]} isAnimationActive={false}>
            {rows.map((row) => (
              <Cell key={row.id} fill={row.weight > HIGH_CONCENTRATION_PCT ? '#ef4444' : '#4f46e5'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function WeightsCard({ summary }) {
  return (
    <Card title="Position weights">
      <CardState request={summary} loadingLabel="Loading positions">
        {(data) => {
          const rows = data.holdings
            .filter((holding) => holding.weight_pct !== null)
            .sort((a, b) => b.weight_pct - a.weight_pct)
            .slice(0, TOP_N)
            .map((holding) => ({
              id: holding.id,
              label: shortSymbol(holding.symbol),
              weight: holding.weight_pct,
              current_value: holding.current_value,
            }))
          if (rows.length === 0) {
            return <EmptyState icon={BarChart3} title="No positions yet" message="Weights appear once you add holdings." />
          }
          const concentrated = data.holdings.filter(
            (holding) => holding.asset_type === 'stock' && holding.weight_pct > HIGH_CONCENTRATION_PCT,
          )
          return (
            <>
              {concentrated.length > 0 && (
                <div className="mb-3 flex flex-wrap gap-2">
                  {concentrated.map((holding) => (
                    <span
                      key={holding.id}
                      className="inline-flex items-center gap-1 rounded-full bg-red-50 px-3 py-1 text-xs font-medium text-red-700"
                    >
                      <AlertTriangle size={14} />
                      High concentration: {shortSymbol(holding.symbol)} {holding.weight_pct.toFixed(1)}%
                    </span>
                  ))}
                </div>
              )}
              <WeightsChart rows={rows} />
            </>
          )
        }}
      </CardState>
    </Card>
  )
}
