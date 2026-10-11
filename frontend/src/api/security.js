import client from './client'

export async function getSecurityEvents({ type, limit = 50 } = {}) {
  const { data } = await client.get('/security/events', { params: { type: type || undefined, limit } })
  return data
}

export async function getQuarantine({ limit = 50 } = {}) {
  const { data } = await client.get('/security/quarantine', { params: { limit } })
  return data
}

export async function getSecurityStats() {
  const { data } = await client.get('/security/stats')
  return data
}

export async function getPermissions() {
  const { data } = await client.get('/security/permissions')
  return data
}

export async function scanText(text) {
  const { data } = await client.post('/security/scan-text', { text })
  return data
}
