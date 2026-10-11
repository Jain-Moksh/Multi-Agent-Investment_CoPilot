import { useNavigate } from 'react-router-dom'
import { PieChart as PieIcon } from 'lucide-react'
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import Card from '../../components/Card'
import EmptyState from '../../components/EmptyState'
import { formatINR } from '../../utils/format'
import CardState from './CardState'
import { CHART_COLORS, assetLabel } from './helpers'

function AllocationChart({ allocation }) {
  const data = allocation.map((slice) => ({
    name: assetLabel(slice.asset_type),
    value: slice.value,
    percent: slice.percent,
  }))
  return (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="name"
            innerRadius="55%"
            outerRadius="80%"
            paddingAngle={2}
            isAnimationActive={false}
          >
            {data.map((entry, index) => (
              <Cell key={entry.name} fill={CHART_COLORS[index % CHART_COLORS.length]} />
            ))}
          </Pie>
          <Tooltip formatter={(value, name, item) => [`${formatINR(value)} (${item.payload.percent ?? '-'}%)`, name]} />
          <Legend
            verticalAlign="bottom"
            formatter={(value, entry) => (
              <span className="text-sm text-slate-600">
                {value} {entry.payload.percent === null ? '' : `${entry.payload.percent.toFixed(1)}%`}
              </span>
            )}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function AllocationCard({ summary }) {
  const navigate = useNavigate()
  return (
    <Card title="Allocation by asset type">
      <CardState request={summary} loadingLabel="Loading allocation">
        {(data) =>
          data.allocation.length === 0 ? (
            <EmptyState
              icon={PieIcon}
              title="No holdings yet"
              message="Add your investments to see how they are spread."
              actionLabel="Go to Portfolio"
              onAction={() => navigate('/portfolio')}
            />
          ) : (
            <AllocationChart allocation={data.allocation} />
          )
        }
      </CardState>
    </Card>
  )
}
