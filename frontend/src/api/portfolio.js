import client from './client'

export async function getHoldings() {
  const { data } = await client.get('/portfolio/holdings')
  return data
}

export async function getSummary() {
  const { data } = await client.get('/portfolio/summary')
  return data
}

export async function addHolding(body) {
  const { data } = await client.post('/portfolio/holdings', body)
  return data
}

export async function updateHolding(id, body) {
  const { data } = await client.put(`/portfolio/holdings/${id}`, body)
  return data
}

export async function deleteHolding(id) {
  await client.delete(`/portfolio/holdings/${id}`)
}

export async function importStatement(file) {
  const form = new FormData()
  form.append('file', file)
  const { data } = await client.post('/portfolio/import-statement', form)
  return data
}

export async function getZerodhaConnectUrl() {
  const { data } = await client.get('/portfolio/zerodha/connect')
  return data
}

export async function getZerodhaStatus() {
  const { data } = await client.get('/portfolio/zerodha/status')
  return data
}

export async function syncZerodha() {
  const { data } = await client.post('/portfolio/zerodha/sync')
  return data
}

export async function disconnectZerodha() {
  await client.delete('/portfolio/zerodha')
}
