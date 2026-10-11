import { formatINR } from '../../utils/format'

export const ASSET_LABELS = {
  stock: 'Stocks',
  mutual_fund: 'Mutual funds',
  fd: 'Fixed deposits',
  gold: 'Gold',
  property: 'Property',
}

export const CHART_COLORS = ['#4f46e5', '#0ea5e9', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6']

export const HIGH_CONCENTRATION_PCT = 40

export function assetLabel(type) {
  return ASSET_LABELS[type] || type || '-'
}

export function plClass(value) {
  if (value === null || value === undefined || Number(value) === 0) return 'text-slate-900'
  return Number(value) > 0 ? 'text-green-600' : 'text-red-600'
}

export function signedINR(value) {
  if (value === null || value === undefined) return '-'
  const text = formatINR(value)
  return Number(value) > 0 ? `+${text}` : text
}

export function shortSymbol(symbol) {
  return String(symbol || '').replace(/\.(NS|BO)$/i, '')
}

export function insightsLink(symbol) {
  return `/insights?symbol=${encodeURIComponent(symbol)}`
}
