import client from './client'

export async function getNews({ symbol, sector, portfolioOnly = false, limit = 20, offset = 0 } = {}) {
  const { data } = await client.get('/news', {
    params: {
      symbol: symbol || undefined,
      sector: sector || undefined,
      portfolio_only: portfolioOnly,
      limit,
      offset,
    },
  })
  return data
}
