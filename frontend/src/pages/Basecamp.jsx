import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { API_BASE } from '../config'

// ── Helpers ─────────────────────────────────────────────────────────────────

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

function formatBytes(bytes) {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// ── Status badge ─────────────────────────────────────────────────────────────
function StatusBadge({ connected }) {
  return connected ? (
    <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-100 text-emerald-700 text-sm font-medium ring-1 ring-emerald-200">
      <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
      Connected
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-slate-100 text-slate-500 text-sm font-medium ring-1 ring-slate-200">
      <span className="w-2 h-2 rounded-full bg-slate-400" />
      Not Connected
    </span>
  )
}

// ── Error / success banner ───────────────────────────────────────────────────
const OAUTH_ERROR_MESSAGES = {
  access_denied:         'Access was denied. You cancelled the Basecamp authorisation.',
  missing_code:          'OAuth callback received without an authorisation code.',
  token_exchange_failed: 'Token exchange with Basecamp failed. Please try again.',
}

function Banner({ type, message, onDismiss }) {
  const styles = {
    error:   'bg-red-50 border-red-200 text-red-700',
    success: 'bg-emerald-50 border-emerald-200 text-emerald-700',
    info:    'bg-amber-50 border-amber-200 text-amber-700',
  }
  return (
    <div className={`flex items-start justify-between gap-3 px-4 py-3 rounded-lg border text-sm ${styles[type]}`}>
      <p>{message}</p>
      <button onClick={onDismiss} className="shrink-0 font-bold opacity-60 hover:opacity-100">✕</button>
    </div>
  )
}

// ── Spinner ──────────────────────────────────────────────────────────────────
function Spinner({ label }) {
  return (
    <div className="flex items-center gap-2 text-slate-400 text-sm py-4">
      <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
      </svg>
      {label}
    </div>
  )
}

// ── Empty state ──────────────────────────────────────────────────────────────
function EmptyState({ icon, title, subtitle }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="text-4xl mb-3">{icon}</div>
      <p className="font-medium text-slate-700">{title}</p>
      {subtitle && <p className="text-sm text-slate-400 mt-1">{subtitle}</p>}
    </div>
  )
}

// ── Error state ──────────────────────────────────────────────────────────────
function ErrorState({ message, onRetry }) {
  return (
    <div className="flex flex-col items-center gap-3 py-10 text-center">
      <div className="text-3xl">⚠️</div>
      <p className="text-sm text-red-600 max-w-sm">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="px-3 py-1.5 text-sm bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg transition-colors"
        >
          Retry
        </button>
      )}
    </div>
  )
}

