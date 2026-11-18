import { useState, useEffect, useCallback } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { API_BASE } from '../config'

function formatDateTime(iso) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
    }) + ' IST'
  } catch {
    return iso
  }
}

function ActionBadge({ action }) {
  const act = (action || '').toLowerCase()
  let color = 'bg-slate-100 text-slate-700 border-slate-200'
  let label = action

  if (act === 'login') {
    color = 'bg-blue-50 text-blue-700 border-blue-200'
    label = 'Login'
  } else if (act === 'logout') {
    color = 'bg-slate-100 text-slate-600 border-slate-200'
    label = 'Logout'
  } else if (act.startsWith('basecamp_')) {
    color = 'bg-amber-50 text-amber-700 border-amber-200'
    label = act.replace('_', ' ')
  } else if (act === 'project_select') {
    color = 'bg-purple-50 text-purple-700 border-purple-200'
    label = 'Project Select'
  } else if (act === 'article_select') {
    color = 'bg-indigo-50 text-indigo-700 border-indigo-200'
    label = 'Article Select'
  } else if (act === 'workflow_start') {
    color = 'bg-sky-50 text-sky-700 border-sky-200'
    label = 'Workflow Start'
  } else if (act === 'workflow_complete') {
    color = 'bg-emerald-50 text-emerald-700 border-emerald-200'
    label = 'Workflow Complete'
  } else if (act === 'workflow_failure') {
    color = 'bg-rose-50 text-rose-700 border-rose-200'
    label = 'Workflow Failure'
  } else if (act === 'image_upload') {
    color = 'bg-teal-50 text-teal-700 border-teal-200'
    label = 'Image Upload'
  } else if (act === 'image_approve') {
    color = 'bg-emerald-50 text-emerald-700 border-emerald-200'
    label = 'Image Approve'
  } else if (act === 'draft_create') {
    color = 'bg-emerald-50 text-emerald-800 border-emerald-200 font-semibold'
    label = 'Draft Created'
  } else if (act === 'wp_author_select') {
    color = 'bg-cyan-50 text-cyan-700 border-cyan-200'
    label = 'Author Selected'
  } else if (act === 'qa_audit') {
    color = 'bg-violet-50 text-violet-700 border-violet-200'
    label = 'QA Audit'
  } else if (act.startsWith('employee_')) {
    color = 'bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200'
    label = act.replace('_', ' ')
  }

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border capitalize ${color}`}>
      {label}
    </span>
  )
}

function StatusBadge({ status }) {
  const isSuccess = (status || '').toLowerCase() === 'success'
  if (isSuccess) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
        Success
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-rose-50 text-rose-700 border border-rose-200">
      <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
      Failure
    </span>
  )
}

export default function AdminActivity() {
  const { isAdmin, loading: authLoading, authFetch } = useAuth()

  // KPI Summary State
  const [summary, setSummary] = useState(null)
  const [summaryLoading, setSummaryLoading] = useState(true)

  // Activity Logs Table State
  const [logs, setLogs] = useState([])
  const [totalLogs, setTotalLogs] = useState(0)
  const [logsLoading, setLogsLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [limit, setLimit] = useState(25)

  // Filter Dropdown Options
  const [employeesList, setEmployeesList] = useState([])
  const [actionTypesList, setActionTypesList] = useState([])
  const [employeesLoading, setEmployeesLoading] = useState(false)
  const [employeesError, setEmployeesError] = useState(null)

  // Filter States
  const [selectedEmployeeId, setSelectedEmployeeId] = useState('')
  const [selectedAction, setSelectedAction] = useState('')
  const [selectedStatus, setSelectedStatus] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [searchQuery, setSearchQuery] = useState('')

  // Modal State
  const [selectedLog, setSelectedLog] = useState(null)
  const [exporting, setExporting] = useState(false)
  const [errorMsg, setErrorMsg] = useState(null)

  // Redirect non-admins
  if (!authLoading && !isAdmin) {
    return <Navigate to="/" replace />
  }

  // ── Fetch Summary ──────────────────────────────────────────────────────────
  const fetchSummary = useCallback(async () => {
    try {
      setSummaryLoading(true)
      const res = await authFetch(`${API_BASE}/api/admin/activity/summary`)
      if (!res.ok) throw new Error('Failed to load activity summary')
      const data = await res.json()
      setSummary(data)
    } catch (err) {
      setErrorMsg(err.message)
    } finally {
      setSummaryLoading(false)
    }
  }, [authFetch])

  // ── Fetch Filter Options (Employees & Action Types) ────────────────────────
  const fetchFilterOptions = useCallback(async () => {
    setEmployeesLoading(true)
    setEmployeesError(null)
    try {
      const [empRes, typesRes] = await Promise.all([
        authFetch(`${API_BASE}/api/admin/activity/employees`).catch(() => null),
        authFetch(`${API_BASE}/api/admin/activity/types`).catch(() => null),
      ])

      let employeesData = null
      if (empRes && empRes.ok) {
        employeesData = await empRes.json()
      } else {
        // Fallback to /api/admin/employees or /api/auth/employees if needed
        const fallbackRes = (await authFetch(`${API_BASE}/api/admin/employees`).catch(() => null))
          || (await authFetch(`${API_BASE}/api/auth/employees`).catch(() => null))
        if (fallbackRes && fallbackRes.ok) {
          employeesData = await fallbackRes.json()
        }
      }

      if (employeesData && Array.isArray(employeesData.employees)) {
        setEmployeesList(employeesData.employees)
      } else {
        setEmployeesError('Failed to load employee list.')
      }

      if (typesRes && typesRes.ok) {
        const typesData = await typesRes.json()
        setActionTypesList(typesData.action_types || typesData.types || [])
      }
    } catch (err) {
      setEmployeesError(err.message || 'Could not fetch employees.')
    } finally {
      setEmployeesLoading(false)
    }
  }, [authFetch])

  // ── Fetch Activity Logs ────────────────────────────────────────────────────
  const fetchLogs = useCallback(async () => {
    try {
      setLogsLoading(true)
      setErrorMsg(null)
      const params = new URLSearchParams()
      params.append('page', page.toString())
      params.append('limit', limit.toString())
      if (selectedEmployeeId) params.append('employee_id', selectedEmployeeId)
      if (selectedAction) params.append('action', selectedAction)
      if (selectedStatus) params.append('status', selectedStatus)
      if (startDate) params.append('start_date', startDate)
      if (endDate) params.append('end_date', endDate)
      if (searchQuery.trim()) params.append('q', searchQuery.trim())

      const res = await authFetch(`${API_BASE}/api/admin/activity/logs?${params.toString()}`)
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || 'Failed to load activity logs')
      }
      const data = await res.json()
      setLogs(data.logs || [])
      setTotalLogs(data.total || 0)
    } catch (err) {
      setErrorMsg(err.message)
    } finally {
      setLogsLoading(false)
    }
  }, [authFetch, page, limit, selectedEmployeeId, selectedAction, selectedStatus, startDate, endDate, searchQuery])

  // Initial Load
  useEffect(() => {
    if (isAdmin) {
      fetchSummary()
      fetchFilterOptions()
    }
  }, [isAdmin, fetchSummary, fetchFilterOptions])

  // Logs trigger on filter/page change
  useEffect(() => {
    if (isAdmin) {
      fetchLogs()
    }
  }, [isAdmin, fetchLogs])

  // ── Export CSV Handler ─────────────────────────────────────────────────────
  async function handleExportCsv() {
    try {
      setExporting(true)
      const params = new URLSearchParams()
      if (selectedEmployeeId) params.append('employee_id', selectedEmployeeId)
      if (selectedAction) params.append('action', selectedAction)
      if (selectedStatus) params.append('status', selectedStatus)
      if (startDate) params.append('start_date', startDate)
      if (endDate) params.append('end_date', endDate)
      if (searchQuery.trim()) params.append('q', searchQuery.trim())

      const res = await authFetch(`${API_BASE}/api/admin/activity/export?${params.toString()}`)
      if (!res.ok) throw new Error('Export failed')
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const today = new Date().toISOString().slice(0, 10)
      a.download = `espial_activity_logs_${today}.csv`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (err) {
      alert(`CSV Export failed: ${err.message}`)
    } finally {
      setExporting(false)
    }
  }

  function handleResetFilters() {
    setSelectedEmployeeId('')
    setSelectedAction('')
    setSelectedStatus('')
    setStartDate('')
    setEndDate('')
    setSearchQuery('')
    setPage(1)
  }

  const totalPages = Math.max(1, Math.ceil(totalLogs / limit))

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-6 space-y-6">
      {/* ── Top Header ──────────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-slate-200">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-2xl">🛡️</span>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Admin Activity Dashboard</h1>
            <span className="bg-indigo-100 text-indigo-700 text-xs px-2.5 py-0.5 rounded-full font-semibold border border-indigo-200">
              Admin Only
            </span>
          </div>
          <p className="text-sm text-slate-500 mt-1">
            Comprehensive audit tracking, employee activity logs, and system KPIs across the publishing pipeline.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { fetchSummary(); fetchLogs(); }}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 shadow-sm"
          >
            <span>🔄</span> Refresh
          </button>
          <button
            onClick={handleExportCsv}
            disabled={exporting}
            className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 shadow-sm"
          >
            <span>📥</span> {exporting ? 'Exporting…' : 'Export CSV'}
          </button>
        </div>
      </div>

      {errorMsg && (
        <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl text-sm text-rose-700 flex items-center justify-between">
          <span>{errorMsg}</span>
          <button onClick={() => setErrorMsg(null)} className="text-xs font-bold underline">Dismiss</button>
        </div>
      )}

      {/* ── 6 KPI Summary Cards ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
        {/* Card 1: Total Employees */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">Total Staff</p>
            <span className="text-xl">👥</span>
          </div>
          <p className="text-2xl font-bold text-slate-900 mt-2">
            {summaryLoading ? '—' : summary?.total_employees ?? 0}
          </p>
          <p className="text-[11px] text-slate-400 mt-1">Registered staff</p>
        </div>

        {/* Card 2: Active Accounts */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">Active Accounts</p>
            <span className="text-xl">🟢</span>
          </div>
          <p className="text-2xl font-bold text-emerald-600 mt-2">
            {summaryLoading ? '—' : summary?.active_employees ?? 0}
          </p>
          <p className="text-[11px] text-slate-400 mt-1">Enabled accounts</p>
        </div>

        {/* Card 3: Employees Logged In Today */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">Active Today</p>
            <span className="text-xl">📅</span>
          </div>
          <p className="text-2xl font-bold text-blue-600 mt-2">
            {summaryLoading ? '—' : summary?.logged_in_today ?? 0}
          </p>
          <p className="text-[11px] text-slate-400 mt-1">Asia/Kolkata day</p>
        </div>

        {/* Card 4: Articles Processed */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">Articles Done</p>
            <span className="text-xl">📄</span>
          </div>
          <p className="text-2xl font-bold text-indigo-600 mt-2">
            {summaryLoading ? '—' : summary?.articles_processed ?? 0}
          </p>
          <p className="text-[11px] text-slate-400 mt-1">Completed runs</p>
        </div>

        {/* Card 5: WordPress Drafts Created */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">WP Drafts</p>
            <span className="text-xl">📝</span>
          </div>
          <p className="text-2xl font-bold text-violet-600 mt-2">
            {summaryLoading ? '—' : summary?.drafts_created ?? 0}
          </p>
          <p className="text-[11px] text-slate-400 mt-1">Unique post IDs</p>
        </div>

        {/* Card 6: Workflow Outcomes */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">Workflows</p>
            <span className="text-xl">⚖️</span>
          </div>
          <div className="flex items-baseline gap-2 mt-2">
            <span className="text-xl font-bold text-emerald-600">
              {summaryLoading ? '—' : summary?.successful_workflows ?? 0}
            </span>
            <span className="text-xs text-slate-400">/</span>
            <span className="text-xl font-bold text-rose-500">
              {summaryLoading ? '—' : summary?.failed_workflows ?? 0}
            </span>
          </div>
          <p className="text-[11px] text-slate-400 mt-1">Success / Failed (Net)</p>
        </div>
      </div>

      {/* ── Search and Filter Controls ───────────────────────────────────────── */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          {/* Employee Filter */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-xs font-medium text-slate-600">Employee</label>
              {employeesLoading && (
                <span className="text-[10px] text-slate-400 animate-pulse">Loading…</span>
              )}
            </div>
            <select
              value={selectedEmployeeId}
              onChange={(e) => { setSelectedEmployeeId(e.target.value); setPage(1); }}
              disabled={employeesLoading}
              className="w-full text-xs rounded-lg border-slate-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 disabled:bg-slate-50 disabled:text-slate-400"
            >
              <option value="">All Employees</option>
              {employeesList.map((emp) => {
                const isInactive = emp.is_active === false
                const displayName = emp.full_name || emp.name || emp.email || `User #${emp.id}`
                const label = isInactive
                  ? `${displayName} (${emp.email}) [Inactive]`
                  : `${displayName} (${emp.email})`
                return (
                  <option key={emp.id} value={emp.id}>
                    {label}
                  </option>
                )
              })}
            </select>
            {employeesError && (
              <p className="text-[11px] text-rose-500 mt-1 flex items-center justify-between">
                <span>{employeesError}</span>
                <button
                  type="button"
                  onClick={fetchFilterOptions}
                  className="underline text-indigo-600 hover:text-indigo-800 ml-1 font-medium"
                >
                  Retry
                </button>
              </p>
            )}
          </div>

          {/* Activity Type Filter */}
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Activity Type</label>
            <select
              value={selectedAction}
              onChange={(e) => { setSelectedAction(e.target.value); setPage(1); }}
              className="w-full text-xs rounded-lg border-slate-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 capitalize"
            >
              <option value="">All Activities</option>
              {actionTypesList.map((act) => (
                <option key={act} value={act}>
                  {act.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
          </div>

          {/* Status Filter */}
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Status</label>
            <select
              value={selectedStatus}
              onChange={(e) => { setSelectedStatus(e.target.value); setPage(1); }}
              className="w-full text-xs rounded-lg border-slate-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
            >
              <option value="">All Statuses</option>
              <option value="success">Success</option>
              <option value="failure">Failure</option>
            </select>
          </div>

          {/* Start Date */}
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">From Date</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => { setStartDate(e.target.value); setPage(1); }}
              className="w-full text-xs rounded-lg border-slate-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
            />
          </div>

          {/* End Date */}
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">To Date</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => { setEndDate(e.target.value); setPage(1); }}
              className="w-full text-xs rounded-lg border-slate-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
            />
          </div>

          {/* Keyword Search */}
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Search Keyword</label>
            <input
              type="text"
              placeholder="Article, Project, Post ID…"
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setPage(1); }}
              className="w-full text-xs rounded-lg border-slate-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
            />
          </div>
        </div>

        <div className="flex items-center justify-between pt-2 border-t border-slate-100">
          <p className="text-xs text-slate-500">
            Found <span className="font-semibold text-slate-800">{totalLogs}</span> activity records
          </p>
          <button
            onClick={handleResetFilters}
            className="text-xs text-indigo-600 hover:text-indigo-800 font-medium"
          >
            Clear all filters
          </button>
        </div>
      </div>

      {/* ── Activity Logs Table ──────────────────────────────────────────────── */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-left text-xs">
            <thead className="bg-slate-50 text-slate-600 uppercase font-semibold tracking-wider">
              <tr>
                <th className="py-3 px-4">Timestamp</th>
                <th className="py-3 px-4">Employee</th>
                <th className="py-3 px-4">Activity</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Target / Context</th>
                <th className="py-3 px-4 text-right">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-700">
              {logsLoading ? (
                <tr>
                  <td colSpan="6" className="py-12 text-center text-slate-400">
                    <div className="inline-block animate-spin h-6 w-6 border-2 border-indigo-600 border-t-transparent rounded-full mb-2" />
                    <p>Loading activity logs…</p>
                  </td>
                </tr>
              ) : logs.length === 0 ? (
                <tr>
                  <td colSpan="6" className="py-12 text-center text-slate-400">
                    No activity logs match the selected filters.
                  </td>
                </tr>
              ) : (
                logs.map((log) => (
                  <tr key={log.id} className="hover:bg-slate-50 transition-colors">
                    <td className="py-3 px-4 whitespace-nowrap text-slate-500 font-mono text-[11px]">
                      {formatDateTime(log.created_at)}
                    </td>
                    <td className="py-3 px-4 whitespace-nowrap">
                      <p className="font-medium text-slate-900">{log.employee_name || 'System / Service'}</p>
                      <p className="text-[11px] text-slate-400 font-mono">{log.employee_email || '—'}</p>
                    </td>
                    <td className="py-3 px-4 whitespace-nowrap">
                      <ActionBadge action={log.action} />
                    </td>
                    <td className="py-3 px-4 whitespace-nowrap">
                      <StatusBadge status={log.status} />
                    </td>
                    <td className="py-3 px-4 max-w-xs truncate">
                      {log.article_title && (
                        <p className="font-medium text-slate-800 truncate" title={log.article_title}>
                          📄 {log.article_title}
                        </p>
                      )}
                      {log.project_name && (
                        <p className="text-[11px] text-slate-500 truncate" title={log.project_name}>
                          📁 {log.project_name}
                        </p>
                      )}
                      {log.post_id && (
                        <p className="text-[11px] text-indigo-600 font-medium">
                          WP Post #{log.post_id} {log.author_name ? `• Author: ${log.author_name}` : ''}
                        </p>
                      )}
                      {!log.article_title && !log.project_name && !log.post_id && (
                        <span className="text-slate-400 text-xs">
                          {log.session_id ? `Session: ${log.session_id.slice(0, 16)}…` : '—'}
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-4 text-right whitespace-nowrap">
                      <button
                        onClick={() => setSelectedLog(log)}
                        className="px-2.5 py-1 text-xs font-medium text-indigo-600 bg-indigo-50 border border-indigo-200 rounded hover:bg-indigo-100 transition-colors"
                      >
                        View Details
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Footer */}
        <div className="px-4 py-3 bg-slate-50 border-t border-slate-200 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-slate-600">
          <div className="flex items-center gap-2">
            <span>Rows per page:</span>
            <select
              value={limit}
              onChange={(e) => { setLimit(Number(e.target.value)); setPage(1); }}
              className="text-xs rounded border-slate-300 py-1 px-2 focus:ring-indigo-500 focus:border-indigo-500"
            >
              <option value="15">15</option>
              <option value="25">25</option>
              <option value="50">50</option>
              <option value="100">100</option>
            </select>
            <span>
              Showing {totalLogs === 0 ? 0 : (page - 1) * limit + 1} to {Math.min(page * limit, totalLogs)} of {totalLogs}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="px-3 py-1 bg-white border border-slate-300 rounded hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Previous
            </button>
            <span className="font-semibold text-slate-800">
              Page {page} of {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="px-3 py-1 bg-white border border-slate-300 rounded hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Next
            </button>
          </div>
        </div>
      </div>

      {/* ── Activity Details Modal ───────────────────────────────────────────── */}
      {selectedLog && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-2xl w-full shadow-2xl border border-slate-200 overflow-hidden">
            {/* Modal Header */}
            <div className="px-6 py-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xl">🔍</span>
                <h3 className="font-bold text-slate-900 text-base">Activity Record Details</h3>
                <ActionBadge action={selectedLog.action} />
              </div>
              <button
                onClick={() => setSelectedLog(null)}
                className="text-slate-400 hover:text-slate-600 text-lg font-bold p-1"
              >
                ✕
              </button>
            </div>

            {/* Modal Content */}
            <div className="p-6 space-y-4 max-h-[75vh] overflow-y-auto text-xs">
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                  <p className="text-[10px] uppercase font-semibold text-slate-500">Timestamp</p>
                  <p className="font-mono text-slate-800 mt-0.5">{formatDateTime(selectedLog.created_at)}</p>
                </div>
                <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                  <p className="text-[10px] uppercase font-semibold text-slate-500">Status</p>
                  <div className="mt-0.5">
                    <StatusBadge status={selectedLog.status} />
                  </div>
                </div>
                <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                  <p className="text-[10px] uppercase font-semibold text-slate-500">Employee</p>
                  <p className="font-medium text-slate-800 mt-0.5">{selectedLog.employee_name || 'System'}</p>
                  <p className="text-slate-500 font-mono text-[11px]">{selectedLog.employee_email || '—'}</p>
                </div>
                <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                  <p className="text-[10px] uppercase font-semibold text-slate-500">Workflow Session ID</p>
                  <p className="font-mono text-slate-800 mt-0.5 truncate" title={selectedLog.session_id}>
                    {selectedLog.session_id || '—'}
                  </p>
                </div>
              </div>

              {/* Context Identifiers */}
              <div className="bg-slate-50 p-3 rounded-lg border border-slate-200 space-y-1.5">
                <p className="text-[10px] uppercase font-semibold text-slate-500">Target Identifiers</p>
                <div className="grid grid-cols-2 gap-2 text-[11px]">
                  <div><span className="text-slate-500">Project:</span> {selectedLog.project_name || selectedLog.project_id || '—'}</div>
                  <div><span className="text-slate-500">Article/Message:</span> {selectedLog.message_id || '—'}</div>
                  <div><span className="text-slate-500">WordPress Site:</span> {selectedLog.site_name || selectedLog.site_id || '—'}</div>
                  <div><span className="text-slate-500">Draft Post ID:</span> {selectedLog.post_id || '—'}</div>
                  <div><span className="text-slate-500">Author:</span> {selectedLog.author_name || selectedLog.author_id || '—'}</div>
                  <div><span className="text-slate-500">Article Title:</span> {selectedLog.article_title || '—'}</div>
                </div>
              </div>

              {/* Sanitized Details JSON */}
              <div>
                <p className="text-[10px] uppercase font-semibold text-slate-500 mb-1">
                  Sanitized Event Payload
                </p>
                <pre className="bg-slate-900 text-emerald-400 p-3 rounded-lg overflow-x-auto text-[11px] font-mono leading-relaxed">
                  {selectedLog.details
                    ? JSON.stringify(selectedLog.details, null, 2)
                    : '// No extra metadata recorded'}
                </pre>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="px-6 py-3 bg-slate-50 border-t border-slate-200 flex justify-end">
              <button
                onClick={() => setSelectedLog(null)}
                className="px-4 py-2 bg-slate-200 text-slate-800 font-medium rounded-lg hover:bg-slate-300 transition-colors text-xs"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

