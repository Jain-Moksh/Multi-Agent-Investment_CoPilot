import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowDown, ArrowUp, ArrowUpDown, Briefcase, LineChart, Pencil, Trash2 } from 'lucide-react'
import EmptyState from '../EmptyState'
import { ASSET_TYPES, SOURCE_LABELS, assetTypeLabel } from '../../utils/assets'
import { formatDateTime, formatINR, formatNumber, formatPct, plClass } from '../../utils/format'

const COLUMNS = [
  { key: 'symbol', label: 'Symbol', align: 'left' },
  { key: 'asset_type', label: 'Type', align: 'left' },
  { key: 'quantity', label: 'Qty' },
  { key: 'avg_buy_price', label: 'Avg buy' },
  { key: 'current_price', label: 'Current price' },
  { key: 'invested_value', label: 'Invested' },
  { key: 'current_value', label: 'Current value' },
  { key: 'unrealized_pl', label: 'P/L' },
  { key: 'weight_pct', label: 'Weight' },
]

const TABS = [{ value: 'all', plural: 'All' }, ...ASSET_TYPES]

function compare(a, b, { key, direction }) {
  const left = a[key]
  const right = b[key]
  if (left === null || left === undefined) return 1
  if (right === null || right === undefined) return -1
  const result = typeof left === 'string' ? left.localeCompare(right) : left - right
  return direction === 'asc' ? result : -result
}

function SortIcon({ active, direction }) {
  if (!active) return <ArrowUpDown size={12} className="text-slate-300" />
  return direction === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
}

export default function HoldingsTable({ holdings, onAdd, onEdit, onDelete }) {
  const navigate = useNavigate()
  const [tab, setTab] = useState('all')
  const [sort, setSort] = useState({ key: 'current_value', direction: 'desc' })

  const counts = useMemo(() => {
    const result = { all: holdings.length }
    holdings.forEach((holding) => {
      result[holding.asset_type] = (result[holding.asset_type] || 0) + 1
    })
    return result
  }, [holdings])

  const rows = useMemo(() => {
    const filtered = tab === 'all' ? holdings : holdings.filter((holding) => holding.asset_type === tab)
    return [...filtered].sort((a, b) => compare(a, b, sort))
  }, [holdings, tab, sort])

  function toggleSort(key) {
    setSort((current) =>
      current.key === key
        ? { key, direction: current.direction === 'asc' ? 'desc' : 'asc' }
        : { key, direction: key === 'symbol' || key === 'asset_type' ? 'asc' : 'desc' },
    )
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map((item) => (
          <button
            key={item.value}
            type="button"
            onClick={() => setTab(item.value)}
            className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
              tab === item.value ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          >
            {item.plural}
            <span className="ml-1 opacity-70">{counts[item.value] || 0}</span>
          </button>
        ))}
      </div>

      {holdings.length === 0 ? (
        <EmptyState
          icon={Briefcase}
          title="No holdings yet"
          message="Add your first holding, or connect Zerodha to sync your demat holdings."
          actionLabel="Add holding"
          onAction={onAdd}
        />
      ) : rows.length === 0 ? (
        <EmptyState icon={Briefcase} title="Nothing in this category" message="Pick another tab or add a holding." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                {COLUMNS.map((column) => (
                  <th
                    key={column.key}
                    className={`px-3 py-2 font-medium ${column.align === 'left' ? 'text-left' : 'text-right'}`}
                  >
                    <button
                      type="button"
                      onClick={() => toggleSort(column.key)}
                      className={`inline-flex items-center gap-1 hover:text-slate-900 ${
                        column.align === 'left' ? '' : 'flex-row-reverse'
                      }`}
                    >
                      {column.label}
                      <SortIcon active={sort.key === column.key} direction={sort.direction} />
                    </button>
                  </th>
                ))}
                <th className="px-3 py-2 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((holding) => {
                const synced = holding.source === 'kite_sync'
                return (
                  <tr key={holding.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    <td className="px-3 py-3">
                      <div className="font-medium text-slate-900">{holding.symbol}</div>
                      <div className="text-xs text-slate-400">{SOURCE_LABELS[holding.source] || holding.source}</div>
                    </td>
                    <td className="px-3 py-3 text-slate-600">{assetTypeLabel(holding.asset_type)}</td>
                    <td className="px-3 py-3 text-right">{formatNumber(holding.quantity)}</td>
                    <td className="px-3 py-3 text-right">{formatINR(holding.avg_buy_price)}</td>
                    <td className="px-3 py-3 text-right">
                      {holding.price_missing ? (
                        <span className="inline-flex rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
                          price unavailable
                        </span>
                      ) : (
                        <span
                          title={holding.price_as_of ? `As of ${formatDateTime(holding.price_as_of)}` : undefined}
                          className="cursor-help border-b border-dotted border-slate-300"
                        >
                          {formatINR(holding.current_price)}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-right">{formatINR(holding.invested_value)}</td>
                    <td className="px-3 py-3 text-right">{formatINR(holding.current_value)}</td>
                    <td className={`px-3 py-3 text-right ${plClass(holding.unrealized_pl)}`}>
                      <div>{formatINR(holding.unrealized_pl)}</div>
                      <div className="text-xs">{formatPct(holding.unrealized_pl_pct)}</div>
                    </td>
                    <td className="px-3 py-3 text-right">{formatPct(holding.weight_pct).replace('+', '')}</td>
                    <td className="px-3 py-3">
                      <div className="flex items-center justify-end gap-1">
                        {holding.asset_type === 'stock' && (
                          <button
                            type="button"
                            onClick={() => navigate(`/insights?symbol=${encodeURIComponent(holding.symbol)}`)}
                            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-indigo-600 hover:bg-indigo-50"
                          >
                            <LineChart size={14} />
                            Analyze
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => onEdit(holding)}
                          disabled={synced}
                          title={synced ? 'Synced from Zerodha; updated automatically' : 'Edit'}
                          aria-label="Edit"
                          className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button"
                          onClick={() => onDelete(holding)}
                          disabled={synced}
                          title={synced ? 'Synced from Zerodha; disconnect Zerodha to remove' : 'Delete'}
                          aria-label="Delete"
                          className="rounded-lg p-1.5 text-slate-500 hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
