const inrFormatter = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const dateTimeFormatter = new Intl.DateTimeFormat('en-IN', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

const dateFormatter = new Intl.DateTimeFormat('en-IN', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
})

function isMissing(value) {
  return value === null || value === undefined || value === '' || Number.isNaN(Number(value))
}

export function formatINR(value) {
  if (isMissing(value)) return '-'
  return inrFormatter.format(Number(value))
}

export function formatPct(value, digits = 2) {
  if (isMissing(value)) return '-'
  const number = Number(value)
  const sign = number > 0 ? '+' : ''
  return `${sign}${number.toFixed(digits)}%`
}

function parseDate(value) {
  if (!value) return null
  const text = typeof value === 'string' && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? `${value}Z` : value
  const date = new Date(text)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatDateTime(value) {
  const date = parseDate(value)
  return date ? dateTimeFormatter.format(date) : '-'
}

export function formatDate(value) {
  if (!value) return '-'
  const match = typeof value === 'string' && /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  const date = match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : parseDate(value)
  return date && !Number.isNaN(date.getTime()) ? dateFormatter.format(date) : '-'
}

export function formatNumber(value, maxDigits = 4) {
  if (isMissing(value)) return '-'
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: maxDigits }).format(Number(value))
}

export function plClass(value) {
  if (isMissing(value) || Number(value) === 0) return 'text-slate-700'
  return Number(value) > 0 ? 'text-green-600' : 'text-red-600'
}

export function timeAgo(value) {
  const date = parseDate(value)
  if (!date) return '-'
  const seconds = Math.round((Date.now() - date.getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} day${days === 1 ? '' : 's'} ago`
  return formatDateTime(value)
}

export function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max)
}

export const SENTIMENT_THRESHOLD = 0.15

export function sentimentBucket(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'unscored'
  const number = Number(value)
  if (number > SENTIMENT_THRESHOLD) return 'positive'
  if (number < -SENTIMENT_THRESHOLD) return 'negative'
  return 'neutral'
}
