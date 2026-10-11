import client from './client'

export async function getNotifications(params = {}) {
  const { data } = await client.get('/notifications', { params })
  return data
}

export async function markNotificationRead(id) {
  const { data } = await client.post(`/notifications/${id}/read`)
  return data
}

export function notificationList(data) {
  if (Array.isArray(data)) return data
  return Array.isArray(data?.items) ? data.items : []
}

export function isNotificationRead(item) {
  return item?.read === true || item?.is_read === true || Boolean(item?.read_at)
}
