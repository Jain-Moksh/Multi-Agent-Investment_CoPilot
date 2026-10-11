import axios from 'axios'

export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const AUTH_PATHS_WITHOUT_RETRY = ['/auth/login', '/auth/signup', '/auth/refresh', '/auth/logout']

let accessToken = null
let refreshPromise = null

export function setAccessToken(token) {
  accessToken = token
}

export function getAccessToken() {
  return accessToken
}

const client = axios.create({
  baseURL: API_URL,
  withCredentials: true,
})

export function refreshAccessToken() {
  if (!refreshPromise) {
    refreshPromise = axios
      .post(`${API_URL}/auth/refresh`, null, { withCredentials: true })
      .then((response) => {
        accessToken = response.data.access_token
        return accessToken
      })
      .catch((error) => {
        accessToken = null
        throw error
      })
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise
}

export function safeNextPath(value) {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return '/'
  if (value.startsWith('/login') || value.startsWith('/signup')) return '/'
  return value
}

function redirectToLogin() {
  const { pathname, search } = window.location
  if (pathname === '/login' || pathname === '/signup') return
  const params = new URLSearchParams({ expired: '1', next: safeNextPath(pathname + search) })
  window.location.assign(`/login?${params}`)
}

client.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  return config
})

client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config
    const status = error.response?.status
    const skipRetry = !original || AUTH_PATHS_WITHOUT_RETRY.includes(original.url)

    if (status !== 401 || skipRetry || original._retried) {
      return Promise.reject(error)
    }

    original._retried = true
    try {
      await refreshAccessToken()
    } catch {
      setAccessToken(null)
      redirectToLogin()
      return Promise.reject(error)
    }
    return client(original)
  },
)

export function getErrorMessage(error, fallback = 'Something went wrong. Please try again.') {
  const response = error?.response
  if (!response) {
    return error?.code === 'ERR_NETWORK'
      ? 'Cannot reach the server. Check that the backend is running.'
      : fallback
  }

  if (response.status === 429) {
    const seconds = Number(response.headers?.['retry-after'])
    if (Number.isFinite(seconds) && seconds > 0) {
      return `Too many requests. Please try again in ${seconds} second${seconds === 1 ? '' : 's'}.`
    }
    const text = response.data?.detail
    return typeof text === 'string' && text ? text : 'Too many requests. Please try again shortly.'
  }

  const detail = response.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const field = Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body').at(-1) : null
        const message = item.msg || String(item)
        return field && typeof field === 'string' ? `${field.replaceAll('_', ' ')}: ${message}` : message
      })
      .join('; ')
  }
  if (detail && typeof detail === 'object') return detail.message || fallback
  return fallback
}

export function isNotBuilt(error) {
  return error?.response?.status === 404 && error.response.data?.detail === 'Not Found'
}

export default client
