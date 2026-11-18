import { useState, useEffect, useCallback } from 'react'
import { API_BASE } from '../config'

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
  })
}

function StatusBadge({ status }) {
  const s = (status || '').toLowerCase()
  if (s === 'completed') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 border border-emerald-200">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
        Completed
      </span>
    )
  }
  if (s === 'duplicate') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 border border-amber-300">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
        Duplicate Found
      </span>
    )
  }
  if (s === 'warning') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 border border-amber-200">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
        Warning
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-700 border border-red-200">
      <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
      Failed
    </span>
  )
}

function QABadge({ status }) {
  if (status === 'PASS') {
    return <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 border border-emerald-200">PASS</span>
  }
  if (status === 'DUPLICATE FOUND') {
    return <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-300">DUPLICATE</span>
  }
  if (status === 'WARNING') {
    return <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 border border-amber-200">WARNING</span>
  }
  if (status === 'NOT APPLICABLE') {
    return <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 border border-slate-200">N/A</span>
  }
  return <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-red-100 text-red-600 border border-red-200">FAIL</span>
}

export default function Reports() {
  const [reports, setReports] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Filters
  const [dateFilter, setDateFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedReport, setSelectedReport] = useState(null)

  const fetchReports = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (dateFilter) params.append('date', dateFilter)
      if (statusFilter && statusFilter !== 'all') params.append('status', statusFilter)
      if (searchQuery) params.append('search', searchQuery)

      const res = await fetch(`${API_BASE}/api/reports?${params.toString()}`)
      if (!res.ok) throw new Error('Failed to load reports')
      const data = await res.json()
      setReports(data.reports || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [dateFilter, statusFilter, searchQuery])

  useEffect(() => {
    fetchReports()
  }, [fetchReports])

  const statusCounts = {
    all: reports.length,
    completed: reports.filter(r => r.status === 'completed').length,
    duplicate: reports.filter(r => r.status === 'duplicate').length,
    error: reports.filter(r => r.status === 'error').length,
  }

  return (
    <div className="space-y-6 max-w-[1600px] h-[calc(100vh-6rem)] flex flex-col">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Processing Reports</h1>
          <p className="text-slate-500 mt-0.5 text-sm">
            Complete real execution history of article automation runs.
          </p>
        </div>
        <button
          onClick={fetchReports}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-indigo-700 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200 rounded-lg transition-colors w-fit"
        >
          <span>↻ Refresh History</span>
        </button>
      </div>

      {/* Filters Bar */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          {/* Status Tabs */}
          <div className="flex items-center bg-slate-100 p-1 rounded-lg text-xs font-medium">
            {[
              { id: 'all', label: 'All Runs' },
              { id: 'completed', label: 'Completed' },
              { id: 'duplicate', label: 'Duplicate Found' },
              { id: 'error', label: 'Failed' },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setStatusFilter(tab.id)}
                className={`px-3 py-1.5 rounded-md transition-all ${
                  statusFilter === tab.id
                    ? 'bg-white text-indigo-700 font-semibold shadow-xs'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Date filter */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 font-medium">Date:</span>
            <input
              type="date"
              value={dateFilter}
              onChange={e => setDateFilter(e.target.value)}
              className="text-xs border border-slate-300 rounded-lg px-2.5 py-1.5 bg-slate-50 focus:ring-indigo-500 focus:border-indigo-500"
            />
            {dateFilter && (
              <button
                onClick={() => setDateFilter('')}
                className="text-xs text-slate-400 hover:text-slate-600 font-bold"
              >
                ✕
              </button>
            )}
          </div>

          {/* Search bar */}
          <div className="flex-1 min-w-[200px]">
            <input
              type="text"
              placeholder="Search article, file, or project..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="w-full text-xs border border-slate-300 rounded-lg px-3 py-1.5 bg-slate-50 focus:ring-indigo-500 focus:border-indigo-500"
            />
          </div>
        </div>
      </div>

      {/* Reports Table / List */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm flex-1 overflow-hidden flex flex-col">
        {loading ? (
          <div className="flex-1 flex items-center justify-center p-12 text-slate-400 text-sm">
            <svg className="animate-spin h-5 w-5 mr-2" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
            </svg>
            Loading reports history...
          </div>
        ) : error ? (
          <div className="p-8 text-center text-red-600 text-sm">
            <p className="font-semibold mb-1">Failed to load reports</p>
            <p className="text-xs text-slate-500">{error}</p>
          </div>
        ) : reports.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center p-12 text-center text-slate-400">
            <span className="text-3xl mb-2">📋</span>
            <p className="text-sm font-semibold text-slate-600">No reports found</p>
            <p className="text-xs text-slate-400 mt-1">Processed workflow runs will appear here automatically.</p>
          </div>
        ) : (
          <div className="overflow-x-auto flex-1">
            <table className="w-full text-left text-xs text-slate-600 border-collapse">
              <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 uppercase tracking-wider text-[11px] sticky top-0">
                <tr>
                  <th className="py-3 px-4 font-semibold">Date / Time</th>
                  <th className="py-3 px-4 font-semibold">Article & Project</th>
                  <th className="py-3 px-4 font-semibold">WordPress Site</th>
                  <th className="py-3 px-4 font-semibold">Status</th>
                  <th className="py-3 px-4 font-semibold">Focus Keyphrase</th>
                  <th className="py-3 px-4 font-semibold">Author / Category</th>
                  <th className="py-3 px-4 font-semibold text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {reports.map(r => (
                  <tr key={r.id} className="hover:bg-slate-50/75 transition-colors">
                    <td className="py-3.5 px-4 whitespace-nowrap">
                      <p className="font-medium text-slate-800">{r.date}</p>
                      <p className="text-[11px] text-slate-400">{formatDate(r.created_at)}</p>
                    </td>
                    <td className="py-3.5 px-4 max-w-[280px]">
                      <p className="font-semibold text-slate-800 truncate" title={r.article_title}>
                        {r.article_title}
                      </p>
                      <p className="text-[11px] text-slate-400 truncate mt-0.5">
                        {r.project_name || `Project #${r.project_id || '—'}`} {r.filename ? `· 📄 ${r.filename}` : ''}
                      </p>
                    </td>
                    <td className="py-3.5 px-4 whitespace-nowrap">
                      <p className="font-medium text-slate-700">{r.wordpress_site_name || 'Espial Solutions'}</p>
                      {r.wordpress_post_id && (
                        <span className="text-[11px] font-mono text-slate-400">Post #{r.wordpress_post_id}</span>
                      )}
                    </td>
                    <td className="py-3.5 px-4 whitespace-nowrap">
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="py-3.5 px-4 max-w-[200px]">
                      {r.focus_keyphrase ? (
                        <span className="font-mono text-[11px] bg-slate-100 text-slate-800 px-2 py-0.5 rounded truncate inline-block max-w-full">
                          {r.focus_keyphrase}
                        </span>
                      ) : (
                        <span className="text-slate-400 italic">—</span>
                      )}
                    </td>
                    <td className="py-3.5 px-4 whitespace-nowrap">
                      <p className="text-slate-700 font-medium">👤 {r.author || 'Home Office Editor'}</p>
                      <p className="text-[11px] text-indigo-600 mt-0.5">📂 {r.primary_category || 'Uncategorized'}</p>
                    </td>
                    <td className="py-3.5 px-4 text-right whitespace-nowrap space-x-2">
                      <button
                        onClick={() => setSelectedReport(r)}
                        className="px-2.5 py-1 text-xs font-semibold text-indigo-600 hover:text-indigo-800 bg-indigo-50 hover:bg-indigo-100 rounded border border-indigo-200 transition-colors"
                      >
                        Details
                      </button>
                      {(r.edit_url || r.draft_url) && (
                        <a
                          href={r.edit_url || r.draft_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="px-2.5 py-1 text-xs font-semibold text-emerald-700 hover:text-emerald-900 bg-emerald-50 hover:bg-emerald-100 rounded border border-emerald-200 transition-colors inline-block"
                        >
                          Open Draft ↗
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Report Detail Modal */}
      {selectedReport && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4 backdrop-blur-xs">
          <div className="bg-white rounded-2xl shadow-xl border border-slate-200 w-full max-w-3xl max-h-[85vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between bg-slate-50">
              <div>
                <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Processing Report #{selectedReport.id}</span>
                <h3 className="text-base font-bold text-slate-800 truncate max-w-lg mt-0.5">
                  {selectedReport.article_title}
                </h3>
              </div>
              <button
                onClick={() => setSelectedReport(null)}
                className="w-8 h-8 rounded-full bg-slate-200 hover:bg-slate-300 text-slate-600 flex items-center justify-center font-bold text-sm transition-colors"
              >
                ✕
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto space-y-6 text-sm text-slate-700">
              {/* Top Overview Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                  <span className="text-[10px] font-bold text-slate-400 uppercase block">Status</span>
                  <div className="mt-1"><StatusBadge status={selectedReport.status} /></div>
                </div>
                <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                  <span className="text-[10px] font-bold text-slate-400 uppercase block">Date & Time</span>
                  <span className="text-xs font-semibold text-slate-800 mt-1 block truncate">
                    {formatDate(selectedReport.created_at)}
                  </span>
                </div>
                <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                  <span className="text-[10px] font-bold text-slate-400 uppercase block">WordPress Post ID</span>
                  <span className="text-xs font-mono font-semibold text-slate-800 mt-1 block">
                    #{selectedReport.wordpress_post_id || '—'}
                  </span>
                </div>
                <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                  <span className="text-[10px] font-bold text-slate-400 uppercase block">Author</span>
                  <span className="text-xs font-semibold text-slate-800 mt-1 block truncate">
                    👤 {selectedReport.author || 'Home Office Editor'}
                  </span>
                </div>
              </div>

              {/* Focus Keyphrase & SEO */}
              <div className="bg-indigo-50/50 border border-indigo-100 rounded-xl p-4 space-y-3">
                <h4 className="text-xs font-bold uppercase tracking-wider text-indigo-900">SEO & Keyphrase</h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <span className="text-xs text-slate-500 block">Focus Keyphrase (≤ 4 words)</span>
                    <span className="text-sm font-mono font-bold text-indigo-700 bg-white border border-indigo-200 px-2.5 py-1 rounded inline-block mt-1">
                      {selectedReport.focus_keyphrase || 'Not generated'}
                    </span>
                  </div>
                  <div>
                    <span className="text-xs text-slate-500 block">Categories</span>
                    <span className="text-xs font-semibold text-slate-800 bg-white border border-slate-200 px-2.5 py-1 rounded inline-block mt-1">
                      Primary: {selectedReport.primary_category || 'Uncategorized'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Image & Destination details */}
              <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-3 text-xs">
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-600">Featured Image & Destination</h4>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <span className="text-slate-400 block">Image Source:</span>
                    <span className="font-semibold text-slate-700">{selectedReport.image_source || 'DOCX / Pexels'}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">Dimensions:</span>
                    <span className="font-semibold text-emerald-700">1000 × 667 px</span>
                  </div>
                </div>
                {selectedReport.image_source_url && (
                  <div>
                    <span className="text-slate-400 block">Source URL:</span>
                    <a href={selectedReport.image_source_url} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline break-all">
                      {selectedReport.image_source_url} ↗
                    </a>
                  </div>
                )}
                {selectedReport.edit_url && (
                  <div className="pt-2 border-t border-slate-200 flex justify-between items-center">
                    <span className="text-slate-500">WordPress Draft Admin Editor:</span>
                    <a
                      href={selectedReport.edit_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded font-semibold transition-colors"
                    >
                      Open WordPress Draft ↗
                    </a>
                  </div>
                )}
              </div>

              {/* 28-point QA Checklist breakdown */}
              {selectedReport.qa_checklist && Object.keys(selectedReport.qa_checklist).length > 0 && (
                <div className="space-y-3">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700 border-b border-slate-200 pb-1">
                    28-Point HBM QA Checklist Verification
                  </h4>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {Object.entries(selectedReport.qa_checklist).map(([sectionKey, items]) => (
                      <div key={sectionKey} className="bg-slate-50 border border-slate-200 rounded-lg p-3 space-y-2">
                        <p className="text-[11px] font-bold uppercase tracking-wider text-slate-600">
                          {sectionKey.replace(/_/g, ' ')}
                        </p>
                        <div className="space-y-1">
                          {typeof items === 'object' && items !== null && Object.entries(items).map(([k, val]) => {
                            const status = typeof val === 'object' ? val.status : (val ? 'PASS' : 'FAIL')
                            const label = typeof val === 'object' ? val.label : k.replace(/_/g, ' ')
                            return (
                              <div key={k} className="flex items-center justify-between text-xs py-0.5 border-b border-slate-100 last:border-0">
                                <span className="text-slate-600 truncate mr-2" title={label}>{label}</span>
                                <QABadge status={status} />
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="px-6 py-3 border-t border-slate-200 bg-slate-50 flex justify-end">
              <button
                onClick={() => setSelectedReport(null)}
                className="px-4 py-2 bg-slate-200 hover:bg-slate-300 text-slate-700 text-xs font-semibold rounded-lg transition-colors"
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
