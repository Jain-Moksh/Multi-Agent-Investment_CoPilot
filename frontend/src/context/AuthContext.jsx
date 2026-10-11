import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import * as authApi from '../api/auth'
import { setAccessToken } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    async function restoreSession() {
      try {
        await authApi.refresh()
        const me = await authApi.getMe()
        if (!cancelled) setUser(me)
      } catch {
        setAccessToken(null)
        if (!cancelled) setUser(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    restoreSession()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (email, password) => {
    await authApi.login(email, password)
    const me = await authApi.getMe()
    setUser(me)
    return me
  }, [])

  const signup = useCallback(async (email, password) => {
    await authApi.signup(email, password)
    const me = await authApi.getMe()
    setUser(me)
    return me
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } finally {
      setUser(null)
    }
  }, [])

  const value = useMemo(
    () => ({ user, loading, login, signup, logout }),
    [user, loading, login, signup, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
