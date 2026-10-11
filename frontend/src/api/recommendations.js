import client from './client'

export async function createRecommendation(symbol) {
  const { data } = await client.post(`/recommendations/${encodeURIComponent(symbol)}`, null, { timeout: 120000 })
  return data
}

export async function getRecommendation(id) {
  const { data } = await client.get(`/recommendations/${id}`)
  return data
}

export async function listRecommendations({ symbol, limit = 20 } = {}) {
  const { data } = await client.get('/recommendations', { params: { symbol, limit } })
  return data
}
