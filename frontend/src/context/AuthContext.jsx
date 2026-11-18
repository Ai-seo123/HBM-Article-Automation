import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { API_BASE } from '../config'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [employee, setEmployee] = useState(null)
  const [csrfToken, setCsrfToken] = useState('')
  const [loading, setLoading] = useState(true)

  // Read CSRF token from cookie
  const readCsrfCookie = useCallback(() => {
    const match = document.cookie.match(/(?:^|;\s*)espial_csrf=([^;]+)/)
    return match ? decodeURIComponent(match[1]) : ''
  }, [])

  // Check session on mount
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/auth/me`, { credentials: 'include' })
        if (res.ok) {
          const data = await res.json()
          if (!cancelled) {
            setEmployee(data.employee)
            setCsrfToken(data.csrf_token || readCsrfCookie())
          }
        }
      } catch {
        // Not logged in
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [readCsrfCookie])

  const login = useCallback(async (email, password) => {
    const res = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email, password }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || 'Login failed')
    setEmployee(data.employee)
    setCsrfToken(data.csrf_token || readCsrfCookie())
    return data
  }, [readCsrfCookie])

  const logout = useCallback(async () => {
    try {
      await fetch(`${API_BASE}/api/auth/logout`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'X-CSRF-Token': csrfToken },
      })
    } catch { /* ignore */ }
    setEmployee(null)
    setCsrfToken('')
  }, [csrfToken])

  // Helper for authenticated fetch with CSRF
  const authFetch = useCallback(async (url, options = {}) => {
    const headers = { ...(options.headers || {}) }
    const method = (options.method || 'GET').toUpperCase()
    if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method) && csrfToken) {
      headers['X-CSRF-Token'] = csrfToken
    }
    return fetch(url, { ...options, headers, credentials: 'include' })
  }, [csrfToken])

  return (
    <AuthContext.Provider value={{
      employee,
      csrfToken,
      loading,
      isAdmin: employee?.role === 'admin',
      isAuthenticated: !!employee,
      login,
      logout,
      authFetch,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export default AuthContext

