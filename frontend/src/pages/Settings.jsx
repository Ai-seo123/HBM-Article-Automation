import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { API_BASE } from '../config'

// ── Settings Page ─────────────────────────────────────────────────────────────

export default function Settings() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { employee, isAdmin, authFetch } = useAuth()

  // Tabs
  const initialTab = searchParams.get('tab') || 'integrations'
  const [activeTab, setActiveTab] = useState(initialTab)

  // Basecamp Status
  const [bcStatus, setBcStatus] = useState(null)
  const [bcLoading, setBcLoading] = useState(true)
  const [bcError, setBcError] = useState(null)
  const [bcActionLoading, setBcActionLoading] = useState(false)

  // Multi-account selection
  const [pendingAccounts, setPendingAccounts] = useState([])
  const [pendingLoading, setPendingLoading] = useState(false)
  const [selectedAccountId, setSelectedAccountId] = useState('')

  // Admin: Employee management
  const [employees, setEmployees] = useState([])
  const [empLoading, setEmpLoading] = useState(false)
  const [empError, setEmpError] = useState(null)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [createForm, setCreateForm] = useState({ email: '', full_name: '', password: '', role: 'employee' })
  const [createLoading, setCreateLoading] = useState(false)
  const [createError, setCreateError] = useState(null)
  const [createSuccess, setCreateSuccess] = useState(null)

  // URL params from OAuth callback
  const selectBasecampAccount = searchParams.get('select_basecamp_account') === '1'
  const basecampStatus = searchParams.get('basecamp_status')
  const basecampError = searchParams.get('basecamp_error')

  // ── Fetch Basecamp Status ──────────────────────────────────────────────────

  const fetchBcStatus = useCallback(async () => {
    setBcLoading(true)
    setBcError(null)
    try {
      const res = await authFetch(`${API_BASE}/api/basecamp/status`)
      if (res.ok) {
        const data = await res.json()
        setBcStatus(data)
      } else {
        setBcStatus({ connected: false })
      }
    } catch {
      setBcStatus({ connected: false })
      setBcError('Could not fetch Basecamp status.')
    } finally {
      setBcLoading(false)
    }
  }, [authFetch])

  useEffect(() => {
    fetchBcStatus()
  }, [fetchBcStatus])

  // Handle callback URL params
  useEffect(() => {
    if (basecampStatus === 'connected') {
      fetchBcStatus()
      // Clean up URL params
      const params = new URLSearchParams(searchParams)
      params.delete('basecamp_status')
      setSearchParams(params, { replace: true })
    }
    if (basecampError) {
      setBcError(`Basecamp connection failed: ${basecampError}`)
      const params = new URLSearchParams(searchParams)
      params.delete('basecamp_error')
      setSearchParams(params, { replace: true })
    }
  }, [basecampStatus, basecampError, fetchBcStatus, searchParams, setSearchParams])

  // Fetch pending accounts if multi-account
  useEffect(() => {
    if (selectBasecampAccount) {
      setActiveTab('integrations')
      loadPendingAccounts()
    }
  }, [selectBasecampAccount])

  async function loadPendingAccounts() {
    setPendingLoading(true)
    try {
      const res = await authFetch(`${API_BASE}/api/basecamp/pending-accounts`)
      if (res.ok) {
        const data = await res.json()
        setPendingAccounts(data.accounts || [])
      }
    } catch {
      setBcError('Failed to load Basecamp accounts.')
    } finally {
      setPendingLoading(false)
    }
  }

  // ── Basecamp Actions ───────────────────────────────────────────────────────

  function handleConnect() {
    // Redirect to backend OAuth endpoint (same window)
    window.location.href = `${API_BASE}/api/basecamp/connect`
  }

  async function handleDisconnect() {
    if (!window.confirm('Disconnect your Basecamp account?')) return
    setBcActionLoading(true)
    try {
      await authFetch(`${API_BASE}/api/basecamp/disconnect`, { method: 'POST' })
      setBcStatus({ connected: false })
    } catch {
      setBcError('Failed to disconnect.')
    } finally {
      setBcActionLoading(false)
    }
  }

  async function handleRefresh() {
    setBcActionLoading(true)
    setBcError(null)
    try {
      const res = await authFetch(`${API_BASE}/api/basecamp/refresh`, { method: 'POST' })
      if (res.ok) {
        await fetchBcStatus()
      } else {
        const data = await res.json().catch(() => ({}))
        setBcError(data.detail || 'Token refresh failed. Try reconnecting.')
      }
    } catch {
      setBcError('Failed to refresh connection.')
    } finally {
      setBcActionLoading(false)
    }
  }

  async function handleSelectAccount() {
    if (!selectedAccountId) return
    setBcActionLoading(true)
    setBcError(null)
    try {
      const res = await authFetch(`${API_BASE}/api/basecamp/select-account`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_id: selectedAccountId }),
      })
      if (res.ok) {
        setPendingAccounts([])
        setSelectedAccountId('')
        const params = new URLSearchParams(searchParams)
        params.delete('select_basecamp_account')
        setSearchParams(params, { replace: true })
        await fetchBcStatus()
      } else {
        const data = await res.json().catch(() => ({}))
        setBcError(data.detail || 'Failed to select account.')
      }
    } catch {
      setBcError('Failed to select account.')
    } finally {
      setBcActionLoading(false)
    }
  }

  // ── Admin: Employee Management ─────────────────────────────────────────────

  const fetchEmployees = useCallback(async () => {
    if (!isAdmin) return
    setEmpLoading(true)
    setEmpError(null)
    try {
      const res = await authFetch(`${API_BASE}/api/auth/employees`)
      if (res.ok) {
        const data = await res.json()
        setEmployees(data.employees || [])
      } else {
        setEmpError('Failed to load employees.')
      }
    } catch {
      setEmpError('Could not fetch employees.')
    } finally {
      setEmpLoading(false)
    }
  }, [authFetch, isAdmin])

  useEffect(() => {
    if (activeTab === 'admin' && isAdmin) fetchEmployees()
  }, [activeTab, isAdmin, fetchEmployees])

  async function handleCreateEmployee(e) {
    e.preventDefault()
    setCreateLoading(true)
    setCreateError(null)
    setCreateSuccess(null)
    try {
      const res = await authFetch(`${API_BASE}/api/auth/employees`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(createForm),
      })
      const data = await res.json()
      if (res.ok) {
        setCreateSuccess(`Employee ${data.employee?.email || ''} created.`)
        setCreateForm({ email: '', full_name: '', password: '', role: 'employee' })
        setShowCreateForm(false)
        fetchEmployees()
      } else {
        setCreateError(data.detail || 'Failed to create employee.')
      }
    } catch {
      setCreateError('Error creating employee.')
    } finally {
      setCreateLoading(false)
    }
  }

  async function handleDeactivateEmployee(empId, empEmail) {
    if (!window.confirm(`Deactivate ${empEmail}?`)) return
    try {
      const res = await authFetch(`${API_BASE}/api/auth/employees/${empId}`, { method: 'DELETE' })
      if (res.ok) {
        fetchEmployees()
      } else {
        const data = await res.json().catch(() => ({}))
        setEmpError(data.detail || 'Failed to deactivate employee.')
      }
    } catch {
      setEmpError('Error deactivating employee.')
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  const tabs = [
    { key: 'integrations', label: 'Integrations' },
    ...(isAdmin ? [{ key: 'admin', label: 'Employee Management' }] : []),
  ]

  return (
    <div className="max-w-4xl mx-auto">
      <h1 className="text-xl font-bold text-slate-800 mb-5">Settings</h1>

      {/* Tab Switcher */}
      <div className="flex gap-1 border-b border-slate-200 mb-6">
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={[
              'px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px',
              activeTab === t.key
                ? 'border-indigo-600 text-indigo-600'
                : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300',
            ].join(' ')}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Integrations Tab ─────────────────────────────────────────────── */}
      {activeTab === 'integrations' && (
        <div className="space-y-6">
          {/* Basecamp Card */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 bg-slate-50/50 flex justify-between items-center">
              <div>
                <h2 className="text-sm font-bold text-slate-700 uppercase tracking-wide">Basecamp</h2>
                <p className="text-xs text-slate-500 mt-0.5">Connect your Basecamp account to access projects and articles.</p>
              </div>
              {bcLoading ? (
                <span className="text-xs text-slate-400">Loading...</span>
              ) : (
                <StatusIndicator status={bcStatus} />
              )}
            </div>

            <div className="p-5 space-y-4">
              {bcError && (
                <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                  {bcError}
                  <button onClick={() => setBcError(null)} className="float-right text-red-400 hover:text-red-600 font-bold">×</button>
                </div>
              )}

              {/* Multi-Account Selector */}
              {(selectBasecampAccount || pendingAccounts.length > 0) && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 space-y-3">
                  <p className="text-sm font-semibold text-amber-800">
                    Multiple Basecamp accounts found. Select the account to use:
                  </p>
                  {pendingLoading ? (
                    <p className="text-xs text-amber-600">Loading accounts...</p>
                  ) : (
                    <div className="space-y-2">
                      {pendingAccounts.map(acc => (
                        <label key={acc.id} className="flex items-center gap-3 p-2 bg-white rounded border border-amber-100 cursor-pointer hover:bg-amber-25">
                          <input
                            type="radio"
                            name="bc_account"
                            value={acc.id}
                            checked={selectedAccountId === String(acc.id)}
                            onChange={() => setSelectedAccountId(String(acc.id))}
                            className="accent-indigo-600"
                          />
                          <div>
                            <p className="text-sm font-medium text-slate-700">{acc.name || `Account ${acc.id}`}</p>
                            {acc.product && <p className="text-xs text-slate-500">{acc.product}</p>}
                          </div>
                        </label>
                      ))}
                      <button
                        onClick={handleSelectAccount}
                        disabled={!selectedAccountId || bcActionLoading}
                        className="mt-2 text-xs bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg font-semibold transition-colors"
                      >
                        {bcActionLoading ? 'Saving...' : 'Confirm Selection'}
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* Connection Info */}
              {!bcLoading && bcStatus?.connected && (
                <div className="text-xs text-slate-600 space-y-1">
                  {bcStatus.account_name && (
                    <p>Account: <strong className="text-slate-800">{bcStatus.account_name}</strong></p>
                  )}
                  {bcStatus.identity_name && (
                    <p>Identity: <strong className="text-slate-800">{bcStatus.identity_name}</strong></p>
                  )}
                </div>
              )}

              {/* Actions */}
              <div className="flex flex-wrap gap-2 pt-1">
                {!bcStatus?.connected ? (
                  <button
                    onClick={handleConnect}
                    disabled={bcActionLoading}
                    className="text-xs bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg font-semibold transition-colors shadow-sm"
                  >
                    Connect Basecamp
                  </button>
                ) : (
                  <>
                    <button
                      onClick={handleRefresh}
                      disabled={bcActionLoading}
                      className="text-xs bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-white px-4 py-2 rounded-lg font-semibold transition-colors"
                    >
                      {bcActionLoading ? 'Refreshing...' : 'Refresh Connection'}
                    </button>
                    <button
                      onClick={handleConnect}
                      disabled={bcActionLoading}
                      className="text-xs bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg font-semibold transition-colors"
                    >
                      Reconnect Basecamp
                    </button>
                    <button
                      onClick={handleDisconnect}
                      disabled={bcActionLoading}
                      className="text-xs bg-red-500 hover:bg-red-600 disabled:opacity-50 text-white px-4 py-2 rounded-lg font-semibold transition-colors"
                    >
                      Disconnect
                    </button>
                  </>
                )}
              </div>

              <p className="text-[11px] text-slate-400 pt-1">
                Tokens are never refreshed automatically. Click "Refresh Connection" to manually refresh, or "Reconnect Basecamp" to re-authenticate.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ── Admin: Employee Management Tab ─────────────────────────────── */}
      {activeTab === 'admin' && isAdmin && (
        <div className="space-y-6">
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 bg-slate-50/50 flex justify-between items-center">
              <div>
                <h2 className="text-sm font-bold text-slate-700 uppercase tracking-wide">Employee Accounts</h2>
                <p className="text-xs text-slate-500 mt-0.5">Create, manage, and deactivate employee accounts.</p>
              </div>
              <div className="flex items-center gap-2">
                <a
                  href="/admin/activity"
                  className="text-xs bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-300 px-3 py-1.5 rounded-lg font-semibold transition-colors flex items-center gap-1.5"
                >
                  <span>🛡️</span> Activity Logs
                </a>
                <button
                  onClick={() => { setShowCreateForm(v => !v); setCreateError(null); setCreateSuccess(null) }}
                  className="text-xs bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-1.5 rounded-lg font-semibold transition-colors"
                >
                  {showCreateForm ? 'Cancel' : '+ New Employee'}
                </button>
              </div>
            </div>

            <div className="p-5 space-y-4">
              {createSuccess && (
                <div className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2">
                  {createSuccess}
                </div>
              )}
              {empError && (
                <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                  {empError}
                </div>
              )}

              {/* Create Form */}
              {showCreateForm && (
                <form onSubmit={handleCreateEmployee} className="bg-slate-50 border border-slate-200 rounded-lg p-4 space-y-3">
                  <h3 className="text-xs font-bold text-slate-700 uppercase">Create Employee</h3>
                  {createError && (
                    <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1">{createError}</div>
                  )}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">Full Name</label>
                      <input
                        type="text" required
                        value={createForm.full_name}
                        onChange={e => setCreateForm(f => ({ ...f, full_name: e.target.value }))}
                        className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">Email</label>
                      <input
                        type="email" required
                        value={createForm.email}
                        onChange={e => setCreateForm(f => ({ ...f, email: e.target.value }))}
                        className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">Password</label>
                      <input
                        type="password" required minLength={8}
                        value={createForm.password}
                        onChange={e => setCreateForm(f => ({ ...f, password: e.target.value }))}
                        className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">Role</label>
                      <select
                        value={createForm.role}
                        onChange={e => setCreateForm(f => ({ ...f, role: e.target.value }))}
                        className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none bg-white"
                      >
                        <option value="employee">Employee</option>
                        <option value="admin">Admin</option>
                      </select>
                    </div>
                  </div>
                  <button
                    type="submit"
                    disabled={createLoading}
                    className="text-xs bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg font-semibold transition-colors"
                  >
                    {createLoading ? 'Creating...' : 'Create Employee'}
                  </button>
                </form>
              )}

              {/* Employee List */}
              {empLoading ? (
                <p className="text-xs text-slate-400">Loading employees...</p>
              ) : (
                <div className="divide-y divide-slate-100">
                  {employees.map(emp => (
                    <div key={emp.id} className="flex items-center justify-between py-3">
                      <div>
                        <p className="text-sm font-medium text-slate-700">
                          {emp.full_name}
                          {emp.id === employee?.id && <span className="ml-2 text-[10px] bg-indigo-100 text-indigo-600 px-1.5 py-0.5 rounded font-bold">YOU</span>}
                        </p>
                        <p className="text-xs text-slate-500">{emp.email} · <span className="capitalize">{emp.role}</span></p>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${emp.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-600'}`}>
                          {emp.is_active ? 'Active' : 'Inactive'}
                        </span>
                        {emp.is_active && emp.id !== employee?.id && (
                          <button
                            onClick={() => handleDeactivateEmployee(emp.id, emp.email)}
                            className="text-[10px] text-red-500 hover:text-red-700 font-medium hover:underline"
                          >
                            Deactivate
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                  {employees.length === 0 && (
                    <p className="text-xs text-slate-400 py-4 text-center">No employees found.</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Status Indicator ──────────────────────────────────────────────────────────

function StatusIndicator({ status }) {
  if (!status || !status.connected) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-500 text-xs font-medium ring-1 ring-slate-200">
        <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
        Not Connected
      </span>
    )
  }
  if (status.expired || status.is_expired) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-amber-100 text-amber-700 text-xs font-semibold ring-1 ring-amber-200">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
        Expired
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700 text-xs font-semibold ring-1 ring-emerald-200">
      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
      Connected
    </span>
  )
}
