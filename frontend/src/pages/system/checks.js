import client, { getErrorMessage } from '../../api/client'
import { notificationList } from '../../api/notifications'
import { formatINR, timeAgo } from '../../utils/format'

export const STATUS_STYLE = {
  working: { label: 'Working', className: 'bg-green-100 text-green-700' },
  partial: { label: 'Partial', className: 'bg-amber-100 text-amber-800' },
  not_built: { label: 'Not built', className: 'bg-slate-200 text-slate-700' },
  failing: { label: 'Failing', className: 'bg-red-100 text-red-700' },
}

const ok = (detail) => ({ status: 'working', detail })
const partial = (detail) => ({ status: 'partial', detail })
const failing = (detail) => ({ status: 'failing', detail })

export function createContext() {
  const cache = new Map()
  return {
    get(url) {
      if (!cache.has(url)) cache.set(url, client.get(url).then((response) => response.data))
      return cache.get(url)
    },
  }
}

export function errorResult(error) {
  const status = error?.response?.status
  if (status === 404 && error.response.data?.detail === 'Not Found') {
    return { status: 'not_built', detail: 'The endpoint does not exist yet (HTTP 404).' }
  }
  return failing(status ? `HTTP ${status}: ${getErrorMessage(error)}` : getErrorMessage(error))
}

function lastRunText(run) {
  if (!run) return 'no run since the server started'
  const when = run.finished_at ? timeAgo(run.finished_at) : 'still running'
  return `${run.status} (${when})`
}

function listCount(data) {
  return Array.isArray(data) ? data.length : notificationList(data).length
}

