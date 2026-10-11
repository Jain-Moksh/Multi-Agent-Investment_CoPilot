import client from './client'

export async function getProfile() {
  const { data } = await client.get('/profile')
  return data
}

export async function updateProfile(body) {
  const { data } = await client.put('/profile', body)
  return data
}
