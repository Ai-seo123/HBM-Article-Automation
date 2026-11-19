import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { API_BASE } from '../config'

// ── Helpers ──────────────────────────────────────────────────────────────────

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

function Spinner({ label }) {
  return (
    <div className="flex items-center justify-center gap-2 text-slate-400 text-sm py-2">
      <svg className="animate-spin h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
      </svg>
      {label}
    </div>
  )
}

function ErrorMsg({ msg }) {
  return msg ? (
    <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{msg}</p>
  ) : null
}

function StatusBadge({ connected }) {
  return connected ? (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700 text-xs font-semibold ring-1 ring-emerald-200">
      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
      Connected
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-500 text-xs font-medium ring-1 ring-slate-200">
      <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
      Not Connected
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
    return <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-300">NOT APPLICABLE</span>
  }
  if (status === 'INCONCLUSIVE') {
    return <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 border border-purple-200">INCONCLUSIVE</span>
  }
  return <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-red-100 text-red-600 border border-red-200">FAIL</span>
}

const QA_CATEGORY_CONFIG = {
  overall_view: { label: '1. Overall Page Layout', icon: '📄', description: 'Blank lines, paragraph spacing, broken layout tags' },
  links: { label: '2. Links & Citations', icon: '🔗', description: 'Live HTTP reachability, 3-5 word internal anchors, 3-4 word authority anchors' },
  title: { label: '3. Title & Headings', icon: '🏷️', description: 'Title Case formatting, subtitle differentiation, single H1' },
  headings: { label: '4. Heading Hierarchy (H2-H4)', icon: '📑', description: 'Strict H2-H4 nesting, Title Case, bold tags, no converted body paragraphs' },
  images: { label: '5. Featured Image & Envato Credits', icon: '🖼️', description: 'Dimensions, alt text, envato.com source link attribution' },
  content_integrity: { label: '6. Content Parity & Integrity', icon: '✍️', description: 'Source DOCX vocabulary parity, leftover instructions scan' },
  categories_and_tags: { label: '7. Categories & Tags Discrepancies', icon: '📁', description: 'Discrepancy reporting for Richard, zero auto-alterations' },
  author: { label: '8. Author Attribution & Bio Box', icon: '👤', description: 'Richard Henderson default, prohibited author checks (Naveen Shukla, webdev, admin)' },
  duplicate_check: { label: '9. Duplicate Article & Canonical Check', icon: '🔍', description: 'Exact & filler-word duplicate title search, -2 slug suffix prevention' },
  seo: { label: '10. Yoast SEO Metadata & Snippets', icon: '📈', description: '140-155 char meta description, keyphrase in title/desc, excerpt sync' },
}

function SectionCard({ title, children, actions }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-sm flex flex-col h-full overflow-hidden">
      <div className="px-5 py-3 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
        <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide">{title}</h2>
        {actions && <div>{actions}</div>}
      </div>
      <div className="p-5 flex-1 overflow-y-auto space-y-4">{children}</div>
    </div>
  )
}

// ── Main Dashboard Component ──────────────────────────────────────────────────

