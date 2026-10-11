import client from './client'

export async function getSystemStatus() {
  const { data } = await client.get('/system/status')
  return data
}

export async function getHealth() {
  const { data } = await client.get('/health')
  return data
}

export async function getSchedulerStatus() {
  const { data } = await client.get('/health/scheduler')
  return data
}
