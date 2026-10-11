import client, { refreshAccessToken, setAccessToken } from './client'

export async function login(email, password) {
  const form = new URLSearchParams()
  form.append('username', email)
  form.append('password', password)
  const { data } = await client.post('/auth/login', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  setAccessToken(data.access_token)
  return data
}

export async function signup(email, password) {
  const { data } = await client.post('/auth/signup', { email, password })
  setAccessToken(data.access_token)
  return data
}

export async function refresh() {
  return refreshAccessToken()
}

export async function logout() {
  try {
    await client.post('/auth/logout')
  } finally {
    setAccessToken(null)
  }
}

export async function getMe() {
  const { data } = await client.get('/auth/me')
  return data
}
