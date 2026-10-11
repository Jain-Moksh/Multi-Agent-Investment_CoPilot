import { formatINR, formatPct } from '../../utils/format'

export const SYMBOL_PATTERN = /^[A-Za-z0-9&-]{1,20}(\.(NS|BO))?$/i

export const AGENT_ORDER = [
  'news_agent',
  'market_agent',
  'portfolio_agent',
  'user_profiling_agent',
  'fundamental_economic_agent',
]

export const AGENT_LABELS = {
  news_agent: 'News',
  market_agent: 'Market',
  portfolio_agent: 'Portfolio',
  user_profiling_agent: 'User Profile',
  fundamental_economic_agent: 'Fundamental & Economic',
}

export const TONES = {
  green: 'bg-green-100 text-green-700',
  slate: 'bg-slate-100 text-slate-600',
  amber: 'bg-amber-100 text-amber-800',
  red: 'bg-red-100 text-red-700',
}

export const STATUS_INFO = {
  ok: { label: 'OK', tone: 'green', text: '' },
  no_news: { label: 'No news', tone: 'slate', text: 'No recent news was found for this stock, so news did not count.' },
  no_relevant_news: {
    label: 'No relevant news',
    tone: 'slate',
    text: 'The news found was not about this stock, so news did not count.',
  },
  no_data: { label: 'No data', tone: 'slate', text: 'No market data was available, so this agent did not count.' },
  insufficient_history: {
    label: 'Not enough history',
    tone: 'slate',
    text: 'Fewer than 5 trades on record, so default profile settings were used.',
  },
  not_held: { label: 'Not held', tone: 'slate', text: 'You do not own this stock, so it was judged as a possible new position.' },
  no_portfolio: { label: 'No portfolio', tone: 'slate', text: 'You have no holdings yet.' },
  llm_unavailable: {
    label: 'AI unavailable',
    tone: 'amber',
    text: 'The AI model was unavailable (quota or outage), so this agent could not analyse the news and did not count.',
  },
  invalid_llm_output: {
    label: 'AI answer unusable',
    tone: 'amber',
    text: 'The AI answer could not be understood, so this agent did not count.',
  },
  timeout: { label: 'Timed out', tone: 'red', text: 'This agent took too long and was left out.' },
  error: { label: 'Error', tone: 'red', text: 'This agent failed and was left out.' },
}

export function statusInfo(status) {
  return STATUS_INFO[status] || { label: status || 'Unknown', tone: 'slate', text: '' }
}

const FACT_ORDER = {
  news_agent: ['articles', 'cited_articles', 'severity'],
  market_agent: ['price', 'trend', 'rsi'],
  portfolio_agent: ['unrealized_pl_pct', 'position_weight_pct', 'concentration_risk'],
  user_profiling_agent: ['risk_appetite', 'investment_horizon'],
  fundamental_economic_agent: ['pe_ratio', 'valuation', 'sector'],
}

function words(value) {
  return String(value).replace(/_/g, ' ')
}

const FACT_FORMAT = {
  articles: (v) => `${v} article${v === 1 ? '' : 's'} read`,
  cited_articles: (v) => `${v} cited`,
  severity: (v) => `Severity ${v}`,
  price: (v) => `Price ${formatINR(v)}`,
  trend: (v) => `Trend ${v}`,
  rsi: (v) => `RSI ${Number(v).toFixed(1)}`,
  unrealized_pl_pct: (v) => `P/L ${formatPct(v)}`,
  position_weight_pct: (v) => `Weight ${Number(v).toFixed(1)}%`,
  concentration_risk: (v) => `Concentration ${v}`,
  risk_appetite: (v) => `Risk ${words(v)}`,
  investment_horizon: (v) => `Horizon ${words(v)}`,
  pe_ratio: (v) => `P/E ${Number(v).toFixed(1)}`,
  valuation: (v) => `Valuation ${words(v)}`,
  sector: (v) => v,
}

export function keyFacts(agent, facts) {
  if (!facts) return []
  return (FACT_ORDER[agent] || [])
    .filter((key) => facts[key] !== undefined && facts[key] !== null)
    .slice(0, 3)
    .map((key) => ({ key, text: FACT_FORMAT[key](facts[key]) }))
}

export function explanationSourceLabel(source) {
  if (source === 'llm') return 'AI written'
  if (source === 'template') return 'Template (AI unavailable)'
  return '-'
}

export function signed(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-'
  const number = Number(value)
  return `${number > 0 ? '+' : ''}${number.toFixed(digits)}`
}