export default function Dashboard() {
  const { authFetch } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()

  // ── 1. WordPress Site State
  const [sites, setSites]                   = useState([])
  const [sitesLoading, setSitesLoading]     = useState(true)
  const [selectedSiteId, setSelectedSiteId] = useState('')
  const [showSiteModal, setShowSiteModal]   = useState(false)
  const [siteForm, setSiteForm]             = useState({ name: '', url: '', username: '', app_password: '', is_default: false })
  const [siteSaving, setSiteSaving]         = useState(false)
  const [siteTestResult, setSiteTestResult] = useState(null)
  const [siteTesting, setSiteTesting]       = useState(false)

  // ── 1.1 WordPress Author State
  const [authors, setAuthors]               = useState([])
  const [authorsLoading, setAuthorsLoading] = useState(false)
  const [selectedAuthorId, setSelectedAuthorId] = useState('')

  // ── 2. Basecamp Auth State
  const [connected, setConnected]           = useState(false)
  const [statusLoading, setStatusLoading]   = useState(true)
  const [tokenExpired, setTokenExpired]     = useState(false)
  const [refreshingBc, setRefreshingBc]     = useState(false)
  const [banner, setBanner]                 = useState(null)

  // ── 3. Date, Project & Messages
  const [selectedDate, setSelectedDate]     = useState('')
  const [projects, setProjects]             = useState([])
  const [projectsLoading, setProjectsLoading] = useState(false)
  const [projectsError, setProjectsError]   = useState(null)
  const [selectedProject, setSelectedProject] = useState(null)
  
  const [messages, setMessages]             = useState([])
  const [messagesLoading, setMessagesLoading] = useState(false)
  const [messagesError, setMessagesError]   = useState(null)
  const [selectedMessage, setSelectedMessage] = useState(null)
  
  const [msgDetail, setMsgDetail]           = useState(null)
  const [detailLoading, setDetailLoading]   = useState(false)
  const [selectedAttachment, setSelectedAttachment] = useState(null)

  // ── 4. Image Source & Search State
  const [providers, setProviders]           = useState([])
  const [dashboardProvider, setDashboardProvider] = useState('envato')
  const [selectedProvider, setSelectedProvider] = useState('envato')
  const [imageSearchQuery, setImageSearchQuery] = useState('')
  const [imageSearchResults, setImageSearchResults] = useState([])
  const [imageSearching, setImageSearching] = useState(false)
  const [selectedImage, setSelectedImage]   = useState(null)
  const [showImageSearch, setShowImageSearch] = useState(false)

  // Client-specified provider directive from Basecamp instructions
  const imageDirective = msgDetail?.parsed_instructions?.image_directive || null
  const clientRequiredProvider = imageDirective?.required_provider || null
  const isImageIncluded = (imageDirective?.image_requirement === 'included' || imageDirective?.source === 'included') && !clientRequiredProvider

  // Recalculate provider state whenever article or msgDetail changes; never retain previous article's provider
  useEffect(() => {
    if (clientRequiredProvider) {
      setSelectedProvider(clientRequiredProvider)
    } else {
      setSelectedProvider(dashboardProvider)
    }
  }, [clientRequiredProvider, dashboardProvider, selectedMessage])

  // ── 5. Processing State
  const [processing, setProcessing]         = useState(false)
  const [activeStep, setActiveStep]         = useState(null)
  const [processResult, setProcessResult]   = useState(null)
  const [processError, setProcessError]     = useState(null)

  // ── 5.1 Enhanced Create Draft States (Image Gate, Stages, Prominent URL, Link Review)
  const [pauseAtImageGate, setPauseAtImageGate]       = useState(true)
  const [currentView, setCurrentView]                   = useState('dashboard') // 'dashboard' | 'live_workflow'
  const [pausedSession, setPausedSession]             = useState(null)
  const [selectedCandidate, setSelectedCandidate]     = useState(null)
  const [processingStages, setProcessingStages]       = useState([])
  const [resuming, setResuming]                       = useState(false)
  const [copiedUrl, setCopiedUrl]                     = useState(false)

  // Interactive Content & Link Review Tool State
  const [showLinkReviewModal, setShowLinkReviewModal] = useState(false)
  const [editedArticleContent, setEditedArticleContent] = useState('')
  const [selectedAnchorText, setSelectedAnchorText]   = useState('')
  const [selectedWordCount, setSelectedWordCount]     = useState(0)
  const [targetLinkUrl, setTargetLinkUrl]             = useState('')
  const [linkAttachError, setLinkAttachError]         = useState(null)

  // ── 6. Mode Selector & QA Only State (Phase 2)
  const [workflowMode, setWorkflowMode]               = useState('create_draft') // 'create_draft' | 'qa_only'
  const [qaDrafts, setQaDrafts]                       = useState([])
  const [qaDraftsLoading, setQaDraftsLoading]         = useState(false)
  const [qaDraftsError, setQaDraftsError]             = useState(null)
  const [selectedQaDraft, setSelectedQaDraft]         = useState(null)
  const [qaDocxSourceType, setQaDocxSourceType]       = useState('none') // 'none' | 'basecamp'
  const [qaAuditLoading, setQaAuditLoading]           = useState(false)
  const [qaAuditResult, setQaAuditResult]             = useState(null)
  const [qaAuditError, setQaAuditError]               = useState(null)
  const [qaFilterStatus, setQaFilterStatus]           = useState('all') // 'all' | 'issues' | 'pass' | 'na'
  const [expandedQaCategories, setExpandedQaCategories] = useState({})
  const [qaActiveTab, setQaActiveTab]                 = useState('all_checks') // 'all_checks' | 'broken_links' | 'image_issues' | 'content_diff' | 'yoast'

  const toggleQaCategory = (catKey) => {
    setExpandedQaCategories(prev => ({ ...prev, [catKey]: !prev[catKey] }))
  }

  const setAllQaCategoriesExpanded = (expanded) => {
    if (!qaAuditResult?.categories) return
    const nextState = {}
    Object.keys(qaAuditResult.categories).forEach(k => {
      nextState[k] = expanded
    })
    setExpandedQaCategories(nextState)
  }

  const handleRunQaAudit = async () => {
    if (!selectedSiteId || !selectedQaDraft) return
    setQaAuditLoading(true)
    setQaAuditError(null)

    let docxSourcePayload = { type: 'none' }
    if (qaDocxSourceType === 'basecamp') {
      if (selectedAttachment) {
        docxSourcePayload = {
          type: 'basecamp',
          url: selectedAttachment.url || selectedAttachment.download_url,
          attachment_url: selectedAttachment.url || selectedAttachment.download_url,
          filename: selectedAttachment.filename,
          article_title: selectedMessage?.subject || '',
          message_id: selectedMessage?.id || null,
        }
      } else {
        docxSourcePayload = {
          type: 'basecamp',
          unavailable_reason: 'No Basecamp article attachment was selected for comparison.',
        }
      }
    }

    const clientInstructions = {}
    if (msgDetail?.parsed_instructions?.author) {
      clientInstructions.author = msgDetail.parsed_instructions.author
    }
    if (msgDetail?.parsed_instructions?.tags) {
      clientInstructions.tags = msgDetail.parsed_instructions.tags
    }

    try {
      const res = await fetch(`${API_BASE}/api/qa/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          site_id: Number(selectedSiteId),
          post_id: Number(selectedQaDraft.id),
          docx_source: docxSourcePayload,
          client_instructions: clientInstructions,
        }),
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || `QA Audit failed (HTTP ${res.status})`)
      }

      const auditData = await res.json()
      setQaAuditResult(auditData)
      const initialExp = {}
      if (auditData.categories) {
        Object.keys(auditData.categories).forEach(k => { initialExp[k] = true })
      }
      setExpandedQaCategories(initialExp)
    } catch (err) {
      setQaAuditError(err.message || 'QA audit execution failed.')
    } finally {
      setQaAuditLoading(false)
    }
  }

  // Fetch existing drafts for QA Only mode (Strictly read-only GET request)
  const fetchQaDrafts = useCallback(async (siteId) => {
    const targetSiteId = siteId || selectedSiteId
    if (!targetSiteId) {
      setQaDrafts([])
      setSelectedQaDraft(null)
      return
    }
    setQaDraftsLoading(true)
    setQaDraftsError(null)
    try {
      const res = await fetch(`${API_BASE}/api/wordpress/sites/${targetSiteId}/drafts`)
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `Failed to fetch drafts (HTTP ${res.status})`)
      }
      const data = await res.json()
      const drafts = data.drafts || []
      setQaDrafts(drafts)
      if (drafts.length > 0) {
        setSelectedQaDraft(prev => {
          if (!prev) return drafts[0]
          const existing = drafts.find(d => String(d.id) === String(prev.id))
          return existing || drafts[0]
        })
      } else {
        setSelectedQaDraft(null)
      }
    } catch (err) {
      setQaDrafts([])
      setSelectedQaDraft(null)
      setQaDraftsError(err.message || 'Could not load existing drafts from WordPress.')
    } finally {
      setQaDraftsLoading(false)
    }
  }, [selectedSiteId])

  useEffect(() => {
    if (workflowMode === 'qa_only' && selectedSiteId) {
      fetchQaDrafts(selectedSiteId)
    }
  }, [workflowMode, selectedSiteId, fetchQaDrafts])

  // ── Initialization
  useEffect(() => {
    const connectedParam = searchParams.get('connected')
    const errorParam     = searchParams.get('error')

    if (connectedParam === 'true') {
      setBanner({ type: 'success', message: 'Basecamp connected successfully!' })
    } else if (errorParam) {
      setBanner({ type: 'error', message: `OAuth error: ${errorParam}` })
    }

    if (connectedParam || errorParam) {
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, setSearchParams])

  // Fetch WordPress sites
  const fetchSites = useCallback(async () => {
    setSitesLoading(true)
    try {
      const res = await (authFetch || fetch)(`${API_BASE}/api/wordpress/sites`)
      if (res.ok) {
        const data = await res.json()
        const siteList = data.sites || []
        setSites(siteList)
        if (siteList.length > 0 && !selectedSiteId) {
          const defaultSite = siteList.find(s => s.is_default) || siteList[0]
          setSelectedSiteId(String(defaultSite.id))
        }
      }
    } catch (e) {
      log.error?.('Failed to fetch sites', e)
    } finally {
      setSitesLoading(false)
    }
  }, [selectedSiteId, authFetch])

  // Fetch WordPress Authors dynamically from selected WordPress site
  const fetchAuthors = useCallback(async (siteId) => {
    if (!siteId) {
      setAuthors([])
      setSelectedAuthorId('')
      return
    }
    setAuthorsLoading(true)
    try {
      const res = await (authFetch || fetch)(`${API_BASE}/api/wordpress/sites/${siteId}/authors`)
      if (res.ok) {
        const data = await res.json()
        setAuthors(data.authors || [])
      } else {
        setAuthors([])
      }
    } catch {
      setAuthors([])
    } finally {
      setAuthorsLoading(false)
    }
  }, [authFetch])

  useEffect(() => {
    if (selectedSiteId) {
      fetchAuthors(selectedSiteId)
    } else {
      setAuthors([])
      setSelectedAuthorId('')
    }
  }, [selectedSiteId, fetchAuthors])

  // Fetch Image providers
  const fetchProviders = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/images/providers`)
      if (res.ok) {
        const data = await res.json()
        setProviders(data.providers || [])
      }
    } catch {
      // fallback providers
    }
  }, [])

  useEffect(() => {
    fetchSites()
    fetchProviders()
  }, [fetchSites, fetchProviders])

  // Basecamp connection status
  const fetchStatus = useCallback(async () => {
    setStatusLoading(true)
    try {
      const res = await (authFetch || fetch)(`${API_BASE}/api/basecamp/status`, { credentials: 'include' })
      if (!res.ok) throw new Error()
      const data = await res.json()
      const isConn = Boolean(data.connected && !data.is_expired && !data.expired)
      setConnected(isConn)
      setTokenExpired(Boolean(data.is_expired || data.expired))
    } catch {
      setBanner({ type: 'error', message: 'Backend unreachable.' })
    } finally {
      setStatusLoading(false)
    }
  }, [authFetch])

  useEffect(() => { fetchStatus() }, [fetchStatus])

  // Fetch Projects when Basecamp is connected
  const fetchProjects = useCallback(async () => {
    setProjectsLoading(true)
    setProjectsError(null)
    try {
      const res = await (authFetch || fetch)(`${API_BASE}/api/basecamp/projects`, { credentials: 'include' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        if (res.status === 401 || body.error === 'basecamp_token_expired') {
          setTokenExpired(true)
          setConnected(false)
          throw new Error(body.message || 'Basecamp session expired. Please refresh your connection.')
        }
        throw new Error(body.message || 'Failed to load projects')
      }
      const data = await res.json()
      setProjects(data.projects ?? [])
      setTokenExpired(false)
    } catch (err) {
      setProjects([])
      setProjectsError(err.message || 'Failed to load projects')
    } finally {
      setProjectsLoading(false)
    }
  }, [authFetch])

  const handleRefreshBasecamp = useCallback(async () => {
    setRefreshingBc(true)
    try {
      const res = await (authFetch || fetch)(`${API_BASE}/api/basecamp/refresh`, {
        method: 'POST',
        credentials: 'include',
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok && data.success) {
        setTokenExpired(false)
        await fetchStatus()
        await fetchProjects()
        setBanner({ type: 'success', message: 'Basecamp connection refreshed successfully.' })
      } else {
        setBanner({ type: 'error', message: data.message || data.detail || 'Could not refresh Basecamp connection. Please reconnect.' })
      }
    } catch {
      setBanner({ type: 'error', message: 'Failed to refresh Basecamp connection.' })
    } finally {
      setRefreshingBc(false)
    }
  }, [authFetch, fetchStatus, fetchProjects])

  useEffect(() => {
    if (connected) fetchProjects()
    else {
      setProjects([])
      setSelectedProject(null)
      setMessages([])
      setSelectedMessage(null)
    }
  }, [connected, fetchProjects])

  // Fetch Messages when Project or Date changes
  useEffect(() => {
    if (!selectedProject) {
      setMessages([])
      setSelectedMessage(null)
      setMessagesError(null)
      return
    }
    setMessagesLoading(true)
    setMessagesError(null)
    setSelectedMessage(null)
    setMsgDetail(null)
    setSelectedAttachment(null)
    setSelectedImage(null)
    resetProcessing()

    const controller = new AbortController()
    const timeoutId = setTimeout(() => {
      controller.abort()
    }, 25000)

    const _msgBase = `${API_BASE}/api/basecamp/projects/${selectedProject.id}/messages`
    const _msgUrl = selectedDate ? `${_msgBase}?date=${encodeURIComponent(selectedDate)}` : _msgBase

    ;(authFetch || fetch)(_msgUrl, { credentials: 'include', signal: controller.signal })
      .then(async r => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}))
          throw new Error(body.message || `Failed to load messages (HTTP ${r.status})`)
        }
        return r.json()
      })
      .then(d => {
        setMessages(d.messages ?? [])
        setMessagesError(null)
      })
      .catch(err => {
        if (err?.name === 'AbortError') {
          setMessagesError('Request timed out while loading messages from Basecamp. Please try again.')
        } else {
          setMessages([])
          setMessagesError(err?.message || 'Could not load messages from Basecamp.')
        }
      })
      .finally(() => {
        clearTimeout(timeoutId)
        setMessagesLoading(false)
      })

    return () => {
      clearTimeout(timeoutId)
      controller.abort()
    }
  }, [selectedProject, selectedDate])

  // Fetch Message detail
  useEffect(() => {
    if (!selectedMessage || !selectedProject) {
      setMsgDetail(null)
      setSelectedProvider(dashboardProvider)
      return
    }
    setDetailLoading(true)
    setMsgDetail(null)
    setSelectedAttachment(null)
    setSelectedImage(null)
    setSelectedProvider(dashboardProvider)
    resetProcessing()

    const controller = new AbortController()
    const timeoutId = setTimeout(() => {
      controller.abort()
    }, 25000)

    ;(authFetch || fetch)(`${API_BASE}/api/basecamp/projects/${selectedProject.id}/messages/${selectedMessage.id}`, {
      credentials: 'include',
      signal: controller.signal,
    })
      .then(async r => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}))
          throw new Error(body.message || `Failed to load message detail (HTTP ${r.status})`)
        }
        return r.json()
      })
      .then(d => {
        setMsgDetail(d)
        // Auto search query from subject
        if (d.subject) setImageSearchQuery(d.subject)
        const reqProvider = d.parsed_instructions?.image_directive?.required_provider
        if (reqProvider) {
          setSelectedProvider(reqProvider)
        } else {
          setSelectedProvider(dashboardProvider)
        }
      })
      .catch(err => {
        if (err?.name !== 'AbortError') {
          setSelectedProvider(dashboardProvider)
        }
      })
      .finally(() => {
        clearTimeout(timeoutId)
        setDetailLoading(false)
      })

    return () => {
      clearTimeout(timeoutId)
      controller.abort()
    }
  }, [selectedMessage, selectedProject, dashboardProvider])

  const docxAttachments = (msgDetail?.attachments ?? []).filter(a => {
    const fn = (a.filename || '').toLowerCase()
    const ct = (a.content_type || '').toLowerCase()
    return fn.endsWith('.docx') || ct.includes('wordprocessingml') || ct.includes('openxmlformats')
  })

  // Auto-select attachment if only one docx exists
  useEffect(() => {
    if (docxAttachments.length === 1 && !selectedAttachment) {
      setSelectedAttachment(docxAttachments[0])
    }
  }, [docxAttachments, selectedAttachment])

  // Image search action
  async function handleSearchImages() {
    if (!imageSearchQuery.trim()) return
    setImageSearching(true)
    try {
      const res = await fetch(`${API_BASE}/api/images/search?provider=${selectedProvider}&query=${encodeURIComponent(imageSearchQuery.trim())}`)
      const data = await res.json()
      setImageSearchResults(data.results || [])
    } catch {
      setImageSearchResults([])
    } finally {
      setImageSearching(false)
    }
  }

  // Actions
  function handleConnect() {
    window.location.href = `${API_BASE}/api/basecamp/connect`
  }

  function resetProcessing() {
    setProcessResult(null)
    setProcessError(null)
    setActiveStep(null)
    setPausedSession(null)
    setSelectedCandidate(null)
    setProcessingStages([])
    setEditedArticleContent('')
    setSelectedAnchorText('')
    setSelectedWordCount(0)
    setTargetLinkUrl('')
    setLinkAttachError(null)
  }

  function handleImageFileUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (event) => {
      const dataUrl = event.target.result
      const newCand = {
        source: 'upload',
        provider: 'Uploaded Image',
        label: `Uploaded: ${file.name}`,
        filename: file.name,
        content_type: file.type || 'image/jpeg',
        thumbnail_url: dataUrl,
        preview_url: dataUrl,
        raw_image_base64: dataUrl,
        credit_text: 'Image uploaded by user',
        dimensions: '1000 × 667 px',
      }
      setSelectedCandidate(newCand)
      if (pausedSession) {
        setPausedSession(prev => ({
          ...prev,
          image_candidates: [newCand, ...(prev?.image_candidates || [])],
        }))
      }
    }
    reader.readAsDataURL(file)
  }

  async function handleResumePipeline() {
    if (!pausedSession) return
    const candidate = selectedCandidate || pausedSession.image_candidates?.[0]
    if (!candidate) {
      alert('Please select or upload an image candidate to approve.')
      return
    }

    setResuming(true)
    setProcessError(null)
    try {
      const res = await (authFetch || fetch)(`${API_BASE}/api/articles/process`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: selectedProject.id,
          message_id: selectedMessage.id,
          attachment_id: String(selectedAttachment.id),
          site_id: parseInt(selectedSiteId, 10),
          author_id: selectedAuthorId ? parseInt(selectedAuthorId, 10) : undefined,
          session_id: pausedSession.session_id,
          resume_action: 'approve_image',
          selected_image_data: candidate,
          custom_content: editedArticleContent || undefined,
        }),
      })

      const data = await res.json()
      if (data.stages) setProcessingStages(data.stages)

      if (data.status === 'completed') {
        setActiveStep('qa')
        setProcessResult(data)
        setPausedSession(null)
        // Automatically open the WordPress draft editor in a new tab (Priority 4)
        const editUrl = data.destination?.edit_url || data.draft_result?.data?.edit_url
        if (editUrl) {
          try {
            window.open(editUrl, '_blank')
          } catch (e) {
            log.info?.('Popup blocked by browser', e)
          }
        }
      } else {
        setProcessError(data.error || 'Failed to complete draft creation.')
      }
    } catch (err) {
      setProcessError('Error resuming workflow: ' + err.message)
    } finally {
      setResuming(false)
    }
  }

  function handleContentSelection() {
    const sel = window.getSelection()
    if (!sel || sel.rangeCount === 0) return
    const text = sel.toString().trim()
    if (!text) return
    setSelectedAnchorText(text)
    const words = text.split(/\s+/).filter(Boolean)
    setSelectedWordCount(words.length)
    setLinkAttachError(null)
  }

  function handleAttachLink() {
    setLinkAttachError(null)
    if (!selectedAnchorText) {
      setLinkAttachError('Please highlight consecutive words in the article text first.')
      return
    }
    if (!targetLinkUrl || !targetLinkUrl.trim()) {
      setLinkAttachError('Please enter a target URL.')
      return
    }

    const url = targetLinkUrl.trim()
    const isInternal = url.toLowerCase().includes('homebusinessmag.com')

    if (isInternal) {
      if (selectedWordCount < 3 || selectedWordCount > 5) {
        setLinkAttachError(`Internal link anchor must be strictly 3 to 5 consecutive words (currently ${selectedWordCount}).`)
        return
      }
    } else {
      if (selectedWordCount < 3 || selectedWordCount > 4) {
        setLinkAttachError(`Authority link anchor must be strictly 3 to 4 consecutive words (currently ${selectedWordCount}).`)
        return
      }
    }

    const currentContent = editedArticleContent || pausedSession?.ai_result?.content || ''
    if (!currentContent.includes(selectedAnchorText)) {
      setLinkAttachError('Selected text could not be located in article content. Please select again.')
      return
    }

    const linkedSnippet = `<a href="${url}" target="_blank" rel="noopener noreferrer">${selectedAnchorText}</a>`
    const updated = currentContent.replace(selectedAnchorText, linkedSnippet)
    setEditedArticleContent(updated)
    setSelectedAnchorText('')
    setSelectedWordCount(0)
    setTargetLinkUrl('')
  }

  function handleRemoveLink(urlToRemove) {
    const currentContent = editedArticleContent || pausedSession?.ai_result?.content || ''
    const regex = new RegExp(`<a\\b[^>]*href=["']${urlToRemove.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}["'][^>]*>(.*?)<\\/a>`, 'gi')
    const updated = currentContent.replace(regex, '$1')
    setEditedArticleContent(updated)
  }

  async function handleSaveSite(e) {
    e.preventDefault()
    setSiteSaving(true)
    setSiteTestResult(null)
    try {
      const res = await (authFetch || fetch)(`${API_BASE}/api/wordpress/sites`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(siteForm),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Failed to save site')
      }
      const data = await res.json()
      await fetchSites()
      if (data.site?.id) setSelectedSiteId(String(data.site.id))
      setShowSiteModal(false)
      setSiteForm({ name: '', url: '', username: '', app_password: '', is_default: false })
      setBanner({ type: 'success', message: 'WordPress site added successfully!' })
    } catch (err) {
      setSiteTestResult({ success: false, error: err.message })
    } finally {
      setSiteSaving(false)
    }
  }

  async function handleTestSelectedSite() {
    if (!selectedSiteId) return
    setSiteTesting(true)
    setSiteTestResult(null)
    try {
      const res = await (authFetch || fetch)(`${API_BASE}/api/wordpress/sites/${selectedSiteId}/test`, { method: 'POST' })
      const data = await res.json()
      setSiteTestResult(data)
    } catch (err) {
      setSiteTestResult({ success: false, error: err.message })
    } finally {
      setSiteTesting(false)
    }
  }

  async function handleProcess() {
    if (!selectedSiteId) {
      setProcessError('Please select a WordPress site before processing.')
      return
    }
    if (!connected) {
      setProcessError('Please connect Basecamp before selecting/processing articles.')
      return
    }
    if (!selectedProject || !selectedMessage || !selectedAttachment) {
      setProcessError('Please select a Basecamp project, article message, and Word attachment.')
      return
    }

    setProcessing(true)
    resetProcessing()
    setActiveStep('docx')
    setCurrentView('live_workflow')

    await new Promise(r => setTimeout(r, 400))
    setActiveStep('duplicate')

    try {
      const res = await (authFetch || fetch)(`${API_BASE}/api/articles/process`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: selectedProject.id,
          message_id: selectedMessage.id,
          attachment_id: String(selectedAttachment.id),
          site_id: parseInt(selectedSiteId, 10),
          author_id: selectedAuthorId ? parseInt(selectedAuthorId, 10) : undefined,
          image_provider: selectedProvider,
          selected_image_data: selectedImage,
          pause_at_image: pauseAtImageGate,
        }),
      })
      const data = await res.json()
      if (data.stages) setProcessingStages(data.stages)

      if (data.status === 'paused_image') {
        setActiveStep('image')
        setPausedSession(data)
        if (data.image_candidates && data.image_candidates.length > 0) {
          setSelectedCandidate(data.image_candidates[0])
        }
        if (data.ai_result?.content) {
          setEditedArticleContent(data.ai_result.content)
        }
      } else if (data.status === 'duplicate') {
        setActiveStep('duplicate')
        setProcessResult(data)
      } else if (data.status === 'completed') {
        setActiveStep('qa')
        await new Promise(r => setTimeout(r, 300))
        setProcessResult(data)
        setPausedSession(null)
        // Automatically open the WordPress draft editor in a new tab (Priority 4)
        const editUrl = data.destination?.edit_url || data.draft_result?.data?.edit_url
        if (editUrl) {
          try {
            window.open(editUrl, '_blank')
          } catch (e) {
            log.info?.('Popup blocked by browser', e)
          }
        }
      } else {
        setProcessResult(data)
        setProcessError(data.error || 'Processing failed.')
        if (data.envato_result || data.image_result) setActiveStep('image')
        else setActiveStep('docx')
      }
    } catch {
      setProcessError('Could not reach backend.')
      setActiveStep(null)
    } finally {
      setProcessing(false)
    }
  }

  // ── Pipeline Status Helper
  function getStepStatus(stepKey) {
    if (stepKey === 'site') return selectedSiteId ? 'completed' : 'pending'
    if (stepKey === 'basecamp') return connected ? 'completed' : 'pending'
    if (stepKey === 'docx') {
      if (processing && activeStep === 'docx') return 'processing'
      if (pausedSession || processResult) return 'completed'
      return selectedAttachment ? 'completed' : 'pending'
    }
    if (stepKey === 'duplicate') {
      if (processing && activeStep === 'duplicate') return 'processing'
      if (processResult?.duplicate_result?.status === 'DUPLICATE FOUND' || processResult?.status === 'duplicate') return 'duplicate'
      if (pausedSession || processResult?.status === 'completed' || processResult?.duplicate_result?.status === 'PASSED') return 'completed'
      return 'pending'
    }
    if (stepKey === 'seo') {
      if (activeStep === 'seo' && processing) return 'processing'
      if (pausedSession?.ai_result?.focus_keyphrase || processResult?.ai_result?.focus_keyphrase || processResult?.yoast_result?.status === 'PASSED') return 'completed'
      return 'pending'
    }
    if (stepKey === 'image') {
      if (pausedSession) return 'paused'
      if (activeStep === 'image' && (processing || resuming)) return 'processing'
      if (processResult?.envato_result?.status === 'PASSED' || processResult?.image_result?.status === 'PASSED' || processResult?.destination?.featured_media_id) return 'completed'
      if (processResult?.envato_result?.status === 'FAILED' || processResult?.image_result?.status === 'FAILED') return 'failed'
      return 'pending'
    }
    if (stepKey === 'wp_draft') {
      if (resuming) return 'processing'
      if (processResult?.draft_result?.status === 'success' && processResult.draft_result.data?.post_id) return 'completed'
      if (processResult?.draft_result) return 'failed'
      return 'pending'
    }
    if (stepKey === 'qa') {
      if (processResult?.qa_result?.status === 'PASSED' || processResult?.qa_checklist) return 'completed'
      if (processResult?.qa_result) return 'failed'
      return 'pending'
    }
    return 'pending'
  }

  function PipelineBadge({ status }) {
    if (status === 'completed') return <span className="text-xs bg-emerald-100 text-emerald-700 px-2.5 py-0.5 rounded-full font-semibold ring-1 ring-emerald-200">Done</span>
    if (status === 'processing') return <span className="text-xs bg-indigo-100 text-indigo-700 px-2.5 py-0.5 rounded-full font-semibold ring-1 ring-indigo-200 animate-pulse">Running</span>
    if (status === 'paused') return <span className="text-xs bg-amber-100 text-amber-800 px-2.5 py-0.5 rounded-full font-bold ring-1 ring-amber-300 animate-pulse">Paused at Gate</span>
    if (status === 'duplicate') return <span className="text-xs bg-amber-100 text-amber-800 px-2.5 py-0.5 rounded-full font-semibold ring-1 ring-amber-300">Duplicate Found</span>
    if (status === 'failed') return <span className="text-xs bg-red-100 text-red-700 px-2.5 py-0.5 rounded-full font-semibold ring-1 ring-red-200">Failed</span>
    return <span className="text-xs bg-slate-100 text-slate-500 px-2.5 py-0.5 rounded-full font-medium ring-1 ring-slate-200">Pending</span>
  }

  const pipelineSteps = [
    { key: 'site', label: '1. WordPress Site Selected' },
    { key: 'basecamp', label: '2. Basecamp Connected' },
    { key: 'docx', label: '3. DOCX Extracted' },
    { key: 'duplicate', label: '4. Duplicate Check' },
    { key: 'seo', label: '5. SEO & Keyphrase (Gemini)' },
    { key: 'image', label: '6. Image Acquisition (1000px)' },
    { key: 'wp_draft', label: '7. WordPress Draft' },
    { key: 'qa', label: '8. 28-Point QA Verification' },
  ]

  const activeSelectedSite = sites.find(s => String(s.id) === String(selectedSiteId))

  return (
    <div className="space-y-4 max-w-[1600px] h-[calc(100vh-6rem)] flex flex-col">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Workflow Dashboard</h1>
          <p className="text-slate-500 mt-0.5 text-sm">
            Automate Basecamp article processing to WordPress drafts with live 28-point QA verification.
          </p>
        </div>
      </div>

      {banner && (
        <div className={`px-4 py-2 rounded-lg text-sm flex justify-between items-center ${banner.type === 'error' ? 'bg-red-50 text-red-700 border border-red-200' : 'bg-emerald-50 text-emerald-700 border border-emerald-200'}`}>
          <span>{banner.message}</span>
          <button onClick={() => setBanner(null)} className="font-bold opacity-60 hover:opacity-100">✕</button>
        </div>
      )}

      {/* Prominent Workflow Mode Selector */}
      <div className="bg-slate-100 p-1.5 rounded-xl border border-slate-200 flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
        <button
          type="button"
          onClick={() => setWorkflowMode('create_draft')}
          className={`flex-1 flex items-center justify-center gap-2.5 py-2.5 px-4 rounded-lg font-semibold text-xs transition-all ${
            workflowMode === 'create_draft'
              ? 'bg-white text-indigo-700 shadow-xs border border-indigo-200 ring-1 ring-indigo-200 font-bold'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
          }`}
        >
          <span className={`w-2.5 h-2.5 rounded-full ${workflowMode === 'create_draft' ? 'bg-indigo-600 ring-4 ring-indigo-100' : 'bg-slate-400'}`} />
          <span className="flex flex-col sm:flex-row items-center gap-1 sm:gap-2">
            <strong className="tracking-wide uppercase text-xs">Create Draft</strong>
            <span className="font-normal text-slate-500 text-[11px]">(Pipeline View: Basecamp &rarr; Formatting &rarr; WordPress Draft)</span>
          </span>
        </button>
        <button
          type="button"
          onClick={() => setWorkflowMode('qa_only')}
          className={`flex-1 flex items-center justify-center gap-2.5 py-2.5 px-4 rounded-lg font-semibold text-xs transition-all ${
            workflowMode === 'qa_only'
              ? 'bg-white text-emerald-800 shadow-xs border border-emerald-300 ring-1 ring-emerald-200 font-bold'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
          }`}
        >
          <span className={`w-2.5 h-2.5 rounded-full ${workflowMode === 'qa_only' ? 'bg-emerald-600 ring-4 ring-emerald-100' : 'bg-slate-400'}`} />
          <span className="flex flex-col sm:flex-row items-center gap-1 sm:gap-2">
            <strong className="tracking-wide uppercase text-xs">QA Only</strong>
            <span className="font-normal text-slate-500 text-[11px]">(Read-Only Draft Audit: Existing WordPress Drafts with Zero Writes)</span>
          </span>
        </button>
      </div>

      {workflowMode === 'create_draft' ? (
        currentView === 'live_workflow' ? (
          /* ── LIVE WORKFLOW SCREEN ─────────────────────────────────────────── */
          <div className="flex flex-col gap-4 flex-1 min-h-0">
            {/* Header Bar */}
            <div className="flex items-center justify-between bg-slate-900 text-white rounded-xl px-5 py-3 shadow-sm">
              <div className="flex items-center gap-3">
                <span className="text-lg">⚡</span>
                <div>
                  <h2 className="text-sm font-bold tracking-wide">Live Workflow Execution</h2>
                  <p className="text-[11px] text-slate-300 truncate max-w-[400px]">
                    {selectedAttachment?.filename || 'Processing article…'}
                  </p>
                </div>
              </div>
              <button
                onClick={() => {
                  setCurrentView('dashboard')
                  if (!processing && !resuming) {
                    resetProcessing()
                  }
                }}
                className="text-xs text-slate-300 hover:text-white border border-slate-600 hover:border-slate-400 px-3 py-1.5 rounded-lg transition-all font-medium"
              >
                ← Back to Article Selection
              </button>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 flex-1 min-h-0">

              {/* Column 1: 10-Stage Tracker */}
              <div className="bg-white border border-slate-200 rounded-xl shadow-sm flex flex-col overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-100 bg-slate-50/50">
                  <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wide">Pipeline Stages</h3>
                </div>
                <div className="p-4 space-y-2 flex-1 overflow-y-auto">
                  {[
                    { key: 'docx_download',    label: '1. DOCX Download' },
                    { key: 'docx_extraction',  label: '2. DOCX Extraction' },
                    { key: 'duplicate_check',  label: '3. Duplicate Check' },
                    { key: 'gemini_content',   label: '4. Gemini Content Processing' },
                    { key: 'seo_metadata',     label: '5. SEO Title & Meta Description' },
                    { key: 'links_processing', label: '6. Internal & External Links' },
                    { key: 'yoast_validation', label: '7. Yoast SEO Validation' },
                    { key: 'featured_image',   label: '8. Manual Featured Image Upload' },
                    { key: 'wp_draft',         label: '9. WordPress Draft Creation' },
                    { key: 'qa_verification',  label: '10. Final QA Verification' },
                  ].map(stage => {
                    const stageStatuses = pausedSession?.stage_statuses || processResult?.stage_statuses || {}
                    const stageStatus = stageStatuses[stage.key] || 'pending'
                    // Infer running stage from pipeline activeStep mapping
                    const isRunning = processing && (
                      (stage.key === 'docx_download' && activeStep === 'docx') ||
                      (stage.key === 'docx_extraction' && activeStep === 'docx') ||
                      (stage.key === 'duplicate_check' && activeStep === 'duplicate') ||
                      (stage.key === 'featured_image' && (activeStep === 'image' || resuming)) ||
                      (stage.key === 'wp_draft' && resuming)
                    )
                    const effectiveStatus = isRunning ? 'processing' : stageStatus
                    const isPaused = stage.key === 'featured_image' && !!pausedSession
                    return (
                      <div key={stage.key} className="flex items-center justify-between py-1.5 border-b border-slate-50 last:border-0">
                        <span className={`text-xs ${effectiveStatus === 'completed' ? 'text-slate-800 font-semibold' : effectiveStatus === 'failed' ? 'text-red-600 font-semibold' : 'text-slate-500'}`}>
                          {stage.label}
                        </span>
                        {isPaused ? (
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-300 animate-pulse">Paused</span>
                        ) : effectiveStatus === 'completed' ? (
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 border border-emerald-200">✓ Done</span>
                        ) : effectiveStatus === 'processing' ? (
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 border border-indigo-200 animate-pulse">Running…</span>
                        ) : effectiveStatus === 'failed' ? (
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-red-100 text-red-600 border border-red-200">Failed</span>
                        ) : (
                          <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-400 border border-slate-200">Pending</span>
                        )}
                      </div>
                    )
                  })}
                </div>

                {/* Backend Execution Log */}
                {(processingStages.length > 0 || processing || resuming) && (
                  <div className="border-t border-slate-200 bg-slate-900 rounded-b-xl p-3 max-h-48 overflow-y-auto">
                    <p className="text-[9px] text-slate-400 font-bold uppercase tracking-wider mb-1.5">Execution Log</p>
                    {processingStages.map((stg, idx) => (
                      <div key={idx} className="flex items-start gap-1 text-[10px] leading-relaxed">
                        <span className="text-emerald-400 select-none shrink-0">›</span>
                        <span className={stg.startsWith('Error') ? 'text-red-400 font-bold' : stg.includes('⏸') ? 'text-amber-300 font-bold' : 'text-slate-300'}>
                          {stg}
                        </span>
                      </div>
                    ))}
                    {(processing || resuming) && (
                      <div className="flex items-center gap-1.5 text-indigo-400 animate-pulse pt-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-ping shrink-0" />
                        <span className="text-[10px]">Processing…</span>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Column 2: Image Gate / Article Preview / Error */}
              <div className="bg-white border border-slate-200 rounded-xl shadow-sm flex flex-col overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-100 bg-slate-50/50">
                  <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wide">
                    {pausedSession ? '⏸ Manual Image Approval Gate' : processResult?.status === 'completed' ? '✓ Completed' : 'Article Content Preview'}
                  </h3>
                </div>
                <div className="p-4 flex-1 overflow-y-auto space-y-4">
                  {processError && (
                    <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-xs text-red-700">
                      <p className="font-bold mb-1">Error</p>
                      <p>{processError}</p>
                    </div>
                  )}

                  {/* Image Approval Gate */}
                  {pausedSession && (
                    <div className="space-y-3">
                      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-900">
                        <p className="font-bold text-sm mb-1">Stage 8: Upload Your Featured Image</p>
                        <p className="text-[11px]">Workflow is paused. Download an image from any platform, then upload it below. Only your uploaded image will be used as the WordPress featured image.</p>
                      </div>

                      {/* Upload control */}
                      <div className="space-y-2">
                        <label className="block w-full cursor-pointer py-3 px-4 bg-slate-800 hover:bg-slate-900 text-white rounded-lg text-xs font-bold text-center transition-colors">
                          📁 Choose Image File…
                          <input type="file" accept="image/*" className="hidden" onChange={handleImageFileUpload} />
                        </label>

                        {/* Preview of uploaded image */}
                        {selectedCandidate?.raw_image_base64 && (
                          <div className="space-y-2">
                            <img
                              src={selectedCandidate.raw_image_base64}
                              alt="Preview"
                              className="w-full rounded-lg border border-slate-200 object-cover max-h-48"
                            />
                            <div className="text-[10px] text-slate-600 bg-slate-50 border border-slate-200 rounded p-2 space-y-0.5">
                              <div><strong>File:</strong> {selectedCandidate.filename}</div>
                              <div><strong>Alt Text (Focus Keyphrase):</strong> {pausedSession.ai_result?.focus_keyphrase || '—'}</div>
                            </div>
                            <label className="block text-center text-[11px] text-slate-500 cursor-pointer hover:text-indigo-600">
                              Replace image
                              <input type="file" accept="image/*" className="hidden" onChange={handleImageFileUpload} />
                            </label>
                          </div>
                        )}

                        {!selectedCandidate?.raw_image_base64 && (
                          <p className="text-[11px] text-slate-400 text-center py-4 border border-dashed border-slate-200 rounded-lg">
                            No image selected yet. Choose a file above.
                          </p>
                        )}
                      </div>

                      {/* Content & Link Review */}
                      <button
                        onClick={() => setShowLinkReviewModal(true)}
                        className="w-full py-2 px-3 bg-indigo-50 border border-indigo-200 text-indigo-700 hover:bg-indigo-100 rounded-lg font-semibold text-xs flex items-center justify-center gap-2"
                      >
                        🔗 Review Content & Links (Optional)
                      </button>

                      {/* Approve Button */}
                      <button
                        onClick={handleResumePipeline}
                        disabled={!selectedCandidate?.raw_image_base64 || resuming}
                        className="w-full py-3 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-300 disabled:text-slate-500 text-white font-bold rounded-xl text-xs uppercase tracking-wider flex items-center justify-center gap-2 transition-all shadow-sm"
                      >
                        {resuming ? <><Spinner label="" /> Creating WordPress Draft…</> : '✓ Approve Image & Continue to Draft Creation →'}
                      </button>
                      {!selectedCandidate?.raw_image_base64 && (
                        <p className="text-[11px] text-amber-700 text-center font-medium">Upload an image above before continuing.</p>
                      )}
                    </div>
                  )}

                  {/* Draft Completed */}
                  {processResult?.status === 'completed' && !pausedSession && (
                    <div className="space-y-3">
                      <div className="bg-emerald-50 border-2 border-emerald-400 rounded-xl p-4 space-y-2.5">
                        <div className="flex items-center gap-2">
                          <span className="text-2xl">🎉</span>
                          <div>
                            <p className="font-bold text-emerald-900 text-sm">WordPress Draft Created!</p>
                            <p className="text-[11px] text-emerald-700">Post #{processResult.destination?.post_id} on {processResult.destination?.wordpress_site_name}</p>
                          </div>
                        </div>
                        <a
                          href={processResult.destination?.edit_url || processResult.destination?.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center justify-center gap-2 w-full py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-bold uppercase tracking-wider transition-colors"
                        >
                          Open WordPress Draft Editor ↗
                        </a>
                        <button
                          onClick={() => {
                            navigator.clipboard.writeText(processResult.destination?.edit_url || processResult.destination?.url || '')
                            setCopiedUrl(true)
                            setTimeout(() => setCopiedUrl(false), 2000)
                          }}
                          className="w-full py-2 bg-white border border-emerald-200 text-emerald-700 hover:bg-emerald-50 rounded-lg text-xs font-semibold"
                        >
                          {copiedUrl ? '✓ URL Copied!' : '📋 Copy Editor URL'}
                        </button>
                        <p className="text-[10px] text-emerald-600 italic text-center">If auto-open was blocked, use the button above.</p>
                      </div>
                    </div>
                  )}

                  {/* Pending / Processing state */}
                  {!pausedSession && !processResult && !processError && (
                    <div className="flex flex-col items-center justify-center py-12 text-center space-y-3">
                      {processing ? (
                        <>
                          <div className="w-10 h-10 rounded-full border-4 border-indigo-200 border-t-indigo-600 animate-spin" />
                          <p className="text-sm font-semibold text-slate-700">Processing your article…</p>
                          <p className="text-xs text-slate-500">This may take 30–60 seconds. Please wait.</p>
                        </>
                      ) : (
                        <p className="text-xs text-slate-400 italic">Awaiting process start…</p>
                      )}
                    </div>
                  )}

                  {/* Requirement 3: Live Article Content Preview */}
                  {(pausedSession?.ai_result || processResult?.ai_result) && (() => {
                    const aiData = pausedSession?.ai_result || processResult?.ai_result
                    const internalLinks = aiData?.internal_links || []
                    const authorityLinks = aiData?.authority_links || []
                    const docxLinks = aiData?.docx_hyperlinks || []
                    const activeContent = editedArticleContent || aiData?.content || ''

                    return (
                      <div className="border-t border-slate-200 pt-3 space-y-3">
                        <div className="flex items-center justify-between pb-1 border-b border-slate-100">
                          <span className="text-[11px] font-bold text-slate-700 uppercase tracking-wide flex items-center gap-1.5">
                            <span>📄</span> Live Article Preview
                          </span>
                          <span className="text-[10px] text-slate-400">
                            DOCX Parity Preserved
                          </span>
                        </div>

                        {/* Article Title */}
                        <div className="bg-slate-50 border border-slate-200 rounded-lg p-2.5">
                          <span className="text-[9px] font-bold text-slate-400 uppercase tracking-wider block">Article Title</span>
                          <h4 className="font-bold text-slate-800 text-sm mt-0.5 leading-snug">
                            {aiData?.title || selectedMessage?.subject || 'Untitled Article'}
                          </h4>
                        </div>

                        {/* Attached Links Summary Cards */}
                        <div className="space-y-1.5">
                          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wide block">Attached Links & Anchors</span>
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[10px]">
                            {/* Internal Links */}
                            <div className="bg-blue-50/70 border border-blue-200 rounded-lg p-2 space-y-1">
                              <div className="flex items-center justify-between font-bold text-blue-900">
                                <span>Internal Links (3-5 words)</span>
                                <span className="bg-blue-200/80 text-blue-800 px-1.5 py-0.2 rounded font-mono">{internalLinks.length}</span>
                              </div>
                              {internalLinks.length > 0 ? (
                                <div className="space-y-1 max-h-24 overflow-y-auto">
                                  {internalLinks.map((lk, i) => (
                                    <div key={i} className="truncate text-blue-800">
                                      <strong className="text-blue-950">"{lk.anchor_text || lk.anchor || 'Anchor'}"</strong> &rarr; <span className="text-blue-600">{lk.url || lk.target_url}</span>
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <p className="text-blue-600/70 italic text-[9px]">None added yet</p>
                              )}
                            </div>

                            {/* Authority Links */}
                            <div className="bg-purple-50/70 border border-purple-200 rounded-lg p-2 space-y-1">
                              <div className="flex items-center justify-between font-bold text-purple-900">
                                <span>Authority Links (3-4 words)</span>
                                <span className="bg-purple-200/80 text-purple-800 px-1.5 py-0.2 rounded font-mono">{authorityLinks.length}</span>
                              </div>
                              {authorityLinks.length > 0 ? (
                                <div className="space-y-1 max-h-24 overflow-y-auto">
                                  {authorityLinks.map((lk, i) => (
                                    <div key={i} className="truncate text-purple-800">
                                      <strong className="text-purple-950">"{lk.anchor_text || lk.anchor || 'Anchor'}"</strong> &rarr; <span className="text-purple-600">{lk.url || lk.target_url}</span>
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <p className="text-purple-600/70 italic text-[9px]">None added yet</p>
                              )}
                            </div>
                          </div>

                          {/* Preserved DOCX Links */}
                          {docxLinks.length > 0 && (
                            <div className="bg-slate-50 border border-slate-200 rounded-lg p-2 text-[10px] space-y-1">
                              <div className="flex items-center justify-between font-bold text-slate-700">
                                <span>Original DOCX Hyperlinks Preserved</span>
                                <span className="bg-slate-200 text-slate-700 px-1.5 py-0.2 rounded font-mono">{docxLinks.length}</span>
                              </div>
                              <div className="space-y-0.5 max-h-20 overflow-y-auto text-slate-600">
                                {docxLinks.slice(0, 5).map((dl, i) => (
                                  <div key={i} className="truncate">
                                    <strong>"{dl.anchor_text || dl.text || 'Link'}"</strong> &rarr; {dl.url}
                                  </div>
                                ))}
                                {docxLinks.length > 5 && (
                                  <div className="text-[9px] text-slate-400 italic">+{docxLinks.length - 5} more DOCX links preserved</div>
                                )}
                              </div>
                            </div>
                          )}
                        </div>

                        {/* Full Rendered Body Paragraphs & Headings */}
                        <div className="space-y-1">
                          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wide block">Content & Headings (H2 / H3)</span>
                          <div
                            className="bg-slate-50/80 border border-slate-200 rounded-lg p-3 text-xs space-y-2 max-h-80 overflow-y-auto text-slate-800 prose prose-xs max-w-none leading-relaxed"
                            dangerouslySetInnerHTML={{ __html: activeContent }}
                          />
                        </div>
                      </div>
                    )
                  })()}
                </div>
              </div>

              {/* Column 3: SEO & Destination Details */}
              <div className="bg-white border border-slate-200 rounded-xl shadow-sm flex flex-col overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-100 bg-slate-50/50">
                  <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wide">SEO & Destination</h3>
                </div>
                <div className="p-4 flex-1 overflow-y-auto space-y-3 text-xs">
                  {/* Site */}
                  <div className="bg-slate-50 border border-slate-200 rounded-lg p-2.5 space-y-0.5">
                    <p className="text-[10px] font-bold text-slate-400 uppercase">Destination Site</p>
                    <p className="font-bold text-slate-800">{activeSelectedSite?.name || 'Not selected'}</p>
                    <p className="text-slate-500 text-[11px]">{activeSelectedSite?.url || '—'}</p>
                    <p className="text-[10px] text-amber-700 font-medium pt-0.5">⚠️ DRAFT ONLY — never auto-published</p>
                  </div>

                  {/* SEO fields once available */}
                  {(pausedSession?.ai_result || processResult?.ai_result) && (() => {
                    const seo = pausedSession?.ai_result || processResult?.ai_result
                    const metaLen = (seo?.meta_description || '').length
                    const metaOk = metaLen >= 140 && metaLen <= 155
                    return (
                      <div className="space-y-2">
                        <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-2.5 space-y-0.5">
                          <p className="text-[10px] font-bold text-indigo-800 uppercase">Focus Keyphrase</p>
                          <p className="font-mono font-bold text-indigo-700">{seo?.focus_keyphrase || '—'}</p>
                        </div>
                        <div>
                          <p className="text-[10px] font-bold text-slate-400 uppercase">SEO Title</p>
                          <p className="text-slate-700 font-medium mt-0.5">{seo?.seo_title || '—'}</p>
                        </div>
                        <div>
                          <div className="flex items-center justify-between">
                            <p className="text-[10px] font-bold text-slate-400 uppercase">Meta Description</p>
                            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${metaOk ? 'bg-emerald-100 text-emerald-700 border-emerald-200' : 'bg-red-100 text-red-600 border-red-200'}`}>
                              {metaLen} chars {metaOk ? '✓ 140-155' : '✗ out of range'}
                            </span>
                          </div>
                          <p className="text-slate-600 mt-0.5 leading-relaxed">{seo?.meta_description || '—'}</p>
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <p className="text-[10px] font-bold text-slate-400 uppercase">Category</p>
                            <p className="text-slate-700 font-medium mt-0.5">{(pausedSession || processResult)?.article?.filename ? (pausedSession?.category_info?.primary || processResult?.destination?.primary_category || '—') : '—'}</p>
                          </div>
                          <div>
                            <p className="text-[10px] font-bold text-slate-400 uppercase">Slug</p>
                            <p className="text-slate-600 font-mono text-[10px] mt-0.5 break-all">{seo?.slug || '—'}</p>
                          </div>
                        </div>
                        {processResult?.destination?.post_id && (
                          <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-2.5">
                            <p className="text-[10px] font-bold text-emerald-800 uppercase">WordPress Post</p>
                            <p className="text-emerald-700 font-bold mt-0.5">#{processResult.destination.post_id}</p>
                            {processResult.destination?.edit_url && (
                              <a href={processResult.destination.edit_url} target="_blank" rel="noopener noreferrer" className="text-[11px] text-emerald-600 hover:underline font-medium">
                                Open Editor ↗
                              </a>
                            )}
                          </div>
                        )}
                        {/* QA summary */}
                        {processResult?.qa_checklist && (
                          <div className="bg-slate-50 border border-slate-200 rounded-lg p-2.5 space-y-1.5 max-h-48 overflow-y-auto">
                            <p className="text-[10px] font-bold text-slate-600 uppercase">28-Point QA Checklist</p>
                            {Object.entries(processResult.qa_checklist).map(([sectionKey, items]) => (
                              <div key={sectionKey}>
                                <p className="text-[9px] font-bold uppercase tracking-wider text-slate-500 mt-1">{sectionKey.replace(/_/g, ' ')}</p>
                                {typeof items === 'object' && items !== null && Object.entries(items).map(([k, val]) => {
                                  const status = typeof val === 'object' ? val.status : (val ? 'PASS' : 'FAIL')
                                  const label = typeof val === 'object' ? val.label : k.replace(/_/g, ' ')
                                  return (
                                    <div key={k} className="flex items-center justify-between py-0.5">
                                      <span className="text-slate-600 text-[10px] truncate mr-2">{label}</span>
                                      <QABadge status={status} />
                                    </div>
                                  )
                                })}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  })()}

                  {!pausedSession?.ai_result && !processResult?.ai_result && (
                    <p className="text-slate-400 text-[11px] italic text-center pt-8">SEO data will appear once processing completes.</p>
                  )}
                </div>
              </div>

            </div>
          </div>
        ) : (
        /* 3-Column Layout */
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1 min-h-0">
        
        {/* ========================================================
            PANEL 1 — BASECAMP & WORKFLOW INPUTS
            ======================================================== */}
        <SectionCard 
          title="1. Workflow Setup" 
          actions={
            <div className="flex items-center gap-2">
              <StatusBadge connected={connected} />
            </div>
          }
        >
          <div className="space-y-4">
            
            {/* 1. WORDPRESS SITE SELECTION — FIRST */}
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5 space-y-2.5">
              <div className="flex justify-between items-center">
                <label className="text-xs font-bold text-slate-700 uppercase tracking-wide flex items-center gap-1.5">
                  <span className="w-4 h-4 rounded-full bg-indigo-600 text-white flex items-center justify-center text-[10px]">1</span>
                  WordPress Destination Site
                </label>
                <button
                  onClick={() => setShowSiteModal(true)}
                  className="text-[11px] font-semibold text-indigo-600 hover:text-indigo-800 hover:underline"
                >
                  + Add / Manage
                </button>
              </div>

              {sitesLoading ? <Spinner label="Loading WordPress sites..." /> : (
                <div className="space-y-2">
                  <select
                    className="w-full text-xs font-medium border-slate-300 rounded-lg p-2.5 bg-white shadow-xs focus:ring-indigo-500 focus:border-indigo-500"
                    value={selectedSiteId}
                    onChange={e => {
                      setSelectedSiteId(e.target.value)
                      setSelectedAuthorId('')
                      setSiteTestResult(null)
                    }}
                  >
                    <option value="">-- Select Destination WordPress Site --</option>
                    {sites.map(site => (
                      <option key={site.id} value={site.id}>
                        {site.name} ({site.url}) {site.is_default ? '★ Default' : ''}
                      </option>
                    ))}
                  </select>

                  {activeSelectedSite && (
                    <div className="flex items-center justify-between text-[11px] text-slate-500 pt-1">
                      <span className="truncate">Connected as: <strong className="text-slate-700">{activeSelectedSite.username}</strong></span>
                      <button
                        onClick={handleTestSelectedSite}
                        disabled={siteTesting}
                        className="text-xs text-indigo-600 hover:underline font-semibold"
                      >
                        {siteTesting ? 'Testing...' : 'Test Auth ⚡'}
                      </button>
                    </div>
                  )}

                  {siteTestResult && (
                    <div className={`p-2 rounded text-[11px] ${siteTestResult.success ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-red-50 text-red-700 border border-red-200'}`}>
                      {siteTestResult.success ? `✓ Authentication verified (${siteTestResult.name})` : `✗ ${siteTestResult.error}`}
                    </div>
                  )}

                  {/* WordPress Author Dropdown */}
                  {selectedSiteId && (
                    <div className="pt-2.5 border-t border-slate-200/80 space-y-1">
                      <div className="flex justify-between items-center">
                        <label className="text-[11px] font-bold text-slate-700 uppercase tracking-wide">
                          WordPress Author
                        </label>
                        {authorsLoading && (
                          <span className="text-[10px] text-slate-400">Loading authors...</span>
                        )}
                      </div>
                      <select
                        className="w-full text-xs font-medium border-slate-300 rounded-lg p-2 bg-white shadow-xs focus:ring-indigo-500 focus:border-indigo-500"
                        value={selectedAuthorId}
                        onChange={e => setSelectedAuthorId(e.target.value)}
                        disabled={authorsLoading}
                      >
                        <option value="">-- Default / Site Author --</option>
                        {authors.map(author => (
                          <option key={author.id} value={author.id}>
                            {author.name} {author.slug ? `(@${author.slug})` : ''}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* 2. BASECAMP CONNECTION */}
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5 space-y-2.5">
              <div className="flex justify-between items-center">
                <label className="text-xs font-bold text-slate-700 uppercase tracking-wide flex items-center gap-1.5">
                  <span className="w-4 h-4 rounded-full bg-indigo-600 text-white flex items-center justify-center text-[10px]">2</span>
                  Basecamp Connection
                </label>
                {!connected && !statusLoading && (
                  <button
                    onClick={handleConnect}
                    className="text-xs bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-1 rounded font-semibold transition-colors shadow-xs"
                  >
                    Connect Basecamp
                  </button>
                )}
              </div>

              {!connected ? (
                tokenExpired ? (
                  <div className="flex items-center justify-between text-xs p-2.5 bg-amber-50 border border-amber-200 rounded-lg">
                    <div className="space-y-0.5">
                      <span className="text-amber-800 font-semibold block">Basecamp Session Expired</span>
                      <span className="text-amber-600 text-[11px]">Your access token has expired. Click refresh to renew.</span>
                    </div>
                    <button
                      onClick={handleRefreshBasecamp}
                      disabled={refreshingBc}
                      className="px-3 py-1.5 bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white rounded font-semibold text-xs transition-colors shadow-xs"
                    >
                      {refreshingBc ? 'Refreshing...' : 'Refresh Connection'}
                    </button>
                  </div>
                ) : (
                  <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-2.5">
                    Please connect Basecamp before selecting or processing articles.
                  </p>
                )
              ) : (
                <div className="flex items-center justify-between text-xs text-slate-600 pt-0.5">
                  <span>Basecamp Account Connected</span>
                  <span className="text-emerald-700 font-bold">✓ Ready</span>
                </div>
              )}
            </div>

            {connected && (
              <>
                {/* 3. DATE FILTER & 4. PROJECT SELECTION */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {/* Date Picker */}
                  <div>
                    <label className="text-xs font-bold text-slate-700 uppercase tracking-wide flex items-center gap-1.5 mb-1.5">
                      <span className="w-4 h-4 rounded-full bg-indigo-600 text-white flex items-center justify-center text-[10px]">3</span>
                      Date Filter
                    </label>
                    <input
                      type="date"
                      value={selectedDate}
                      onChange={e => setSelectedDate(e.target.value)}
                      className="w-full text-xs border border-slate-300 rounded-lg p-2.5 bg-white focus:ring-indigo-500 focus:border-indigo-500"
                    />
                    {selectedDate && (
                      <button
                        onClick={() => setSelectedDate('')}
                        className="text-[11px] text-slate-400 hover:text-slate-600 mt-1 block"
                      >
                        Clear date filter
                      </button>
                    )}
                  </div>

                  {/* Project Selector */}
                  <div>
                    <label className="text-xs font-bold text-slate-700 uppercase tracking-wide flex items-center gap-1.5 mb-1.5">
                      <span className="w-4 h-4 rounded-full bg-indigo-600 text-white flex items-center justify-center text-[10px]">4</span>
                      Project
                    </label>
                    {projectsLoading ? <Spinner label="Loading projects..." /> : (
                      <>
                        <select
                          className="w-full text-xs font-medium border border-slate-300 rounded-lg p-2.5 bg-white focus:ring-indigo-500 focus:border-indigo-500"
                          value={selectedProject?.id || ''}
                          onChange={e => setSelectedProject(projects.find(p => String(p.id) === e.target.value))}
                        >
                          <option value="">-- Select Project --</option>
                          {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                        </select>
                        {projectsError && (
                          <div className="mt-1.5 flex items-center justify-between text-[11px] text-red-600 bg-red-50 border border-red-200 rounded p-1.5">
                            <span>{projectsError}</span>
                            {tokenExpired && (
                              <button
                                onClick={handleRefreshBasecamp}
                                disabled={refreshingBc}
                                className="font-bold underline hover:text-red-800 ml-2"
                              >
                                {refreshingBc ? 'Refreshing...' : 'Refresh'}
                              </button>
                            )}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>

                {/* 5. MESSAGE / ARTICLE */}
                {selectedProject && (
                  <div className="space-y-3">
                    <div>
                      <div className="flex items-center justify-between gap-2 mb-1.5">
                        <label className="text-xs font-bold text-slate-700 uppercase tracking-wide flex items-center gap-1.5">
                          <span className="w-4 h-4 rounded-full bg-indigo-600 text-white flex items-center justify-center text-[10px]">5</span>
                          Message / Article
                        </label>
                        {!messagesLoading && !messagesError && messages.length > 0 && (
                          <span className={`text-[11px] font-semibold px-2.5 py-0.5 rounded-full border ${
                            selectedMessage
                              ? 'bg-indigo-50 text-indigo-700 border-indigo-200'
                              : 'bg-slate-100 text-slate-600 border-slate-200'
                          }`}>
                            {selectedMessage ? (
                              <>Selected: <strong className="font-bold text-indigo-900">{messages.findIndex(m => String(m.id) === String(selectedMessage.id)) + 1}</strong> of <strong className="font-bold text-indigo-900">{messages.length}</strong> articles</>
                            ) : (
                              <>0 of {messages.length} articles selected</>
                            )}
                          </span>
                        )}
                        {messagesLoading && (
                          <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-slate-100 text-slate-500 animate-pulse">
                            Loading articles…
                          </span>
                        )}
                      </div>

                      {messagesLoading ? (
                        <Spinner label="Loading messages..." />
                      ) : messagesError ? (
                        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">
                          <p className="font-semibold mb-0.5">Failed to load articles</p>
                          <p>{messagesError}</p>
                        </div>
                      ) : messages.length === 0 ? (
                        <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-500 italic text-center">
                          No articles found{selectedDate ? ` for ${selectedDate}` : ''} in {selectedProject.name}.
                        </div>
                      ) : (
                        <div className="space-y-2">
                          <select
                            className="w-full text-xs font-medium border border-slate-300 rounded-lg p-2.5 bg-white focus:ring-indigo-500 focus:border-indigo-500"
                            value={selectedMessage?.id || ''}
                            onChange={e => setSelectedMessage(messages.find(m => String(m.id) === e.target.value))}
                          >
                            <option value="">-- Select Article Message ({messages.length} available) --</option>
                            {messages.map((m, idx) => (
                              <option key={m.id} value={m.id}>
                                {idx + 1}. {(m.subject || '(No subject)').replace(/\s*\(📎\s*\d+\)/g, '').trim()}
                              </option>
                            ))}
                          </select>
                          {selectedMessage && (
                            <div className="flex items-center justify-between px-3 py-1.5 bg-indigo-50/70 border border-indigo-100 rounded-lg text-xs text-indigo-900">
                              <span className="flex items-center gap-1.5">
                                <span className="text-indigo-600 font-bold">✓</span>
                                <span>Selected: <strong>{messages.findIndex(m => String(m.id) === String(selectedMessage.id)) + 1} of {messages.length} articles</strong></span>
                              </span>
                              {selectedDate && (
                                <span className="text-[11px] text-indigo-700 bg-white px-2 py-0.5 rounded border border-indigo-200 font-medium">
                                  Date Filter: {selectedDate}
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Client Instructions */}
                    {selectedMessage && (
                      <div className="space-y-1.5">
                        <label className="block text-[11px] font-bold text-slate-500 uppercase tracking-wide">
                          Client Instructions
                        </label>
                        {detailLoading ? <Spinner label="Loading instructions..." /> : (
                          <div className="text-xs text-slate-700 bg-slate-50 rounded-lg p-3 max-h-36 overflow-y-auto border border-slate-200 prose prose-xs">
                            {msgDetail?.content ? (
                              <div dangerouslySetInnerHTML={{ __html: msgDetail.content }} />
                            ) : (
                              <span className="italic text-slate-400">No instructions found in message.</span>
                            )}
                          </div>
                        )}
                      </div>
                    )}

                    {/* DOCX Attachment */}
                    {msgDetail && (
                      <div className="space-y-1.5">
                        <label className="block text-[11px] font-bold text-slate-500 uppercase tracking-wide">
                          DOCX Attachment
                        </label>
                        {docxAttachments.length === 0 ? (
                          <p className="text-xs text-amber-700 bg-amber-50 p-2.5 rounded-lg border border-amber-200">
                            No Word document (.docx) attached to this message.
                          </p>
                        ) : (
                          <div className="space-y-1.5">
                            {docxAttachments.map(att => (
                              <button
                                key={att.id}
                                onClick={() => {
                                  setSelectedAttachment(att)
                                  resetProcessing()
                                }}
                                className={`w-full text-left px-3 py-2 rounded-lg border text-xs transition-all flex justify-between items-center ${
                                  selectedAttachment?.id === att.id
                                    ? 'border-indigo-500 bg-indigo-50/80 ring-1 ring-indigo-300 font-semibold text-indigo-900'
                                    : 'border-slate-200 hover:bg-slate-50 text-slate-700'
                                }`}
                              >
                                <span className="truncate flex-1 font-medium">📄 {att.filename}</span>
                                <span className="text-[11px] text-slate-400 ml-2">{formatBytes(att.byte_size)}</span>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Manual Image Upload — provider search removed */}
                    {selectedAttachment && (
                      <div className="bg-blue-50 border border-blue-200 rounded-xl p-3 text-xs text-blue-900 space-y-1">
                        <span className="font-bold block text-blue-800">📷 Manual Featured Image Upload</span>
                        <p className="text-[11px] text-blue-700">
                          After processing, you will be prompted to upload your own featured image before the WordPress draft is created.
                          No image is downloaded or selected automatically.
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}

            {/* 6. Process Button */}
            <div className="pt-2">
              <button
                onClick={handleProcess}
                disabled={!selectedSiteId || !connected || !selectedAttachment || processing}
                className="w-full py-3 bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 disabled:text-slate-500 text-white text-sm font-bold rounded-xl transition-all shadow-sm flex items-center justify-center gap-2"
              >
                {processing ? <><Spinner label="" /> Processing Workflow...</> : 'Process Workflow'}
              </button>
              {!selectedSiteId && (
                <p className="text-[11px] text-amber-700 text-center mt-1.5 font-medium">
                  Please select a WordPress site before processing.
                </p>
              )}
            </div>

          </div>
        </SectionCard>

        {/* ========================================================
            PANEL 2 & 3 — LEGACY PIPELINE VIEW (PRIMARY)
            ======================================================== */}
        <div className="lg:col-span-2 grid grid-cols-1 md:grid-cols-2 gap-6 min-h-0">
          <SectionCard title="2. Processing & QA Status">
          <div className="space-y-4">
            
            {/* Priority 4: Prominent WordPress Editor URL Inspection Banner */}
            {processResult?.status === 'completed' && (processResult.destination?.edit_url || processResult.destination?.url) && (
              <div className="bg-emerald-50 border-2 border-emerald-400 rounded-xl p-4 space-y-2.5 shadow-sm">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-emerald-900 font-bold text-sm">
                    <span className="text-lg">🎉</span>
                    <span>WordPress Draft Ready (#{processResult.destination.post_id || 'Created'})</span>
                  </span>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-200 text-emerald-900">
                    DRAFT ONLY
                  </span>
                </div>
                <p className="text-xs text-emerald-800">
                  Created on <strong>{processResult.destination.wordpress_site_name || 'Espial Test Site'}</strong>. Ready for inspection in the WordPress block editor.
                </p>
                <div className="flex flex-col sm:flex-row gap-2 pt-1">
                  <a
                    href={processResult.destination.edit_url || processResult.destination.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex-1 py-2.5 px-4 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-bold uppercase tracking-wider text-center transition-colors shadow-sm flex items-center justify-center gap-1.5"
                  >
                    <span>Open WordPress Draft Editor</span>
                    <span>↗</span>
                  </a>
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(processResult.destination.edit_url || processResult.destination.url)
                      setCopiedUrl(true)
                      setTimeout(() => setCopiedUrl(false), 2000)
                    }}
                    className="py-2.5 px-3 bg-white border border-emerald-300 hover:bg-emerald-50 text-emerald-800 rounded-lg text-xs font-semibold transition-colors flex items-center justify-center gap-1"
                  >
                    <span>{copiedUrl ? '✓ Copied' : '📋 Copy URL'}</span>
                  </button>
                </div>
                <p className="text-[10px] text-emerald-700 italic">
                  ℹ️ If browser pop-up blocking prevented automatic opening, click the button above to inspect your draft.
                </p>
              </div>
            )}

            {/* Priority 3: Manual Featured Image Approval Gate Card */}
            {pausedSession && (
              <div className="bg-amber-50/90 border-2 border-amber-400 rounded-xl p-4 space-y-3.5 text-xs text-slate-800 shadow-sm">
                <div className="flex items-center justify-between border-b border-amber-200 pb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xl">⏸</span>
                    <div>
                      <h3 className="font-bold text-amber-950 text-sm">Featured Image Approval Gate</h3>
                      <p className="text-[11px] text-amber-800">
                        Automation paused. Review candidates or upload an image before draft creation.
                      </p>
                    </div>
                  </div>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-amber-200 text-amber-900 uppercase">
                    Approval Gate
                  </span>
                </div>

                {/* Candidate Gallery */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="font-bold text-slate-700 uppercase">Image Candidates</span>
                    <span className="text-slate-500 text-[10px]">1000×667 px banner / ≤700px DOCX</span>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 max-h-48 overflow-y-auto p-1 bg-white border border-amber-200 rounded-lg">
                    {pausedSession.image_candidates?.map((cand, idx) => {
                      const isSelected = selectedCandidate?.filename === cand.filename || (!selectedCandidate && idx === 0)
                      return (
                        <div
                          key={idx}
                          onClick={() => setSelectedCandidate(cand)}
                          className={`cursor-pointer rounded-lg border p-1.5 transition-all text-[10px] flex flex-col justify-between ${
                            isSelected
                              ? 'border-indigo-600 ring-2 ring-indigo-400 bg-indigo-50/60 shadow-xs'
                              : 'border-slate-200 hover:border-slate-300 bg-slate-50/50'
                          }`}
                        >
                          <img
                            src={cand.thumbnail_url || cand.preview_url}
                            alt={cand.label}
                            className="w-full h-16 object-cover rounded bg-slate-100"
                          />
                          <div className="mt-1">
                            <span className="font-semibold block truncate text-slate-800">{cand.label}</span>
                            <span className="text-[9px] text-slate-500 block truncate">{cand.credit_text || cand.provider}</span>
                            <span className="text-[9px] text-indigo-600 font-mono block">{cand.dimensions}</span>
                          </div>
                          {isSelected && (
                            <div className="mt-1 text-center bg-indigo-600 text-white font-bold text-[9px] py-0.5 rounded">
                              ✓ Selected
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>

                {/* Custom Search or Upload */}
                <div className="bg-white border border-amber-200 rounded-lg p-2.5 space-y-2 text-[11px]">
                  <div className="flex items-center justify-between font-semibold text-slate-700">
                    <span>Actions & Controls</span>
                  </div>
                  <div className="flex gap-2">
                    <label className="flex-1 cursor-pointer py-1.5 px-2 bg-slate-100 hover:bg-slate-200 border border-slate-300 rounded text-center text-slate-700 font-medium">
                      📁 Choose Image File…
                      <input
                        type="file"
                        accept="image/*"
                        className="hidden"
                        onChange={handleImageFileUpload}
                      />
                    </label>
                    <button
                      onClick={() => setShowLinkReviewModal(true)}
                      className="py-1.5 px-3 bg-indigo-50 border border-indigo-200 text-indigo-700 hover:bg-indigo-100 rounded font-semibold flex items-center gap-1"
                    >
                      <span>🔗 Review Content & Links</span>
                    </button>
                  </div>
                  {selectedCandidate && (
                    <div className="p-2 bg-slate-50 rounded border border-slate-200 text-[10px] space-y-0.5">
                      <div><strong className="text-slate-700">Alt Text (Strict Keyphrase):</strong> {pausedSession.ai_result?.focus_keyphrase || '—'}</div>
                      <div><strong className="text-slate-700">Source Credit:</strong> {selectedCandidate.credit_text || selectedCandidate.provider || 'Selected Image'}</div>
                    </div>
                  )}
                </div>

                {/* Approve and Continue Button */}
                <div className="pt-1">
                  <button
                    onClick={handleResumePipeline}
                    disabled={processing || resuming}
                    className="w-full py-3 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-300 text-white font-bold rounded-xl shadow-sm text-xs uppercase tracking-wider flex items-center justify-center gap-2 transition-all"
                  >
                    {resuming ? <><Spinner label="" /> Creating Draft on Test Site…</> : '✓ Approve Image & Continue to Draft Creation (Next) →'}
                  </button>
                </div>
              </div>
            )}

            {/* Priority 2: Real Backend Processing Stages Log */}
            {(processingStages.length > 0 || processing || resuming) && (
              <div className="bg-slate-900 text-slate-100 rounded-xl p-3 text-xs space-y-1.5 font-mono shadow-inner border border-slate-800">
                <div className="flex justify-between items-center text-slate-400 text-[10px] uppercase tracking-wider font-bold border-b border-slate-800 pb-1">
                  <span>Backend Execution Progress</span>
                  <span>{processing || resuming ? '⚡ Running…' : '✓ Completed'}</span>
                </div>
                <div className="space-y-1 max-h-44 overflow-y-auto pr-1 text-[11px]">
                  {processingStages.map((stg, idx) => (
                    <div key={idx} className="flex items-start gap-1.5 leading-relaxed">
                      <span className="text-emerald-400 select-none">›</span>
                      <span className={stg.startsWith('Error') ? 'text-red-400 font-bold' : (stg.includes('⏸') ? 'text-amber-300 font-bold' : 'text-slate-200')}>
                        {stg}
                      </span>
                    </div>
                  ))}
                  {(processing || resuming) && (
                    <div className="flex items-center gap-2 text-indigo-400 animate-pulse pt-1">
                      <span className="w-2 h-2 rounded-full bg-indigo-400 animate-ping" />
                      <span className="text-[10px] font-sans">Processing current pipeline stage…</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Active Article Context */}
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs flex items-center justify-between">
              <div>
                <p className="text-[10px] font-bold text-slate-400 uppercase">Selected Attachment</p>
                <p className="font-semibold text-indigo-700 truncate max-w-[240px]">
                  {selectedAttachment ? selectedAttachment.filename : 'None selected'}
                </p>
              </div>
              {selectedAttachment && (
                <span className="text-[11px] text-slate-400">{formatBytes(selectedAttachment.byte_size)}</span>
              )}
            </div>

            {/* Pipeline Stage Badges */}
            <div className="space-y-2 bg-slate-50/75 border border-slate-200 rounded-xl p-3">
              {pipelineSteps.map(step => {
                const status = getStepStatus(step.key)
                return (
                  <div key={step.key} className="flex justify-between items-center py-1 border-b border-slate-100 last:border-0">
                    <span className={`text-xs ${status === 'completed' ? 'text-slate-800 font-semibold' : 'text-slate-500'}`}>
                      {step.label}
                    </span>
                    <PipelineBadge status={status} />
                  </div>
                )
              })}
            </div>

            <ErrorMsg msg={processError} />

            {/* Duplicate Notice */}
            {(processResult?.status === 'duplicate' || processResult?.duplicate_result?.status === 'DUPLICATE FOUND') && (
              <div className="bg-amber-50 border-2 border-amber-300 rounded-xl p-4 text-xs text-amber-900 space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-lg">⚠️</span>
                  <div>
                    <span className="font-bold block text-sm">Duplicate Found</span>
                    <span>This article already exists on destination WordPress site. Pipeline halted.</span>
                  </div>
                </div>
                {processResult.existing_post?.title && (
                  <div className="bg-white p-2.5 rounded-lg border border-amber-200 mt-2 space-y-1.5">
                    <p className="font-semibold text-slate-800 truncate">{processResult.existing_post.title}</p>
                    {processResult.existing_post.url && (
                      <a
                        href={processResult.existing_post.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs font-bold text-indigo-600 hover:underline"
                      >
                        <span>Open Existing Article</span>
                        <span>↗</span>
                      </a>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Detailed 28-Point QA Checklist */}
            {processResult?.qa_checklist && (
              <div className="space-y-3 pt-2">
                <div className="flex items-center justify-between pb-1 border-b border-slate-200">
                  <span className="text-xs font-bold uppercase tracking-wider text-slate-800">
                    28-Point HBM QA Checklist
                  </span>
                  {(() => {
                    const hasFail = Object.values(processResult.qa_checklist || {}).some(sec =>
                      typeof sec === 'object' && Object.values(sec || {}).some(item => (typeof item === 'object' ? item.status : item) === 'FAIL')
                    )
                    const isPassed = !hasFail && (processResult.qa_result?.status !== 'FAILED')
                    return (
                      <span className={`text-xs font-bold px-2.5 py-0.5 rounded-full border ${
                        isPassed
                          ? 'bg-emerald-100 text-emerald-800 border-emerald-300'
                          : 'bg-red-100 text-red-800 border-red-300'
                      }`}>
                        {isPassed ? 'PASSED' : 'FAILED'}
                      </span>
                    )
                  })()}
                </div>

                <div className="space-y-3 max-h-80 overflow-y-auto pr-1">
                  {Object.entries(processResult.qa_checklist).map(([sectionKey, items]) => (
                    <div key={sectionKey} className="bg-slate-50 border border-slate-200 rounded-lg p-2.5 space-y-1.5">
                      <p className="text-[11px] font-bold uppercase tracking-wider text-slate-600 border-b border-slate-200 pb-1">
                        {sectionKey.replace(/_/g, ' ')}
                      </p>
                      <div className="space-y-1">
                        {typeof items === 'object' && items !== null && Object.entries(items).map(([k, val]) => {
                          const status = typeof val === 'object' ? val.status : (val ? 'PASS' : 'FAIL')
                          const label = typeof val === 'object' ? val.label : k.replace(/_/g, ' ')
                          const tooltip = typeof val === 'object' && val.detail ? `${label}: ${val.detail}${val.location ? ` [${val.location}]` : ''}` : label
                          return (
                            <div key={k} className="flex items-center justify-between text-xs py-0.5" title={tooltip}>
                              <span className="text-slate-600 truncate mr-2">{label}</span>
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
        </SectionCard>

        {/* ========================================================
            PANEL 3 — DESTINATION (WORDPRESS DRAFT & SEO)
            ======================================================== */}
        <SectionCard 
          title="3. Destination Details"
          actions={
            <span className="text-[11px] bg-indigo-50 text-indigo-700 font-bold px-2 py-0.5 rounded border border-indigo-200">
              DRAFT ONLY
            </span>
          }
        >
          <div className="space-y-4">
            
            {/* Active Destination Site Summary */}
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5 text-xs space-y-1">
              <span className="text-[10px] font-bold text-slate-400 uppercase block">Selected WordPress Site</span>
              <p className="font-bold text-slate-800 text-sm">
                {activeSelectedSite ? activeSelectedSite.name : 'None selected'}
              </p>
              <p className="text-slate-500 text-[11px]">
                {activeSelectedSite ? activeSelectedSite.url : '—'}
              </p>
              <p className="text-[10px] text-amber-700 font-medium pt-1">
                ⚠️ All workflow posts remain <span className="font-bold">DRAFT ONLY</span>. Never automatically published.
              </p>
            </div>

            {/* Draft Details */}
            {processResult?.status === 'completed' ? (
              <div className="space-y-3.5 text-xs">
                
                {/* Proposed Title */}
                <div>
                  <span className="text-[10px] font-bold text-slate-400 uppercase block">Draft Title</span>
                  <span className="font-bold text-slate-800 text-sm block mt-0.5">
                    {processResult.destination?.title || processResult.ai_result?.title || 'Untitled'}
                  </span>
                </div>

                {/* Focus Keyphrase — PROMINENT */}
                <div className="bg-indigo-50/70 border border-indigo-200 rounded-xl p-3 space-y-1">
                  <div className="flex justify-between items-center">
                    <span className="text-[10px] font-bold text-indigo-900 uppercase">Focus Keyphrase (SEO)</span>
                    <span className="text-[10px] font-semibold text-indigo-700 bg-indigo-100 px-1.5 py-0.2 rounded">
                      ≤ 4 words verified
                    </span>
                  </div>
                  <span className="font-mono font-bold text-indigo-800 text-sm block">
                    {processResult.destination?.focus_keyphrase || processResult.ai_result?.focus_keyphrase || '—'}
                  </span>
                </div>

                {/* Categories */}
                <div className="grid grid-cols-2 gap-2 pt-1 border-t border-slate-100">
                  <div>
                    <span className="text-[10px] font-bold text-slate-400 uppercase block">Primary Category</span>
                    <span className="font-bold text-indigo-700 bg-indigo-50 border border-indigo-200 px-2 py-0.5 rounded text-xs inline-block mt-1">
                      {processResult.destination?.primary_category || 'Uncategorized'}
                    </span>
                  </div>
                  <div>
                    <span className="text-[10px] font-bold text-slate-400 uppercase block">All Categories</span>
                    <span className="text-slate-700 font-medium block mt-1">
                      {(processResult.destination?.all_categories || ['Uncategorized']).join(', ')}
                    </span>
                  </div>
                </div>

                {/* Author & Draft Status */}
                <div className="grid grid-cols-2 gap-2 pt-1 border-t border-slate-100">
                  <div>
                    <span className="text-[10px] font-bold text-slate-400 uppercase block">Assigned Author</span>
                    <span className="font-semibold text-slate-800 block mt-1">
                      👤 {processResult.destination?.author || 'Home Office Editor'}
                    </span>
                  </div>
                  <div>
                    <span className="text-[10px] font-bold text-slate-400 uppercase block">Post Status</span>
                    <span className="font-bold uppercase text-emerald-800 bg-emerald-100 px-2 py-0.5 rounded text-[11px] inline-block mt-1">
                      {processResult.destination?.status || 'draft'}
                    </span>
                  </div>
                </div>

                {/* WordPress IDs */}
                <div className="grid grid-cols-2 gap-2 pt-1 border-t border-slate-100">
                  <div>
                    <span className="text-[10px] font-bold text-slate-400 uppercase block">WordPress Post ID</span>
                    <span className="font-mono text-slate-800 font-semibold block mt-1">
                      #{processResult.destination?.post_id || '—'}
                    </span>
                  </div>
                  <div>
                    <span className="text-[10px] font-bold text-slate-400 uppercase block">Featured Media ID</span>
                    <span className="font-mono text-slate-800 font-semibold block mt-1">
                      🖼️ #{processResult.destination?.featured_media_id || '—'}
                    </span>
                  </div>
                </div>

                {/* Image Details */}
                <div className="pt-1 border-t border-slate-100 space-y-1">
                  <span className="text-[10px] font-bold text-slate-400 uppercase block">Image Dimensions & Source</span>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-slate-700 truncate">
                      {processResult.destination?.image_source || 'DOCX / Pexels'}
                    </span>
                    <span className="text-emerald-700 font-semibold bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200 shrink-0 text-[11px]">
                      {processResult.destination?.image_dimensions || '1000 × 667 px'}
                    </span>
                  </div>
                  {processResult.destination?.image_source_url && (
                    <a
                      href={processResult.destination.image_source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs text-indigo-600 hover:underline block truncate"
                    >
                      Source Link: {processResult.destination.image_source_url} ↗
                    </a>
                  )}
                </div>

                {/* Open WordPress Draft Button */}
                <div className="pt-3 border-t border-slate-100 space-y-2">
                  {(processResult.destination?.edit_url || processResult.destination?.url) ? (
                    <>
                      <a
                        href={processResult.destination.edit_url || processResult.destination.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center justify-center w-full px-4 py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-bold uppercase tracking-wider transition-colors gap-1.5 shadow-sm"
                      >
                        <span>Open WordPress Draft Editor #{processResult.destination?.post_id}</span>
                        <span>↗</span>
                      </a>
                      <button
                        type="button"
                        onClick={() => {
                          navigator.clipboard.writeText(processResult.destination.edit_url || processResult.destination.url)
                          setCopiedUrl(true)
                          setTimeout(() => setCopiedUrl(false), 2000)
                        }}
                        className="w-full py-2 bg-slate-50 border border-slate-300 hover:bg-slate-100 text-slate-700 rounded-lg text-xs font-semibold transition-colors flex items-center justify-center gap-1"
                      >
                        <span>{copiedUrl ? '✓ URL Copied to Clipboard' : '📋 Copy Draft Editor URL'}</span>
                      </button>
                    </>
                  ) : <span>—</span>}
                </div>

              </div>
            ) : (
              <div className="text-center py-10 text-slate-400 text-xs italic">
                Select a WordPress site, project, and article, then click "Process Workflow".
              </div>
            )}

          </div>
        </SectionCard>
        </div>

      </div>
        )
      ) : (
        /* QA Only Layout (Phase 2) */
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 flex-1 min-h-0">
          
          {/* LEFT COLUMN: Setup & Existing Drafts Selector (5 cols) */}
          <div className="lg:col-span-5 h-full min-h-0 flex flex-col">
            <SectionCard
              title="QA Audit Setup & Existing Draft Selection"
              actions={
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-emerald-100 text-emerald-800 text-[11px] font-bold border border-emerald-200">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-600 animate-pulse" />
                  Read-Only Mode
                </span>
              }
            >
              <div className="space-y-4">
                
                {/* 1. Destination WordPress Site */}
                <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5 space-y-2.5">
                  <div className="flex justify-between items-center">
                    <label className="text-xs font-bold text-slate-700 uppercase tracking-wide flex items-center gap-1.5">
                      <span className="w-4 h-4 rounded-full bg-emerald-600 text-white flex items-center justify-center text-[10px]">1</span>
                      Destination WordPress Site
                    </label>
                    <button
                      onClick={() => setShowSiteModal(true)}
                      className="text-[11px] font-semibold text-emerald-700 hover:text-emerald-900 hover:underline"
                    >
                      + Add / Manage
                    </button>
                  </div>

                  {sitesLoading ? <Spinner label="Loading WordPress sites..." /> : (
                    <div className="space-y-2">
                      <select
                        className="w-full text-xs font-medium border border-slate-300 rounded-lg p-2.5 bg-white shadow-xs focus:ring-emerald-500 focus:border-emerald-500"
                        value={selectedSiteId}
                        onChange={e => {
                          setSelectedSiteId(e.target.value)
                          setSiteTestResult(null)
                        }}
                      >
                        <option value="">-- Select Destination WordPress Site --</option>
                        {sites.map(site => (
                          <option key={site.id} value={site.id}>
                            {site.name} ({site.url}) {site.is_default ? '★ Default' : ''}
                          </option>
                        ))}
                      </select>

                      {activeSelectedSite && (
                        <div className="flex items-center justify-between text-[11px] text-slate-500 pt-1">
                          <span className="truncate">Connected as: <strong className="text-slate-700">{activeSelectedSite.username}</strong></span>
                          <button
                            onClick={handleTestSelectedSite}
                            disabled={siteTesting}
                            className="text-xs text-emerald-700 hover:underline font-semibold"
                          >
                            {siteTesting ? 'Testing...' : 'Test Auth ⚡'}
                          </button>
                        </div>
                      )}

                      {siteTestResult && (
                        <div className={`p-2 rounded text-[11px] ${siteTestResult.success ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-red-50 text-red-700 border border-red-200'}`}>
                          {siteTestResult.success ? `✓ Authentication verified (${siteTestResult.name})` : `✗ ${siteTestResult.error}`}
                        </div>
                      )}
                    </div>
                  )}

                  <div className="flex items-center gap-1.5 text-[11px] text-emerald-800 bg-emerald-50/70 border border-emerald-100 rounded-md px-2.5 py-1.5 font-medium">
                    <span>🛡️</span>
                    <span>Zero-write guarantee: Only read-only GET requests are sent to this site.</span>
                  </div>
                </div>

                {/* 2. Existing WordPress Drafts Loader */}
                <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5 space-y-2.5">
                  <div className="flex justify-between items-center">
                    <label className="text-xs font-bold text-slate-700 uppercase tracking-wide flex items-center gap-1.5">
                      <span className="w-4 h-4 rounded-full bg-emerald-600 text-white flex items-center justify-center text-[10px]">2</span>
                      Existing WordPress Draft
                    </label>
                    <button
                      onClick={() => fetchQaDrafts(selectedSiteId)}
                      disabled={qaDraftsLoading || !selectedSiteId}
                      className="text-[11px] font-semibold text-emerald-700 hover:text-emerald-900 hover:underline flex items-center gap-1 disabled:opacity-50"
                    >
                      <span>↻</span> Refresh Drafts
                    </button>
                  </div>

                  {!selectedSiteId ? (
                    <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
                      Please select a WordPress site above to view existing drafts.
                    </div>
                  ) : qaDraftsLoading ? (
                    <Spinner label="Loading drafts from WordPress (read-only GET)..." />
                  ) : qaDraftsError ? (
                    <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700 space-y-1">
                      <p className="font-bold">Failed to load drafts</p>
                      <p>{qaDraftsError}</p>
                      <button
                        onClick={() => fetchQaDrafts(selectedSiteId)}
                        className="text-xs text-red-800 underline font-semibold mt-1"
                      >
                        Retry Loading Drafts
                      </button>
                    </div>
                  ) : qaDrafts.length === 0 ? (
                    <div className="p-3 bg-slate-100 border border-slate-200 rounded-lg text-xs text-slate-600 text-center italic">
                      No draft posts found on {activeSelectedSite?.name || 'selected site'}.
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between text-xs text-slate-600">
                        <span>Found <strong className="text-slate-800">{qaDrafts.length}</strong> existing drafts:</span>
                        {selectedQaDraft && (
                          <span className="text-[11px] font-semibold text-emerald-800 bg-emerald-100/80 px-2 py-0.5 rounded border border-emerald-200">
                            Post #{selectedQaDraft.id}
                          </span>
                        )}
                      </div>

                      <select
                        className="w-full text-xs font-medium border border-slate-300 rounded-lg p-2.5 bg-white shadow-xs focus:ring-emerald-500 focus:border-emerald-500"
                        value={selectedQaDraft?.id || ''}
                        onChange={e => {
                          const found = qaDrafts.find(d => String(d.id) === e.target.value)
                          setSelectedQaDraft(found || null)
                          setQaAuditResult(null)
                          setQaAuditError(null)
                        }}
                      >
                        {qaDrafts.map((d, idx) => (
                          <option key={d.id} value={d.id}>
                            {idx + 1}. [#{d.id}] {d.title} ({formatDate(d.modified || d.date)})
                          </option>
                        ))}
                      </select>

                      {selectedQaDraft && (
                        <div className="p-3 bg-white border border-slate-200 rounded-lg space-y-2 shadow-2xs">
                          <div className="flex justify-between items-start gap-2">
                            <div>
                              <h4 className="text-xs font-bold text-slate-800 leading-snug">{selectedQaDraft.title}</h4>
                              <p className="text-[11px] text-slate-500 mt-0.5">
                                Post ID: <strong className="text-slate-700">#{selectedQaDraft.id}</strong> • Slug: <span className="font-mono text-slate-600">{selectedQaDraft.slug || '—'}</span>
                              </p>
                            </div>
                            <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-200 shrink-0">
                              {selectedQaDraft.status}
                            </span>
                          </div>

                          <div className="flex items-center justify-between pt-1 border-t border-slate-100 text-[11px]">
                            <span className="text-slate-500">Modified: {formatDate(selectedQaDraft.modified || selectedQaDraft.date)}</span>
                            {activeSelectedSite && (
                              <a
                                href={`${activeSelectedSite.url.replace(/\/$/, '')}/wp-admin/post.php?post=${selectedQaDraft.id}&action=edit`}
                                target="_blank"
                                rel="noreferrer"
                                className="text-emerald-700 hover:text-emerald-900 font-semibold hover:underline flex items-center gap-1"
                              >
                                View in WP Admin ↗
                              </a>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* 3. Optional DOCX Attachment or Link for Source Comparison */}
                <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5 space-y-2.5">
                  <div>
                    <label className="text-xs font-bold text-slate-700 uppercase tracking-wide flex items-center gap-1.5">
                      <span className="w-4 h-4 rounded-full bg-emerald-600 text-white flex items-center justify-center text-[10px]">3</span>
                      Source DOCX Comparison (Optional)
                    </label>
                    <p className="text-[11px] text-slate-500 mt-0.5">
                      Attach or specify an original Word DOCX document to compare against the WordPress draft.
                    </p>
                  </div>

                  <div className="grid grid-cols-2 gap-1.5 p-1 bg-slate-200/60 rounded-lg text-xs font-medium">
                    <button
                      type="button"
                      onClick={() => setQaDocxSourceType('none')}
                      className={`py-1.5 px-2 rounded-md text-center transition-all ${
                        qaDocxSourceType === 'none'
                          ? 'bg-white text-slate-800 shadow-2xs font-bold'
                          : 'text-slate-600 hover:text-slate-900'
                      }`}
                    >
                      None (Standalone)
                    </button>
                    <button
                      type="button"
                      onClick={() => setQaDocxSourceType('basecamp')}
                      className={`py-1.5 px-2 rounded-md text-center transition-all ${
                        qaDocxSourceType === 'basecamp'
                          ? 'bg-white text-slate-800 shadow-2xs font-bold'
                          : 'text-slate-600 hover:text-slate-900'
                      }`}
                    >
                      From Basecamp
                    </button>
                  </div>

                  {qaDocxSourceType === 'none' && (
                    <div className="p-2.5 bg-blue-50/80 border border-blue-200 rounded-lg text-[11px] text-blue-800 leading-relaxed">
                      <strong>ℹ️ Standalone Draft Audit:</strong> No source DOCX attached. The upcoming Phase 2.1 QA audit will evaluate WordPress draft layout, dead links, headings, featured image formatting, categories, and Yoast SEO. Document parity checks will report honest <strong>NOT APPLICABLE</strong> results.
                    </div>
                  )}

                  {qaDocxSourceType === 'basecamp' && (
                    <div className="space-y-2 pt-1">
                      {!connected ? (
                        <div className="p-2.5 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
                          Basecamp is not connected. Please connect Basecamp or choose None (Standalone).
                        </div>
                      ) : (
                        <div className="space-y-2">
                          {selectedAttachment ? (
                            <div className="p-2.5 bg-white border border-emerald-200 rounded-lg text-xs space-y-1">
                              <div className="flex justify-between items-center">
                                <div>
                                  <span className="font-bold text-slate-700 block truncate">{selectedAttachment.filename}</span>
                                  <span className="text-[11px] text-slate-400">From: {selectedMessage?.subject || 'Basecamp message'}</span>
                                </div>
                                <span className="text-emerald-700 font-bold text-xs">✓ Attached</span>
                              </div>
                              {selectedQaDraft && selectedMessage && (
                                <p className="text-[10px] text-slate-500 pt-0.5 border-t border-slate-100">
                                  Auditing against: <strong className="text-slate-700">{selectedQaDraft.title}</strong>
                                </p>
                              )}
                            </div>
                          ) : (
                            <div className="p-2.5 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
                              No attachment selected in Basecamp setup. (Select an article message below or in Create Draft mode to reuse its DOCX).
                            </div>
                          )}

                          {messages.length > 0 && (
                            <div className="pt-1">
                              <label className="text-[10px] text-slate-500 font-semibold block mb-1">
                                Basecamp Article Document ({messages.length} available):
                              </label>
                              <select
                                className="w-full text-xs border border-slate-300 rounded-lg p-1.5 bg-white"
                                value={selectedMessage?.id || ''}
                                onChange={e => {
                                  const found = messages.find(m => String(m.id) === e.target.value)
                                  setSelectedMessage(found || null)
                                }}
                              >
                                <option value="">-- Choose Basecamp article for comparison --</option>
                                {messages.map(m => (
                                  <option key={m.id} value={m.id}>
                                    {m.subject}
                                  </option>
                                ))}
                              </select>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>

              </div>
            </SectionCard>
          </div>

          {/* RIGHT COLUMN: Draft Audit Overview & Phase 2.1 Readiness (7 cols) */}
          <div className="lg:col-span-7 h-full min-h-0 flex flex-col">
            <SectionCard
              title="Target Draft Audit Overview & QA Readiness"
              actions={
                selectedQaDraft ? (
                  <span className="text-xs font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2.5 py-0.5 rounded-full">
                    Target Ready
                  </span>
                ) : (
                  <span className="text-xs font-semibold text-slate-400 bg-slate-100 px-2.5 py-0.5 rounded-full">
                    No Draft Selected
                  </span>
                )
              }
            >
              <div className="space-y-4">
                
                {/* Target Draft Banner */}
                {selectedQaDraft ? (
                  <div className="p-4 bg-gradient-to-r from-emerald-50 to-teal-50 border border-emerald-200 rounded-xl space-y-2">
                    <div className="flex justify-between items-start gap-3">
                      <div>
                        <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-800 bg-emerald-100 px-2 py-0.5 rounded">
                          Target WordPress Draft
                        </span>
                        <h3 className="text-base font-bold text-slate-900 mt-1">{selectedQaDraft.title}</h3>
                      </div>
                      <span className="text-xs font-mono font-bold text-emerald-900 bg-white/80 px-2.5 py-1 rounded-md border border-emerald-200 shadow-2xs shrink-0">
                        Post #{selectedQaDraft.id}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 border-t border-emerald-200/60 text-xs text-slate-600">
                      <div>
                        <span className="text-[10px] text-slate-400 block uppercase">Destination Site</span>
                        <strong className="text-slate-800 truncate block">{activeSelectedSite?.name || 'WordPress'}</strong>
                      </div>
                      <div>
                        <span className="text-[10px] text-slate-400 block uppercase">Draft Status</span>
                        <strong className="text-slate-800 capitalize">{selectedQaDraft.status}</strong>
                      </div>
                      <div>
                        <span className="text-[10px] text-slate-400 block uppercase">Last Modified</span>
                        <span className="text-slate-700">{formatDate(selectedQaDraft.modified || selectedQaDraft.date)}</span>
                      </div>
                      <div>
                        <span className="text-[10px] text-slate-400 block uppercase">Source DOCX</span>
                        <span className="text-slate-700 truncate block font-medium" title={qaDocxSourceType === 'none' ? 'None (Standalone)' : (selectedAttachment?.filename || 'Basecamp (None selected)')}>
                          {qaDocxSourceType === 'none'
                            ? 'None (Standalone)'
                            : selectedAttachment?.filename
                              ? selectedAttachment.filename
                              : 'Basecamp (None selected)'}
                        </span>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="p-8 text-center bg-slate-50 border border-dashed border-slate-300 rounded-xl space-y-2">
                    <p className="text-sm font-semibold text-slate-700">No WordPress Draft Selected</p>
                    <p className="text-xs text-slate-500 max-w-md mx-auto">
                      Select a destination WordPress site on the left to load existing drafts, then choose an article draft to audit.
                    </p>
                  </div>
                )}

                {/* Safety & Protocol Guarantees */}
                <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-3">
                  <h4 className="text-xs font-bold text-slate-700 uppercase tracking-wide flex items-center gap-1.5">
                    <span className="text-emerald-600 font-bold">✓</span>
                    Strictly Read-Only Safety Protocol
                  </h4>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 text-xs text-slate-600">
                    <div className="flex items-start gap-2 bg-white p-2.5 rounded-lg border border-slate-200">
                      <span className="text-emerald-600 font-bold">✓</span>
                      <span><strong>Zero WordPress Writes:</strong> GET requests only. Never executes POST, PUT, PATCH, or DELETE.</span>
                    </div>
                    <div className="flex items-start gap-2 bg-white p-2.5 rounded-lg border border-slate-200">
                      <span className="text-emerald-600 font-bold">✓</span>
                      <span><strong>Zero Metadata Mutation:</strong> Never modifies existing categories, tags, or author assignments on WordPress.</span>
                    </div>
                    <div className="flex items-start gap-2 bg-white p-2.5 rounded-lg border border-slate-200">
                      <span className="text-emerald-600 font-bold">✓</span>
                      <span><strong>Honest N/A Handling:</strong> Standalone draft audits correctly mark document parity as NOT APPLICABLE.</span>
                    </div>
                    <div className="flex items-start gap-2 bg-white p-2.5 rounded-lg border border-slate-200">
                      <span className="text-emerald-600 font-bold">✓</span>
                      <span><strong>Discrepancy Reporting:</strong> Reports category and tag differences for Richard instead of auto-altering.</span>
                    </div>
                  </div>
                </div>

                {/* Phase 2.1 Authoritative 10-Category QA Audit Engine Panel */}
                <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-4">
                  
                  {/* Top Bar: Action & Mode Status */}
                  <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-slate-200">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-bold text-slate-800">Authoritative 10-Category QA Engine</span>
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-200">
                          Phase 2.1 Active
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-500 mt-0.5">
                        Strictly read-only audit against WordPress draft. Zero write requests guaranteed.
                      </p>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={handleRunQaAudit}
                        disabled={qaAuditLoading || !selectedQaDraft}
                        className="px-4 py-2 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-700 text-white font-bold rounded-lg text-xs shadow-sm hover:shadow transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                      >
                        {qaAuditLoading ? (
                          <>
                            <svg className="animate-spin h-3.5 w-3.5 text-white" viewBox="0 0 24 24" fill="none">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                            </svg>
                            <span>Auditing Draft #{selectedQaDraft?.id}...</span>
                          </>
                        ) : (
                          <>
                            <span>🛡️</span>
                            <span>{qaAuditResult ? 'Re-run 10-Category Audit' : 'Run 10-Category QA Audit'}</span>
                          </>
                        )}
                      </button>
                    </div>
                  </div>

                  {/* Error State */}
                  {qaAuditError && (
                    <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700 space-y-1">
                      <p className="font-bold flex items-center gap-1.5">
                        <span>⚠️</span> QA Audit Execution Error
                      </p>
                      <p>{qaAuditError}</p>
                      <button
                        onClick={handleRunQaAudit}
                        className="text-xs text-red-800 underline font-semibold mt-1 block"
                      >
                        Retry Audit
                      </button>
                    </div>
                  )}

                  {/* Loading State */}
                  {qaAuditLoading && (
                    <div className="p-8 text-center bg-white rounded-xl border border-slate-200 space-y-3">
                      <Spinner label={`Inspecting WordPress Draft #${selectedQaDraft?.id} across all 10 categories...`} />
                      <div className="text-[11px] text-slate-400 max-w-md mx-auto space-y-1">
                        <p>✓ Testing live link HTTP status codes & anchor word counts (3-5 internal, 3-4 authority)</p>
                        <p>✓ Verifying H2-H4 heading hierarchy, Title Case & image source credits</p>
                        <p>✓ Evaluating prohibited authors, duplicate titles, and Yoast SEO requirements</p>
                        <p className="font-semibold text-emerald-700">Strictly Read-Only: Zero WordPress write operations executed.</p>
                      </div>
                    </div>
                  )}

                  {/* When Not Yet Run */}
                  {!qaAuditLoading && !qaAuditResult && (
                    <div className="space-y-3">
                      <p className="text-[11px] text-slate-500">
                        Click "Run 10-Category QA Audit" above to evaluate WordPress draft #{selectedQaDraft?.id || '—'} against the 10 authoritative checklist categories:
                      </p>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px] text-slate-700">
                        {Object.entries(QA_CATEGORY_CONFIG).map(([key, cfg]) => (
                          <div key={key} className="p-2.5 bg-white rounded-lg border border-slate-200 flex items-start gap-2 shadow-2xs">
                            <span className="text-base">{cfg.icon}</span>
                            <div className="min-w-0">
                              <span className="font-bold text-slate-800 block truncate">{cfg.label}</span>
                              <span className="text-[10px] text-slate-400 block line-clamp-1">{cfg.description}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Audit Results View */}
                  {!qaAuditLoading && qaAuditResult && (
                    <div className="space-y-4">
                      
                      {/* 1. Verdict Banner */}
                      <div className={`p-4 rounded-xl border transition-all ${
                        qaAuditResult.verdict === 'READY'
                          ? 'bg-emerald-50/90 border-emerald-300 text-emerald-950'
                          : qaAuditResult.verdict === 'READY AFTER FIXES'
                          ? 'bg-amber-50/90 border-amber-300 text-amber-950'
                          : 'bg-rose-50/90 border-rose-300 text-rose-950'
                      }`}>
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="space-y-1">
                            <div className="flex items-center gap-2">
                              <span className="text-xl">
                                {qaAuditResult.verdict === 'READY' ? '✅' : qaAuditResult.verdict === 'READY AFTER FIXES' ? '⚠️' : '⛔'}
                              </span>
                              <h3 className="text-base font-black tracking-wide uppercase">
                                VERDICT: {qaAuditResult.verdict}
                              </h3>
                            </div>
                            <p className="text-xs font-medium leading-relaxed">
                              {qaAuditResult.verdict_summary}
                            </p>
                          </div>

                          <div className="flex flex-col items-end gap-1 shrink-0">
                            <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-white/80 border border-slate-200 text-slate-700">
                              Zero WordPress Writes Guaranteed
                            </span>
                            <span className="text-[10px] text-slate-500">
                              Audit target: Post #{qaAuditResult.post_id} on {qaAuditResult.site_name}
                            </span>
                          </div>
                        </div>

                        {/* Responsible Parties Summary */}
                        <div className="mt-3 pt-3 border-t border-slate-200/60 flex flex-wrap items-center gap-2 text-xs">
                          <span className="text-[11px] font-bold text-slate-600">Action Assignments:</span>
                          {qaAuditResult.counts.fail === 0 && qaAuditResult.counts.warning === 0 ? (
                            <span className="text-[11px] font-semibold text-emerald-700 bg-white/70 px-2.5 py-0.5 rounded-full border border-emerald-200">
                              ✓ No actions required
                            </span>
                          ) : (
                            <>
                              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-blue-100 text-blue-800 text-[11px] font-bold border border-blue-200">
                                <span>🔧</span> Espial Team Fixes
                              </span>
                              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-purple-100 text-purple-800 text-[11px] font-bold border border-purple-200">
                                <span>👤</span> Report for Richard Henderson
                              </span>
                            </>
                          )}
                        </div>
                      </div>

                      {/* 2. Quick Stat Counters */}
                      <div className="grid grid-cols-2 sm:grid-cols-6 gap-2 text-center text-xs">
                        <div className="p-2.5 bg-white border border-slate-200 rounded-lg shadow-2xs">
                          <span className="text-[10px] uppercase font-bold text-slate-400 block">Total Checks</span>
                          <strong className="text-base font-black text-slate-800">{qaAuditResult.counts.total_checks}</strong>
                        </div>
                        <div className="p-2.5 bg-emerald-50 border border-emerald-200 rounded-lg shadow-2xs">
                          <span className="text-[10px] uppercase font-bold text-emerald-700 block">Passed</span>
                          <strong className="text-base font-black text-emerald-800">{qaAuditResult.counts.pass}</strong>
                        </div>
                        <div className="p-2.5 bg-rose-50 border border-rose-200 rounded-lg shadow-2xs">
                          <span className="text-[10px] uppercase font-bold text-rose-700 block">Failed</span>
                          <strong className="text-base font-black text-rose-800">{qaAuditResult.counts.fail}</strong>
                        </div>
                        <div className="p-2.5 bg-amber-50 border border-amber-200 rounded-lg shadow-2xs">
                          <span className="text-[10px] uppercase font-bold text-amber-700 block">Warnings</span>
                          <strong className="text-base font-black text-amber-800">{qaAuditResult.counts.warning}</strong>
                        </div>
                        <div className="p-2.5 bg-slate-100 border border-slate-200 rounded-lg shadow-2xs">
                          <span className="text-[10px] uppercase font-bold text-slate-500 block">Not Applicable</span>
                          <strong className="text-base font-black text-slate-700">{qaAuditResult.counts.not_applicable}</strong>
                        </div>
                        <div className="p-2.5 bg-purple-50 border border-purple-200 rounded-lg shadow-2xs">
                          <span className="text-[10px] uppercase font-bold text-purple-700 block">Inconclusive</span>
                          <strong className="text-base font-black text-purple-800">{qaAuditResult.counts.inconclusive}</strong>
                        </div>
                      </div>

                      {/* 3. Navigation Tabs */}
                      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-1">
                        <div className="flex flex-wrap items-center gap-1 text-xs">
                          <button
                            type="button"
                            onClick={() => setQaActiveTab('all_checks')}
                            className={`px-3 py-1.5 rounded-t-lg font-bold transition-all ${
                              qaActiveTab === 'all_checks'
                                ? 'bg-white border-t border-x border-slate-200 text-slate-900 shadow-2xs'
                                : 'text-slate-500 hover:text-slate-800'
                            }`}
                          >
                            All 10 Categories ({qaAuditResult.counts.total_checks})
                          </button>
                          
                          <button
                            type="button"
                            onClick={() => setQaActiveTab('broken_links')}
                            className={`px-3 py-1.5 rounded-t-lg font-bold flex items-center gap-1.5 transition-all ${
                              qaActiveTab === 'broken_links'
                                ? 'bg-white border-t border-x border-slate-200 text-slate-900 shadow-2xs'
                                : 'text-slate-500 hover:text-slate-800'
                            }`}
                          >
                            <span>Broken Links</span>
                            <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                              (qaAuditResult.tables?.broken_links?.length || 0) > 0
                                ? 'bg-rose-100 text-rose-800'
                                : 'bg-slate-100 text-slate-600'
                            }`}>
                              {qaAuditResult.tables?.broken_links?.length || 0}
                            </span>
                          </button>

                          <button
                            type="button"
                            onClick={() => setQaActiveTab('image_issues')}
                            className={`px-3 py-1.5 rounded-t-lg font-bold flex items-center gap-1.5 transition-all ${
                              qaActiveTab === 'image_issues'
                                ? 'bg-white border-t border-x border-slate-200 text-slate-900 shadow-2xs'
                                : 'text-slate-500 hover:text-slate-800'
                            }`}
                          >
                            <span>Image Issues</span>
                            <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                              (qaAuditResult.tables?.image_issues?.length || 0) > 0
                                ? 'bg-amber-100 text-amber-800'
                                : 'bg-slate-100 text-slate-600'
                            }`}>
                              {qaAuditResult.tables?.image_issues?.length || 0}
                            </span>
                          </button>

                          <button
                            type="button"
                            onClick={() => setQaActiveTab('content_diff')}
                            className={`px-3 py-1.5 rounded-t-lg font-bold flex items-center gap-1.5 transition-all ${
                              qaActiveTab === 'content_diff'
                                ? 'bg-white border-t border-x border-slate-200 text-slate-900 shadow-2xs'
                                : 'text-slate-500 hover:text-slate-800'
                            }`}
                          >
                            <span>Content Parity</span>
                            <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                              (qaAuditResult.tables?.content_differences?.length || 0) > 0
                                ? 'bg-amber-100 text-amber-800'
                                : 'bg-slate-100 text-slate-600'
                            }`}>
                              {qaAuditResult.tables?.content_differences?.length || 0}
                            </span>
                          </button>

                          <button
                            type="button"
                            onClick={() => setQaActiveTab('yoast')}
                            className={`px-3 py-1.5 rounded-t-lg font-bold flex items-center gap-1.5 transition-all ${
                              qaActiveTab === 'yoast'
                                ? 'bg-white border-t border-x border-slate-200 text-slate-900 shadow-2xs'
                                : 'text-slate-500 hover:text-slate-800'
                            }`}
                          >
                            <span>Yoast SEO</span>
                            <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                              (qaAuditResult.tables?.yoast_issues?.length || 0) > 0
                                ? 'bg-amber-100 text-amber-800'
                                : 'bg-slate-100 text-slate-600'
                            }`}>
                              {qaAuditResult.tables?.yoast_issues?.length || 0}
                            </span>
                          </button>
                        </div>

                        {qaActiveTab === 'all_checks' && (
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => setAllQaCategoriesExpanded(true)}
                              className="text-[11px] text-slate-500 hover:text-slate-800 font-semibold"
                            >
                              Expand All
                            </button>
                            <span className="text-slate-300">•</span>
                            <button
                              type="button"
                              onClick={() => setAllQaCategoriesExpanded(false)}
                              className="text-[11px] text-slate-500 hover:text-slate-800 font-semibold"
                            >
                              Collapse All
                            </button>
                          </div>
                        )}
                      </div>

                      {/* 4. Tab Content */}

                      {/* Tab 1: All 10 Categories */}
                      {qaActiveTab === 'all_checks' && (
                        <div className="space-y-3">
                          
                          {/* Filter Pills */}
                          <div className="flex flex-wrap items-center gap-1.5 bg-slate-100/80 p-1 rounded-lg text-xs font-medium">
                            <span className="text-[11px] text-slate-500 px-2 font-semibold">Filter:</span>
                            <button
                              type="button"
                              onClick={() => setQaFilterStatus('all')}
                              className={`px-2.5 py-1 rounded-md transition-all ${
                                qaFilterStatus === 'all'
                                  ? 'bg-white text-slate-900 font-bold shadow-2xs'
                                  : 'text-slate-600 hover:text-slate-900'
                              }`}
                            >
                              All ({qaAuditResult.counts.total_checks})
                            </button>
                            <button
                              type="button"
                              onClick={() => setQaFilterStatus('issues')}
                              className={`px-2.5 py-1 rounded-md transition-all ${
                                qaFilterStatus === 'issues'
                                  ? 'bg-white text-rose-800 font-bold shadow-2xs'
                                  : 'text-slate-600 hover:text-slate-900'
                              }`}
                            >
                              Issues Only ({qaAuditResult.counts.fail + qaAuditResult.counts.warning})
                            </button>
                            <button
                              type="button"
                              onClick={() => setQaFilterStatus('pass')}
                              className={`px-2.5 py-1 rounded-md transition-all ${
                                qaFilterStatus === 'pass'
                                  ? 'bg-white text-emerald-800 font-bold shadow-2xs'
                                  : 'text-slate-600 hover:text-slate-900'
                              }`}
                            >
                              Passed ({qaAuditResult.counts.pass})
                            </button>
                            <button
                              type="button"
                              onClick={() => setQaFilterStatus('na')}
                              className={`px-2.5 py-1 rounded-md transition-all ${
                                qaFilterStatus === 'na'
                                  ? 'bg-white text-slate-700 font-bold shadow-2xs'
                                  : 'text-slate-600 hover:text-slate-900'
                              }`}
                            >
                              N/A ({qaAuditResult.counts.not_applicable})
                            </button>
                          </div>

                          {/* Category Accordions */}
                          <div className="space-y-2.5">
                            {Object.entries(qaAuditResult.categories || {}).map(([catKey, checks]) => {
                              const meta = QA_CATEGORY_CONFIG[catKey] || { label: catKey, icon: '📋' }
                              const isExpanded = !!expandedQaCategories[catKey]
                              
                              const catPass = checks.filter(c => c.status === 'PASS').length
                              const catFail = checks.filter(c => c.status === 'FAIL').length
                              const catWarn = checks.filter(c => c.status === 'WARNING').length
                              const catNA = checks.filter(c => c.status === 'NOT APPLICABLE').length
                              
                              const filteredChecks = checks.filter(c => {
                                if (qaFilterStatus === 'all') return true
                                if (qaFilterStatus === 'issues') return c.status === 'FAIL' || c.status === 'WARNING'
                                if (qaFilterStatus === 'pass') return c.status === 'PASS'
                                if (qaFilterStatus === 'na') return c.status === 'NOT APPLICABLE'
                                return true
                              })

                              if (qaFilterStatus !== 'all' && filteredChecks.length === 0) {
                                return null
                              }

                              return (
                                <div key={catKey} className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-2xs transition-all">
                                  {/* Category Header */}
                                  <button
                                    type="button"
                                    onClick={() => toggleQaCategory(catKey)}
                                    className="w-full px-4 py-3 bg-slate-50/70 hover:bg-slate-100/70 flex items-center justify-between text-left transition-colors"
                                  >
                                    <div className="flex items-center gap-2.5 min-w-0">
                                      <span className="text-lg">{meta.icon}</span>
                                      <div>
                                        <h4 className="text-xs font-bold text-slate-800">{meta.label}</h4>
                                        <span className="text-[10px] text-slate-400 block">{checks.length} check(s) evaluated</span>
                                      </div>
                                    </div>

                                    <div className="flex items-center gap-2 shrink-0">
                                      {catFail > 0 && (
                                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-rose-100 text-rose-800 border border-rose-200">
                                          {catFail} FAIL
                                        </span>
                                      )}
                                      {catWarn > 0 && (
                                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-200">
                                          {catWarn} WARN
                                        </span>
                                      )}
                                      {catFail === 0 && catWarn === 0 && catPass > 0 && (
                                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-200">
                                          {catPass} PASS
                                        </span>
                                      )}
                                      <span className="text-slate-400 text-xs font-bold ml-1">
                                        {isExpanded ? '▲' : '▼'}
                                      </span>
                                    </div>
                                  </button>

                                  {/* Category Body */}
                                  {isExpanded && (
                                    <div className="p-3.5 space-y-2 border-t border-slate-100 bg-white">
                                      {filteredChecks.length === 0 ? (
                                        <p className="text-xs text-slate-400 italic py-1">No checks match the current filter.</p>
                                      ) : (
                                        filteredChecks.map(chk => (
                                          <div
                                            key={chk.key}
                                            className={`p-3.5 rounded-lg border text-xs space-y-2 transition-all ${
                                              chk.status === 'FAIL'
                                                ? 'bg-rose-50/60 border-rose-200'
                                                : chk.status === 'WARNING'
                                                ? 'bg-amber-50/60 border-amber-200'
                                                : chk.status === 'PASS'
                                                ? 'bg-slate-50/50 border-slate-200'
                                                : 'bg-slate-50/40 border-slate-200/80 text-slate-500'
                                            }`}
                                          >
                                            <div className="flex flex-wrap items-center justify-between gap-2">
                                              <div className="flex items-center gap-2">
                                                <QABadge status={chk.status} />
                                                <strong className="text-slate-800 font-semibold">{chk.name}</strong>
                                              </div>

                                              {chk.responsible_party && (
                                                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-md border shrink-0 ${
                                                  chk.responsible_party === 'Richard'
                                                    ? 'bg-purple-100 text-purple-800 border-purple-200'
                                                    : 'bg-blue-100 text-blue-800 border-blue-200'
                                                }`}>
                                                  {chk.responsible_party === 'Richard' ? '👤 Report for Richard' : '🔧 Espial Team Fix'}
                                                </span>
                                              )}
                                            </div>

                                            <p className="text-slate-600 leading-relaxed text-[11px]">
                                              {chk.detail}
                                            </p>

                                            {/* Exact Issue Location */}
                                            {chk.location && (
                                              <div className="flex items-center gap-1.5 text-[10px] text-slate-500">
                                                <span className="font-semibold text-slate-600">📍 Location:</span>
                                                <span className="font-mono bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200 text-slate-700">{chk.location}</span>
                                              </div>
                                            )}

                                            {/* Suggested Manual Correction */}
                                            {chk.suggested_fix && (
                                              <div className="p-2.5 bg-amber-50/80 border border-amber-200 rounded-md text-[11px] text-amber-900 flex items-start gap-2">
                                                <span className="shrink-0 text-amber-700 font-bold">🛠 Suggested Manual Correction:</span>
                                                <span className="flex-1 font-medium">{chk.suggested_fix}</span>
                                              </div>
                                            )}

                                            {/* Meaningful Evidence Preview if non-empty */}
                                            {chk.evidence && (
                                              <div className="pt-0.5">
                                                <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-0.5">Audit Evidence:</div>
                                                <div className="p-2 bg-white/80 rounded border border-slate-200/80 font-mono text-[10px] text-slate-600 overflow-x-auto max-h-24">
                                                  {typeof chk.evidence === 'string'
                                                    ? chk.evidence
                                                    : JSON.stringify(chk.evidence, null, 2)}
                                                </div>
                                              </div>
                                            )}
                                          </div>
                                        ))
                                      )}
                                    </div>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      )}

                      {/* Tab 2: Broken Links Table */}
                      {qaActiveTab === 'broken_links' && (
                        <div className="space-y-3">
                          {(!qaAuditResult.tables?.broken_links || qaAuditResult.tables.broken_links.length === 0) ? (
                            <div className="p-6 text-center bg-emerald-50/70 border border-emerald-200 rounded-xl space-y-1">
                              <span className="text-xl">✅</span>
                              <p className="text-xs font-bold text-emerald-900">Zero Broken Links Found</p>
                              <p className="text-[11px] text-emerald-700">All draft links passed live reachability checks or returned valid HTTP status codes.</p>
                            </div>
                          ) : (
                            <div className="overflow-x-auto rounded-xl border border-rose-200 bg-white">
                              <table className="w-full text-left text-xs text-slate-700">
                                <thead className="bg-rose-50/80 text-[10px] font-bold uppercase tracking-wider text-rose-900 border-b border-rose-200">
                                  <tr>
                                    <th className="p-2.5">Anchor Text</th>
                                    <th className="p-2.5">Target URL</th>
                                    <th className="p-2.5">Status</th>
                                    <th className="p-2.5">Issue Detail</th>
                                    <th className="p-2.5">Location</th>
                                    <th className="p-2.5">Suggested Manual Correction</th>
                                    <th className="p-2.5">Responsible</th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-100 text-[11px]">
                                  {qaAuditResult.tables.broken_links.map((link, idx) => (
                                    <tr key={idx} className="hover:bg-rose-50/30">
                                      <td className="p-2.5 font-bold text-slate-800">{link.anchor_text || '—'}</td>
                                      <td className="p-2.5 font-mono text-[10px] text-slate-600 max-w-xs truncate" title={link.url}>
                                        <a href={link.url} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline">
                                          {link.url} ↗
                                        </a>
                                      </td>
                                      <td className="p-2.5">
                                        <span className="font-bold px-1.5 py-0.5 rounded bg-rose-100 text-rose-800">
                                          {link.status_code || 'Err'}
                                        </span>
                                      </td>
                                      <td className="p-2.5 text-slate-600">{link.error || 'Dead link'}</td>
                                      <td className="p-2.5 font-mono text-[10px] text-slate-600">{link.location || 'Draft content'}</td>
                                      <td className="p-2.5 text-slate-700 font-medium">{link.suggested_fix || 'Update link in WordPress editor.'}</td>
                                      <td className="p-2.5">
                                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${
                                          (link.responsible_party || link.responsible) === 'Richard'
                                            ? 'bg-purple-100 text-purple-800 border-purple-200'
                                            : 'bg-blue-100 text-blue-800 border-blue-200'
                                        }`}>
                                          {link.responsible_party || link.responsible || 'Espial team'}
                                        </span>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Tab 3: Image Issues Table */}
                      {qaActiveTab === 'image_issues' && (
                        <div className="space-y-3">
                          {(!qaAuditResult.tables?.image_issues || qaAuditResult.tables.image_issues.length === 0) ? (
                            <div className="p-6 text-center bg-emerald-50/70 border border-emerald-200 rounded-xl space-y-1">
                              <span className="text-xl">✅</span>
                              <p className="text-xs font-bold text-emerald-900">Featured Image & Credits Verified</p>
                              <p className="text-[11px] text-emerald-700">Dimensions, alt text, and source attribution credit follow client standards.</p>
                            </div>
                          ) : (
                            <div className="overflow-x-auto rounded-xl border border-amber-200 bg-white">
                              <table className="w-full text-left text-xs text-slate-700">
                                <thead className="bg-amber-50/80 text-[10px] font-bold uppercase tracking-wider text-amber-900 border-b border-amber-200">
                                  <tr>
                                    <th className="p-2.5">Issue</th>
                                    <th className="p-2.5">Requirement</th>
                                    <th className="p-2.5">Status</th>
                                    <th className="p-2.5">Location</th>
                                    <th className="p-2.5">Suggested Manual Correction</th>
                                    <th className="p-2.5">Responsible</th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-100 text-[11px]">
                                  {qaAuditResult.tables.image_issues.map((img, idx) => (
                                    <tr key={idx} className="hover:bg-amber-50/30">
                                      <td className="p-2.5 font-bold text-slate-800">{img.issue}</td>
                                      <td className="p-2.5 text-slate-600">{img.requirement}</td>
                                      <td className="p-2.5">
                                        <QABadge status={img.status || 'WARNING'} />
                                      </td>
                                      <td className="p-2.5 font-mono text-[10px] text-slate-600">{img.location || 'WordPress Featured Media'}</td>
                                      <td className="p-2.5 text-slate-700 font-medium">{img.suggested_fix || 'Update image in WordPress Admin.'}</td>
                                      <td className="p-2.5">
                                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${
                                          (img.responsible_party || img.responsible) === 'Richard'
                                            ? 'bg-purple-100 text-purple-800 border-purple-200'
                                            : 'bg-blue-100 text-blue-800 border-blue-200'
                                        }`}>
                                          {img.responsible_party || img.responsible || 'Espial team'}
                                        </span>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Tab 4: Content Parity Table */}
                      {qaActiveTab === 'content_diff' && (
                        <div className="space-y-3">
                          {(!qaAuditResult.tables?.content_differences || qaAuditResult.tables.content_differences.length === 0) ? (
                            <div className="p-6 text-center bg-slate-50 border border-slate-200 rounded-xl space-y-1">
                              <span className="text-xl">ℹ️</span>
                              <p className="text-xs font-bold text-slate-800">No Content Parity Discrepancies</p>
                              <p className="text-[11px] text-slate-500">
                                {qaAuditResult.source_document?.attached
                                  ? 'Vocabulary parity and content integrity verified against source DOCX.'
                                  : 'Standalone audit: Source comparison reported honest NOT APPLICABLE.'}
                              </p>
                            </div>
                          ) : (
                            <div className="overflow-x-auto rounded-xl border border-amber-200 bg-white">
                              <table className="w-full text-left text-xs text-slate-700">
                                <thead className="bg-amber-50/80 text-[10px] font-bold uppercase tracking-wider text-amber-900 border-b border-amber-200">
                                  <tr>
                                    <th className="p-2.5">Description</th>
                                    <th className="p-2.5">Discrepancy Details</th>
                                    <th className="p-2.5">Location</th>
                                    <th className="p-2.5">Suggested Manual Correction</th>
                                    <th className="p-2.5">Responsible</th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-100 text-[11px]">
                                  {qaAuditResult.tables.content_differences.map((diff, idx) => (
                                    <tr key={idx} className="hover:bg-amber-50/30">
                                      <td className="p-2.5 font-bold text-slate-800">{diff.description}</td>
                                      <td className="p-2.5 text-slate-600">{diff.difference || (diff.expected ? `Expected: ${diff.expected} | Actual: ${diff.actual}` : diff.actual)}</td>
                                      <td className="p-2.5 text-slate-500 font-mono text-[10px]">{diff.location || 'Draft body'}</td>
                                      <td className="p-2.5 text-slate-700 font-medium">{diff.suggested_fix || 'Review and align content in WordPress editor.'}</td>
                                      <td className="p-2.5">
                                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${
                                          (diff.responsible_party || diff.responsible) === 'Richard'
                                            ? 'bg-purple-100 text-purple-800 border-purple-200'
                                            : 'bg-blue-100 text-blue-800 border-blue-200'
                                        }`}>
                                          {diff.responsible_party || diff.responsible || 'Espial team'}
                                        </span>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Tab 5: Yoast SEO Issues Table */}
                      {qaActiveTab === 'yoast' && (
                        <div className="space-y-3">
                          {(!qaAuditResult.tables?.yoast_issues || qaAuditResult.tables.yoast_issues.length === 0) ? (
                            <div className="p-6 text-center bg-emerald-50/70 border border-emerald-200 rounded-xl space-y-1">
                              <span className="text-xl">✅</span>
                              <p className="text-xs font-bold text-emerald-900">Yoast SEO Parameters Compliant</p>
                              <p className="text-[11px] text-emerald-700">Meta description character limits (140–155 chars), focus keyphrase placement, and snippet sync pass all checks.</p>
                            </div>
                          ) : (
                            <div className="overflow-x-auto rounded-xl border border-amber-200 bg-white">
                              <table className="w-full text-left text-xs text-slate-700">
                                <thead className="bg-amber-50/80 text-[10px] font-bold uppercase tracking-wider text-amber-900 border-b border-amber-200">
                                  <tr>
                                    <th className="p-2.5">SEO Parameter</th>
                                    <th className="p-2.5">Actual Value</th>
                                    <th className="p-2.5">Client Requirement</th>
                                    <th className="p-2.5">Location</th>
                                    <th className="p-2.5">Suggested Manual Correction</th>
                                    <th className="p-2.5">Responsible</th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-100 text-[11px]">
                                  {qaAuditResult.tables.yoast_issues.map((seo, idx) => (
                                    <tr key={idx} className="hover:bg-amber-50/30">
                                      <td className="p-2.5 font-bold text-slate-800">{seo.parameter}</td>
                                      <td className="p-2.5 text-slate-600 font-mono text-[10px]">{seo.actual_value || 'None'}</td>
                                      <td className="p-2.5 text-slate-600">{seo.requirement}</td>
                                      <td className="p-2.5 font-mono text-[10px] text-slate-600">{seo.location || 'Yoast SEO Meta Box'}</td>
                                      <td className="p-2.5 text-slate-700 font-medium">{seo.suggested_fix || seo.recommendation || 'Update Yoast SEO settings in WordPress Admin.'}</td>
                                      <td className="p-2.5">
                                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${
                                          (seo.responsible_party || seo.responsible) === 'Richard'
                                            ? 'bg-purple-100 text-purple-800 border-purple-200'
                                            : 'bg-blue-100 text-blue-800 border-blue-200'
                                        }`}>
                                          {seo.responsible_party || seo.responsible || 'Espial team'}
                                        </span>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </div>
                      )}

                    </div>
                  )}

                </div>

              </div>
            </SectionCard>
          </div>

        </div>
      )}

      {/* WordPress Site Management Modal */}
      {showSiteModal && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4 backdrop-blur-xs">
          <div className="bg-white rounded-2xl shadow-xl border border-slate-200 w-full max-w-md overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="px-5 py-4 border-b border-slate-200 flex justify-between items-center bg-slate-50">
              <h3 className="text-sm font-bold text-slate-800">Manage WordPress Sites</h3>
              <button onClick={() => setShowSiteModal(false)} className="text-slate-400 hover:text-slate-600 font-bold">✕</button>
            </div>

            <form onSubmit={handleSaveSite} className="p-5 space-y-3.5 text-xs text-slate-700">
              <div>
                <label className="font-bold text-slate-700 block mb-1">Site Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Home Office Test"
                  value={siteForm.name}
                  onChange={e => setSiteForm({ ...siteForm, name: e.target.value })}
                  className="w-full border border-slate-300 rounded-lg p-2 bg-slate-50 focus:bg-white"
                />
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">WordPress Base URL</label>
                <input
                  type="text"
                  required
                  placeholder="https://espialsolutions.com"
                  value={siteForm.url}
                  onChange={e => setSiteForm({ ...siteForm, url: e.target.value })}
                  className="w-full border border-slate-300 rounded-lg p-2 bg-slate-50 focus:bg-white"
                />
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">WordPress Username</label>
                <input
                  type="text"
                  required
                  placeholder="webdev"
                  value={siteForm.username}
                  onChange={e => setSiteForm({ ...siteForm, username: e.target.value })}
                  className="w-full border border-slate-300 rounded-lg p-2 bg-slate-50 focus:bg-white"
                />
              </div>

              <div>
                <label className="font-bold text-slate-700 block mb-1">Application Password</label>
                <input
                  type="password"
                  required
                  placeholder="xxxx xxxx xxxx xxxx"
                  value={siteForm.app_password}
                  onChange={e => setSiteForm({ ...siteForm, app_password: e.target.value })}
                  className="w-full border border-slate-300 rounded-lg p-2 bg-slate-50 focus:bg-white"
                />
                <span className="text-[10px] text-slate-400 block mt-1">
                  Stored securely server-side. Never exposed in browser.
                </span>
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="site_is_default"
                  checked={siteForm.is_default}
                  onChange={e => setSiteForm({ ...siteForm, is_default: e.target.checked })}
                  className="rounded text-indigo-600"
                />
                <label htmlFor="site_is_default" className="text-slate-600 font-medium">Set as default destination site</label>
              </div>

              {siteTestResult && !siteTestResult.success && (
                <div className="p-2.5 rounded bg-red-50 text-red-700 border border-red-200">
                  {siteTestResult.error}
                </div>
              )}

              <div className="flex justify-end gap-2 pt-3 border-t border-slate-200">
                <button
                  type="button"
                  onClick={() => setShowSiteModal(false)}
                  className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={siteSaving}
                  className="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg font-bold"
                >
                  {siteSaving ? 'Saving...' : 'Save Site'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Priority 5: Interactive Content & Link Review Modal */}
      {showLinkReviewModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs overflow-y-auto">
          <div className="bg-white rounded-2xl shadow-2xl max-w-5xl w-full border border-slate-200 overflow-hidden flex flex-col max-h-[90vh]">
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between bg-slate-50/75">
              <div className="flex items-center gap-2.5">
                <span className="text-xl">🔗</span>
                <div>
                  <h3 className="font-bold text-slate-800 text-base">Interactive Content & Link Review</h3>
                  <p className="text-xs text-slate-500">
                    Select consecutive words in the article body to attach validated internal (3-5 words) or authority (3-4 words) anchors.
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowLinkReviewModal(false)}
                className="w-8 h-8 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-600 flex items-center justify-center text-sm font-bold"
              >
                ✕
              </button>
            </div>

            {/* Modal Body */}
            <div className="grid grid-cols-1 lg:grid-cols-12 flex-1 min-h-0 overflow-hidden divide-y lg:divide-y-0 lg:divide-x divide-slate-200">
              
              {/* Left Column: Text Selection & Link Insertion */}
              <div className="lg:col-span-7 p-4 flex flex-col space-y-3 overflow-hidden">
                <div className="bg-indigo-50/60 border border-indigo-200 rounded-xl p-3 space-y-2 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-indigo-950 uppercase text-[10px] tracking-wide">
                      Anchor Text Selection Tool
                    </span>
                    <span className="text-[10px] font-mono text-indigo-700 font-bold">
                      {selectedWordCount > 0 ? `${selectedWordCount} consecutive words` : 'Highlight words below'}
                    </span>
                  </div>

                  {/* Selected words display */}
                  <div className="p-2 bg-white rounded-lg border border-indigo-200 text-slate-800 font-medium truncate">
                    {selectedAnchorText ? `"${selectedAnchorText}"` : <span className="text-slate-400 italic">No text selected. Drag cursor over text in the preview below.</span>}
                  </div>

                  {/* Compliance Badge */}
                  {selectedAnchorText && targetLinkUrl && (
                    <div>
                      {targetLinkUrl.toLowerCase().includes('homebusinessmag.com') ? (
                        selectedWordCount >= 3 && selectedWordCount <= 5 ? (
                          <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-800 bg-emerald-100 border border-emerald-300 px-2 py-0.5 rounded">
                            ✓ Valid Internal Anchor (3-5 consecutive words)
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[11px] font-bold text-amber-800 bg-amber-100 border border-amber-300 px-2 py-0.5 rounded">
                            ⚠️ Internal anchor must be 3-5 words (currently {selectedWordCount})
                          </span>
                        )
                      ) : (
                        selectedWordCount >= 3 && selectedWordCount <= 4 ? (
                          <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-800 bg-emerald-100 border border-emerald-300 px-2 py-0.5 rounded">
                            ✓ Valid Authority Anchor (3-4 consecutive words)
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[11px] font-bold text-amber-800 bg-amber-100 border border-amber-300 px-2 py-0.5 rounded">
                            ⚠️ Authority anchor must be 3-4 words (currently {selectedWordCount})
                          </span>
                        )
                      )}
                    </div>
                  )}

                  {/* Target URL input & quick recommendations */}
                  <div className="space-y-1.5 pt-1">
                    <input
                      type="url"
                      value={targetLinkUrl}
                      onChange={e => setTargetLinkUrl(e.target.value)}
                      placeholder="Enter target URL (e.g. https://homebusinessmag.com/... or https://forbes.com/...)"
                      className="w-full text-xs border border-slate-300 rounded-lg p-2 bg-white text-slate-800 focus:ring-indigo-500 focus:border-indigo-500"
                    />
                    <div className="flex flex-wrap gap-1 text-[10px]">
                      <span className="text-slate-400 py-0.5">Quick:</span>
                      <button
                        type="button"
                        onClick={() => setTargetLinkUrl('https://homebusinessmag.com/management/')}
                        className="px-2 py-0.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded border border-slate-200"
                      >
                        + HBM Management
                      </button>
                      <button
                        type="button"
                        onClick={() => setTargetLinkUrl('https://homebusinessmag.com/leadership/')}
                        className="px-2 py-0.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded border border-slate-200"
                      >
                        + HBM Leadership
                      </button>
                      <button
                        type="button"
                        onClick={() => setTargetLinkUrl('https://www.forbes.com/business/')}
                        className="px-2 py-0.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded border border-slate-200"
                      >
                        + Forbes Authority
                      </button>
                      <button
                        type="button"
                        onClick={() => setTargetLinkUrl('https://www.entrepreneur.com/')}
                        className="px-2 py-0.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded border border-slate-200"
                      >
                        + Entrepreneur Authority
                      </button>
                    </div>
                  </div>

                  {linkAttachError && (
                    <p className="text-[11px] text-red-600 font-semibold">{linkAttachError}</p>
                  )}

                  <button
                    type="button"
                    onClick={handleAttachLink}
                    disabled={!selectedAnchorText || !targetLinkUrl}
                    className="w-full py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 text-white font-bold rounded-lg text-xs transition-colors shadow-xs"
                  >
                    Attach Link to Selected Words
                  </button>
                </div>

                {/* Article Content Viewer */}
                <div className="flex-1 min-h-0 flex flex-col space-y-1">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                    Article Content (Drag to select text)
                  </span>
                  <div
                    onMouseUp={handleContentSelection}
                    className="flex-1 overflow-y-auto p-4 bg-slate-50 border border-slate-200 rounded-xl text-xs text-slate-700 leading-relaxed select-text font-serif space-y-3 max-h-72"
                    dangerouslySetInnerHTML={{
                      __html: editedArticleContent || pausedSession?.ai_result?.content || processResult?.ai_result?.content || '<p class="text-slate-400 italic">No article content available yet.</p>',
                    }}
                  />
                </div>
              </div>

              {/* Right Column: Preserved DOCX Hyperlinks & Active Content Links */}
              <div className="lg:col-span-5 p-4 bg-slate-50 flex flex-col space-y-4 overflow-y-auto max-h-[70vh]">
                
                {/* Preserved DOCX Links */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-slate-800 uppercase text-[11px]">
                      Preserved Original DOCX Links
                    </span>
                    <span className="text-[10px] bg-emerald-100 text-emerald-800 font-bold px-2 py-0.5 rounded-full">
                      {(pausedSession?.ai_result?.docx_hyperlinks || processResult?.ai_result?.docx_hyperlinks || []).length} Preserved
                    </span>
                  </div>

                  <div className="space-y-1.5 max-h-36 overflow-y-auto">
                    {(pausedSession?.ai_result?.docx_hyperlinks || processResult?.ai_result?.docx_hyperlinks || []).length > 0 ? (
                      (pausedSession?.ai_result?.docx_hyperlinks || processResult?.ai_result?.docx_hyperlinks || []).map((link, idx) => (
                        <div key={idx} className="bg-white p-2 rounded-lg border border-slate-200 text-[11px] space-y-0.5">
                          <div className="font-semibold text-slate-800 truncate">
                            "{link.anchor_text || '(no anchor)'}"
                          </div>
                          <a
                            href={link.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-indigo-600 hover:underline block truncate font-mono text-[10px]"
                          >
                            {link.url} ↗
                          </a>
                        </div>
                      ))
                    ) : (
                      <p className="text-slate-400 italic text-[11px]">No original hyperlinks detected in source DOCX.</p>
                    )}
                  </div>
                </div>

                {/* Active Draft Links in Content */}
                <div className="space-y-2 pt-2 border-t border-slate-200">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-slate-800 uppercase text-[11px]">
                      Active Links in Draft Content
                    </span>
                  </div>

                  {(() => {
                    const content = editedArticleContent || pausedSession?.ai_result?.content || processResult?.ai_result?.content || ''
                    const matches = [...content.matchAll(/<a\b[^>]*href=["']([^"']+)["'][^>]*>(.*?)<\/a>/gi)]
                    if (matches.length === 0) {
                      return <p className="text-slate-400 italic text-[11px]">No links attached in body content yet.</p>
                    }
                    return (
                      <div className="space-y-1.5 max-h-48 overflow-y-auto">
                        {matches.map((m, idx) => {
                          const href = m[1]
                          const anchor = m[2].replace(/<[^>]+>/g, '').trim()
                          const words = anchor.split(/\s+/).filter(Boolean).length
                          const isHbm = href.toLowerCase().includes('homebusinessmag.com')
                          const isOk = isHbm ? (words >= 3 && words <= 5) : (words >= 3 && words <= 4)
                          return (
                            <div key={idx} className="bg-white p-2 rounded-lg border border-slate-200 text-[11px] space-y-1">
                              <div className="flex items-center justify-between">
                                <span className="font-bold text-slate-800 truncate mr-2">"{anchor}"</span>
                                <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${
                                  isOk ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'
                                }`}>
                                  {words} words {isOk ? '✓' : '⚠️'}
                                </span>
                              </div>
                              <div className="flex items-center justify-between">
                                <a
                                  href={href}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-indigo-600 hover:underline truncate max-w-[200px] font-mono text-[10px]"
                                >
                                  {href} ↗
                                </a>
                                <button
                                  type="button"
                                  onClick={() => handleRemoveLink(href)}
                                  className="text-[10px] font-semibold text-red-600 hover:text-red-800 hover:underline"
                                >
                                  Remove
                                </button>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    )
                  })()}
                </div>

              </div>

            </div>

            {/* Modal Footer */}
            <div className="px-6 py-3 border-t border-slate-200 flex items-center justify-between bg-slate-50/75">
              <span className="text-xs text-slate-500 font-medium">
                Changes will be included when creating the WordPress draft.
              </span>
              <button
                type="button"
                onClick={() => setShowLinkReviewModal(false)}
                className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded-xl text-xs transition-colors shadow-xs"
              >
                ✓ Save Approved Content & Close
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