export const CHECKS = [
  {
    id: 'health',
    group: 'Backend',
    name: 'API health',
    endpoint: 'GET /health',
    run: async (ctx) => {
      const data = await ctx.get('/health')
      return data.status === 'ok' ? ok('API is up, database connected.') : failing(`Database: ${data.database}`)
    },
  },
  {
    id: 'database',
    group: 'Backend',
    name: 'Database',
    endpoint: 'GET /system/status',
    run: async (ctx) => {
      const { database } = await ctx.get('/system/status')
      return database.ok ? ok('Supabase PostgreSQL reachable.') : failing(database.error || 'Database unreachable.')
    },
  },
  {
    id: 'scheduler',
    group: 'Backend',
    name: 'Background jobs',
    endpoint: 'GET /system/status',
    run: async (ctx) => {
      const { scheduler } = await ctx.get('/system/status')
      if (!scheduler.running) return partial('Scheduler is not running (SCHEDULER_ENABLED=false?).')
      const runs = scheduler.last_runs || {}
      const text = scheduler.jobs.map((job) => `${job.id}: ${lastRunText(runs[job.id])}`).join(' · ')
      const failed = Object.values(runs).some((run) => run.status === 'failed')
      const degraded = Object.values(runs).some((run) => run.status === 'partial')
      if (failed) return failing(text)
      return degraded ? partial(text) : ok(text || 'Running.')
    },
  },
  {
    id: 'row_counts',
    group: 'Backend',
    name: 'Table row counts',
    endpoint: 'GET /system/status',
    run: async (ctx) => {
      const { row_counts: counts } = await ctx.get('/system/status')
      return ok(Object.entries(counts).map(([table, count]) => `${table} ${count ?? '-'}`).join(' · '))
    },
  },
  {
    id: 'vectors',
    group: 'Backend',
    name: 'Vector store (ChromaDB)',
    endpoint: 'GET /system/status',
    run: async (ctx) => {
      const { vector_store: store } = await ctx.get('/system/status')
      if (store.vectors === null) return failing(`Could not read ChromaDB (${store.error || 'unknown error'}).`)
      return store.vectors > 0
        ? ok(`${store.vectors} vectors in "${store.collection}".`)
        : partial(`"${store.collection}" is empty; news is embedded by the news job.`)
    },
  },
  {
    id: 'llm_keys',
    group: 'Backend',
    name: 'LLM keys and models',
    endpoint: 'GET /system/status',
    run: async (ctx) => {
      const { llm } = await ctx.get('/system/status')
      const parts = Object.entries(llm.providers).map(
        ([name, provider]) => `${name}: ${provider.keys_configured} key(s), models ${provider.models.join(', ') || '-'}`,
      )
      const total = Object.values(llm.providers).reduce((sum, provider) => sum + provider.keys_configured, 0)
      return total > 0 ? ok(`Primary ${llm.primary_provider}. ${parts.join(' · ')}`) : failing('No LLM key configured.')
    },
  },
  {
    id: 'data_sources',
    group: 'Backend',
    name: 'Data source keys',
    endpoint: 'GET /system/status',
    run: async (ctx) => {
      const { data_sources: sources } = await ctx.get('/system/status')
      const missing = Object.entries(sources).filter(([, configured]) => !configured).map(([name]) => name)
      const configured = Object.entries(sources).filter(([, value]) => value).map(([name]) => name)
      return missing.length === 0
        ? ok(`All configured: ${configured.join(', ')}.`)
        : partial(`Missing: ${missing.join(', ')}. Configured: ${configured.join(', ') || 'none'}.`)
    },
  },
  {
    id: 'me',
    group: 'Auth',
    name: 'Current user',
    endpoint: 'GET /auth/me',
    run: async (ctx) => {
      const me = await ctx.get('/auth/me')
      return ok(`Logged in as ${me.email}.`)
    },
  },
  {
    id: 'news_count',
    group: 'Data',
    name: 'News collected',
    endpoint: 'GET /system/status',
    run: async (ctx) => {
      const count = (await ctx.get('/system/status')).row_counts.news_events
      return count > 0 ? ok(`${count} articles stored.`) : partial('No news stored yet.')
    },
  },
  {
    id: 'snapshots',
    group: 'Data',
    name: 'Market prices',
    endpoint: 'GET /system/status',
    run: async (ctx) => {
      const count = (await ctx.get('/system/status')).row_counts.market_snapshots
      return count > 0 ? ok(`${count} price snapshots stored.`) : partial('No prices yet; they are collected for held stocks.')
    },
  },
  {
    id: 'last_news_run',
    group: 'Data',
    name: 'Last news ingestion run',
    endpoint: 'GET /system/status',
    run: async (ctx) => {
      const run = (await ctx.get('/system/status')).scheduler.last_runs?.news_ingestion
      if (!run) return partial('No news run since the server started (first run is 60 s after start).')
      const details = run.details || {}
      const fetched = details.fetched ? Object.entries(details.fetched).map(([source, n]) => `${source} ${n}`).join(', ') : '-'
      const text = `${lastRunText(run)}; fetched ${fetched}; inserted ${details.inserted ?? '-'}; quarantined ${details.quarantined ?? 0}`
      if (run.status === 'failed') return failing(`${text}. ${run.errors?.[0] || ''}`)
      return run.status === 'ok' ? ok(text) : partial(text)
    },
  },
  {
    id: 'security_stats',
    group: 'Security',
    name: 'Security statistics',
    endpoint: 'GET /security/stats',
    run: async (ctx) => {
      const s = await ctx.get('/security/stats')
      return ok(`${s.events_total} events (${s.blocked_count} blocked), ${s.quarantine_count} quarantined, ${s.safe_news_count} safe articles.`)
    },
  },
  {
    id: 'security_permissions',
    group: 'Security',
    name: 'Agent permissions',
    endpoint: 'GET /security/permissions',
    run: async (ctx) => {
      const permissions = await ctx.get('/security/permissions')
      return ok(`${Object.keys(permissions).length} agents with read/write allow-lists.`)
    },
  },
  {
    id: 'portfolio_summary',
    group: 'Portfolio',
    name: 'Portfolio summary',
    endpoint: 'GET /portfolio/summary',
    run: async (ctx) => {
      const s = await ctx.get('/portfolio/summary')
      if (s.holdings_count === 0) return ok('Works; this account has no holdings yet.')
      return ok(`${s.holdings_count} holdings (${s.priced_holdings} with a live price), value ${formatINR(s.totals.total_current_value)}.`)
    },
  },
  {
    id: 'zerodha',
    group: 'Portfolio',
    name: 'Zerodha connection',
    endpoint: 'GET /portfolio/zerodha/status',
    run: async (ctx) => {
      const s = await ctx.get('/portfolio/zerodha/status')
      return s.connected ? ok(`Connected as ${s.broker_user_id || '-'}.`) : partial('Not connected (connect it from the Portfolio page).')
    },
  },
  {
    id: 'opportunities',
    group: 'Optional features',
    name: 'Opportunity Scanner',
    endpoint: 'GET /opportunities',
    run: async (ctx) => ok(`${listCount(await ctx.get('/opportunities'))} opportunities returned.`),
  },
  {
    id: 'notifications',
    group: 'Optional features',
    name: 'Notifications',
    endpoint: 'GET /notifications',
    run: async (ctx) => ok(`${listCount(await ctx.get('/notifications'))} notifications returned.`),
  },
  {
    id: 'ai_recommendation',
    group: 'AI (uses quota)',
    name: 'Recommendation for a held stock',
    endpoint: 'POST /recommendations/{symbol}',
    expensive: true,
    run: async (ctx) => {
      const summary = await ctx.get('/portfolio/summary')
      const stocks = summary.holdings.filter((holding) => holding.asset_type === 'stock')
      const held = stocks.find((holding) => !holding.price_missing) || stocks[0]
      if (!held) return partial('No held stock to analyse; add a stock holding first.')
      try {
        const { data } = await client.post(`/recommendations/${encodeURIComponent(held.symbol)}`, null, { timeout: 120000 })
        const degraded = Object.entries(data.agents || {})
          .filter(([, agent]) => !['ok', 'not_held', 'no_portfolio'].includes(agent.status))
          .map(([name, agent]) => `${name.replace('_agent', '')} (${agent.status})`)
        const text = `${data.symbol}: ${data.decision_label}, confidence ${Math.round(data.confidence * 100)}%, explanation ${data.explanation_source}. Degraded: ${degraded.join(', ') || 'none'}.`
        return degraded.length === 0 ? ok(text) : partial(text)
      } catch (error) {
        if (error?.response?.status === 429) return partial(`Cooldown: ${getErrorMessage(error)}`)
        throw error
      }
    },
  },
  {
    id: 'ai_chat',
    group: 'AI (uses quota)',
    name: 'AI Assistant chat',
    endpoint: 'POST /chat/message',
    expensive: true,
    run: async () => {
      const { data } = await client.post(
        '/chat/message',
        { message: 'In one sentence, how is my portfolio doing?', conversation_id: null },
        { timeout: 120000 },
      )
      const text = `status ${data.status}, mode ${data.mode}, security ${data.security?.verdict || '-'}.`
      if (data.status === 'ok') return ok(text)
      return data.status === 'llm_unavailable' ? partial(text) : failing(text)
    },
  },
]

export const GROUPS = [...new Set(CHECKS.map((check) => check.group))]

export function summarize(results) {
  const counts = { working: 0, partial: 0, not_built: 0, failing: 0 }
  Object.values(results).forEach((result) => {
    if (result?.status && counts[result.status] !== undefined) counts[result.status] += 1
  })
  return counts
}

export function summaryLine(counts) {
  return `${counts.working} working, ${counts.partial} partial, ${counts.not_built} not built, ${counts.failing} failing`
}

function cell(text) {
  return String(text ?? '-').replace(/\|/g, '\\|').replace(/\n/g, ' ')
}

export function markdownReport(results, generatedAt) {
  const lines = [
    `# Investment Copilot system check (${generatedAt})`,
    '',
    summaryLine(summarize(results)),
    '',
    '| Group | Check | Endpoint | Status | Detail |',
    '|---|---|---|---|---|',
  ]
  CHECKS.forEach((check) => {
    const result = results[check.id]
    const status = result?.status ? STATUS_STYLE[result.status].label : 'Not run'
    lines.push(`| ${cell(check.group)} | ${cell(check.name)} | \`${cell(check.endpoint)}\` | ${status} | ${cell(result?.detail)} |`)
  })
  return lines.join('\n')
}
