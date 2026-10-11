import client from './client'

export async function getOpportunities(params = {}) {
  const { data } = await client.get('/opportunities', { params })
  return data
}