// ── Project card ─────────────────────────────────────────────────────────────
function ProjectCard({ project, onViewMessages, isSelected }) {
  return (
    <div
      className={`bg-white border rounded-xl p-4 shadow-sm flex flex-col gap-3 transition-all ${
        isSelected ? 'border-indigo-400 ring-2 ring-indigo-100' : 'border-slate-200 hover:border-slate-300'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-slate-800 text-sm truncate">{project.name}</p>
          {project.description && (
            <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">{project.description}</p>
          )}
        </div>
        <span
          className={`shrink-0 text-xs px-2 py-0.5 rounded-full font-medium ${
            project.status === 'active'
              ? 'bg-emerald-100 text-emerald-700'
              : 'bg-slate-100 text-slate-500'
          }`}
        >
          {project.status}
        </span>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-400">Updated {formatDate(project.updated_at)}</span>
        <div className="flex items-center gap-2">
          {project.url && (
            <a
              href={project.url}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-slate-400 hover:text-indigo-500 transition-colors"
              title="Open in Basecamp"
            >
              ↗
            </a>
          )}
          <button
            onClick={() => onViewMessages(project)}
            className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors ${
              isSelected
                ? 'bg-indigo-600 text-white'
                : 'bg-indigo-50 text-indigo-600 hover:bg-indigo-100'
            }`}
          >
            {isSelected ? 'Viewing Messages' : 'View Messages'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Message row ───────────────────────────────────────────────────────────────
function MessageRow({ message, onClick, isSelected }) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-4 py-3 rounded-lg border transition-all ${
        isSelected
          ? 'border-indigo-400 bg-indigo-50 ring-1 ring-indigo-200'
          : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="font-medium text-slate-800 text-sm truncate">{message.subject || '(No subject)'}</p>
          <div className="flex items-center gap-2 mt-0.5 flex-wrap">
            {message.author && (
              <span className="text-xs text-slate-500">{message.author}</span>
            )}
            <span className="text-xs text-slate-300">·</span>
            <span className="text-xs text-slate-400">{formatDate(message.created_at)}</span>
            {message.attachment_count > 0 && (
              <>
                <span className="text-xs text-slate-300">·</span>
                <span className="text-xs text-amber-600 font-medium">
                  📎 {message.attachment_count} attachment{message.attachment_count !== 1 ? 's' : ''}
                </span>
              </>
            )}
          </div>
          {message.preview && (
            <p className="text-xs text-slate-500 mt-1.5 line-clamp-2">{message.preview}</p>
          )}
        </div>
        {message.url && (
          <a
            href={message.url}
            target="_blank"
            rel="noreferrer"
            onClick={e => e.stopPropagation()}
            className="shrink-0 text-slate-400 hover:text-indigo-500 text-sm transition-colors"
            title="Open in Basecamp"
          >
            ↗
          </a>
        )}
      </div>
    </button>
  )
}

// ── Message detail panel ─────────────────────────────────────────────────────
function MessageDetail({ projectId, message, onClose }) {
  const [detail, setDetail]   = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  const fetchDetail = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/api/basecamp/projects/${projectId}/messages/${message.id}`, { credentials: 'include' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.message || `HTTP ${res.status}`)
      }
      setDetail(await res.json())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [projectId, message.id])

  useEffect(() => { fetchDetail() }, [fetchDetail])

  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-sm">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-slate-100">
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-slate-800">{message.subject || '(No subject)'}</p>
          <p className="text-xs text-slate-400 mt-0.5">
            {message.author} · {formatDate(message.created_at)}
          </p>
        </div>
        <button
          onClick={onClose}
          className="shrink-0 text-slate-400 hover:text-slate-600 text-lg leading-none"
        >
          ✕
        </button>
      </div>

      {/* Body */}
      <div className="px-5 py-4">
        {loading && <Spinner label="Loading message…" />}
        {error && <ErrorState message={error} onRetry={fetchDetail} />}
        {!loading && !error && detail && (
          <div className="space-y-5">
            {/* Content */}
            <div
              className="prose prose-sm max-w-none text-slate-700 text-sm leading-relaxed"
              dangerouslySetInnerHTML={{ __html: detail.content || '<em>No content</em>' }}
            />

            {/* Attachments */}
            {detail.attachments && detail.attachments.length > 0 && (
              <div className="border-t border-slate-100 pt-4">
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
                  Attachments ({detail.attachments.length})
                </p>
                <div className="space-y-2">
                  {detail.attachments.map((att, i) => (
                    <div
                      key={att.id ?? i}
                      className="flex items-center gap-3 px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg"
                    >
                      <span className="text-lg shrink-0">📎</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-slate-700 truncate">
                          {att.filename || 'Unnamed file'}
                        </p>
                        <p className="text-xs text-slate-400">
                          {att.content_type || 'unknown type'} · {formatBytes(att.byte_size)}
                        </p>
                      </div>
                      {att.url && (
                        <a
                          href={att.url}
                          target="_blank"
                          rel="noreferrer"
                          className="shrink-0 text-xs text-indigo-500 hover:underline"
                        >
                          Open ↗
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {detail.attachments && detail.attachments.length === 0 && (
              <p className="text-xs text-slate-400 border-t border-slate-100 pt-4">No attachments.</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function Basecamp() {
  const [searchParams, setSearchParams] = useSearchParams()

  // ── Auth state
  const [connected, setConnected]           = useState(false)
  const [statusLoading, setStatusLoading]   = useState(true)
  const [actionLoading, setActionLoading]   = useState(false)
  const [banner, setBanner]                 = useState(null)

  // ── Projects state
  const [projects, setProjects]             = useState([])
  const [projectsLoading, setProjectsLoading] = useState(false)
  const [projectsError, setProjectsError]   = useState(null)
  const [selectedProject, setSelectedProject] = useState(null)

  // ── Messages state
  const [messages, setMessages]             = useState([])
  const [messagesLoading, setMessagesLoading] = useState(false)
  const [messagesError, setMessagesError]   = useState(null)
  const [selectedMessage, setSelectedMessage] = useState(null)

  // ── Read OAuth callback query params ────────────────────────────────────────
  useEffect(() => {
    const connectedParam = searchParams.get('connected')
    const errorParam     = searchParams.get('error')

    if (connectedParam === 'true') {
      setBanner({ type: 'success', message: 'Basecamp connected successfully!' })
    } else if (errorParam) {
      const msg = OAUTH_ERROR_MESSAGES[errorParam] ?? `OAuth error: ${errorParam}`
      setBanner({ type: 'error', message: msg })
    }

    if (connectedParam || errorParam) {
      setSearchParams({}, { replace: true })
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Fetch connection status ──────────────────────────────────────────────────
  const fetchStatus = useCallback(async () => {
    setStatusLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/basecamp/status`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setConnected(data.connected ?? false)
    } catch {
      setBanner({
        type: 'error',
        message: 'Could not reach the backend. Make sure the FastAPI server is running.',
      })
    } finally {
      setStatusLoading(false)
    }
  }, [])

  useEffect(() => { fetchStatus() }, [fetchStatus])

  // ── Auto-load projects when connected ───────────────────────────────────────
  useEffect(() => {
    if (connected) fetchProjects()
    else {
      setProjects([])
      setSelectedProject(null)
      setMessages([])
      setSelectedMessage(null)
    }
  }, [connected]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Fetch projects ───────────────────────────────────────────────────────────
  const fetchProjects = useCallback(async () => {
    setProjectsLoading(true)
    setProjectsError(null)
    setSelectedProject(null)
    setMessages([])
    setSelectedMessage(null)
    try {
      const res = await fetch(`${API_BASE}/api/basecamp/projects`)
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.message || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setProjects(data.projects ?? [])
    } catch (e) {
      setProjectsError(e.message)
    } finally {
      setProjectsLoading(false)
    }
  }, [])

  // ── Fetch messages for a project ─────────────────────────────────────────────
  const fetchMessages = useCallback(async (project) => {
    setSelectedProject(project)
    setSelectedMessage(null)
    setMessages([])
    setMessagesLoading(true)
    setMessagesError(null)
    try {
      const res = await fetch(`${API_BASE}/api/basecamp/projects/${project.id}/messages`, { credentials: 'include' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.message || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setMessages(data.messages ?? [])
    } catch (e) {
      setMessagesError(e.message)
    } finally {
      setMessagesLoading(false)
    }
  }, [])

  // ── OAuth actions ─────────────────────────────────────────────────────────────
  function handleConnect() {
    window.location.href = `${API_BASE}/api/basecamp/connect`
  }

  async function handleDisconnect() {
    setActionLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/basecamp/disconnect`, { method: 'POST' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setConnected(false)
      setBanner({ type: 'info', message: 'Basecamp disconnected.' })
    } catch {
      setBanner({ type: 'error', message: 'Failed to disconnect. Please try again.' })
    } finally {
      setActionLoading(false)
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-6">
      {/* Page heading */}
      <div>
        <h1 className="text-2xl font-bold text-slate-800">Basecamp</h1>
        <p className="text-slate-500 mt-1 text-sm">
          Connect your Basecamp account to browse projects and pull article briefs.
        </p>
      </div>

      {/* Banner */}
      {banner && (
        <Banner type={banner.type} message={banner.message} onDismiss={() => setBanner(null)} />
      )}

      {/* Connection card */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6 space-y-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-amber-50 flex items-center justify-center text-xl ring-1 ring-amber-100">
              🏕️
            </div>
            <div>
              <p className="font-semibold text-slate-800">Basecamp</p>
              <p className="text-xs text-slate-400">37signals</p>
            </div>
          </div>
          {statusLoading ? (
            <span className="text-xs text-slate-400">Checking…</span>
          ) : (
            <StatusBadge connected={connected} />
          )}
        </div>

        <hr className="border-slate-100" />

        <p className="text-sm text-slate-600">
          Authorise Espial Article Publishing to access your Basecamp account using OAuth 2.0.
          Your credentials are never stored in this application — only an access token is kept server-side.
        </p>

        <div className="flex items-center gap-3">
          {!statusLoading && !connected && (
            <button
              onClick={handleConnect}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
              disabled={actionLoading}
            >
              Connect Basecamp
            </button>
          )}

          {!statusLoading && connected && (
            <>
              <button
                onClick={fetchProjects}
                disabled={projectsLoading}
                className="px-4 py-2 bg-indigo-50 hover:bg-indigo-100 text-indigo-600 text-sm font-medium rounded-lg border border-indigo-200 transition-colors disabled:opacity-50"
              >
                {projectsLoading ? 'Loading…' : 'Refresh Projects'}
              </button>
              <button
                onClick={handleDisconnect}
                disabled={actionLoading}
                className="px-4 py-2 bg-red-50 hover:bg-red-100 text-red-600 text-sm font-medium rounded-lg border border-red-200 transition-colors disabled:opacity-50"
              >
                {actionLoading ? 'Disconnecting…' : 'Disconnect'}
              </button>
            </>
          )}

          <button
            onClick={fetchStatus}
            disabled={statusLoading}
            className="px-3 py-2 text-slate-500 hover:text-slate-700 text-sm rounded-lg hover:bg-slate-100 transition-colors"
          >
            {statusLoading ? 'Refreshing…' : 'Refresh status'}
          </button>
        </div>
      </div>

      {/* ── Not connected helper ──────────────────────────────────────────── */}
      {!statusLoading && !connected && (
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 text-sm text-slate-500 space-y-1">
          <p className="font-medium text-slate-600">Setup required</p>
          <p>
            To complete the OAuth flow, add your Basecamp app credentials to{' '}
            <code className="bg-slate-200 text-slate-700 px-1 rounded text-xs">backend/.env</code>:
          </p>
          <pre className="mt-2 bg-white border border-slate-200 rounded p-3 text-xs text-slate-600 overflow-x-auto">
{`BASECAMP_CLIENT_ID=your_client_id
BASECAMP_CLIENT_SECRET=your_client_secret
BASECAMP_REDIRECT_URI=http://localhost:8000/api/basecamp/callback`}
          </pre>
          <p>
            Register your app at{' '}
            <a
              href="https://launchpad.37signals.com/integrations"
              target="_blank"
              rel="noreferrer"
              className="text-indigo-500 hover:underline"
            >
              launchpad.37signals.com/integrations
            </a>
          </p>
        </div>
      )}

      {/* ── Projects section ─────────────────────────────────────────────── */}
      {!statusLoading && connected && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-800">Projects</h2>
            {projects.length > 0 && (
              <span className="text-xs text-slate-400">{projects.length} project{projects.length !== 1 ? 's' : ''}</span>
            )}
          </div>

          {projectsLoading && <Spinner label="Loading projects…" />}

          {projectsError && (
            <ErrorState message={`Could not load projects: ${projectsError}`} onRetry={fetchProjects} />
          )}

          {!projectsLoading && !projectsError && projects.length === 0 && (
            <EmptyState
              icon="📂"
              title="No projects found"
              subtitle="Your Basecamp account has no accessible projects, or the message board tool is not enabled."
            />
          )}

          {!projectsLoading && !projectsError && projects.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {projects.map(p => (
                <ProjectCard
                  key={p.id}
                  project={p}
                  onViewMessages={fetchMessages}
                  isSelected={selectedProject?.id === p.id}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Messages section ──────────────────────────────────────────────── */}
      {selectedProject && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-800">
                Messages — {selectedProject.name}
              </h2>
              {messages.length > 0 && (
                <p className="text-xs text-slate-400 mt-0.5">
                  {messages.length} message{messages.length !== 1 ? 's' : ''}
                </p>
              )}
            </div>
            <button
              onClick={() => { setSelectedProject(null); setMessages([]); setSelectedMessage(null) }}
              className="text-xs text-slate-400 hover:text-slate-600 transition-colors"
            >
              Close ✕
            </button>
          </div>

          {messagesLoading && <Spinner label="Loading messages…" />}

          {messagesError && (
            <ErrorState
              message={`Could not load messages: ${messagesError}`}
              onRetry={() => fetchMessages(selectedProject)}
            />
          )}

          {!messagesLoading && !messagesError && messages.length === 0 && (
            <EmptyState
              icon="💬"
              title="No messages"
              subtitle="This project's message board is empty."
            />
          )}

          {!messagesLoading && !messagesError && messages.length > 0 && (
            <div className="space-y-2">
              {messages.map(m => (
                <MessageRow
                  key={m.id}
                  message={m}
                  onClick={() => setSelectedMessage(m)}
                  isSelected={selectedMessage?.id === m.id}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Message detail ────────────────────────────────────────────────── */}
      {selectedMessage && selectedProject && (
        <MessageDetail
          projectId={selectedProject.id}
          message={selectedMessage}
          onClose={() => setSelectedMessage(null)}
        />
      )}
    </div>
  )
}
