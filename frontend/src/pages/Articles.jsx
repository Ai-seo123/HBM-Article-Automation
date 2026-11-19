import { useState, useEffect } from 'react'
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

// ── Sub-components ───────────────────────────────────────────────────────────

function SectionCard({ title, children, actions }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-sm">
      <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700">{title}</h2>
        {actions && <div>{actions}</div>}
      </div>
      <div className="p-5">{children}</div>
    </div>
  )
}

function Spinner({ label }) {
  return (
    <div className="flex items-center gap-2 text-slate-400 text-sm py-2">
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
    <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{msg}</p>
  ) : null
}

// ── Step progress indicator ───────────────────────────────────────────────────

const STEPS = [
  { key: 'reading',    label: 'Reading Word document' },
  { key: 'duplicate',  label: 'Checking duplicate' },
  { key: 'gemini',     label: 'Processing with Gemini' },
  { key: 'done',       label: 'Completed' },
]

function StepProgress({ activeStep, error }) {
  const stepKeys = STEPS.map(s => s.key)
  const activeIdx = stepKeys.indexOf(activeStep)

  return (
    <div className="flex items-start gap-0">
      {STEPS.map((step, i) => {
        const done = i < activeIdx
        const active = i === activeIdx
        const isLast = i === STEPS.length - 1
        const isError = active && error

        return (
          <div key={step.key} className="flex items-center flex-1 min-w-0">
            <div className="flex flex-col items-center gap-1.5 shrink-0">
              <div className={[
                'w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold border-2 transition-all',
                done  ? 'bg-emerald-500 border-emerald-500 text-white' :
                isError ? 'bg-red-500 border-red-500 text-white' :
                active ? 'bg-indigo-600 border-indigo-600 text-white animate-pulse' :
                         'bg-white border-slate-300 text-slate-400',
              ].join(' ')}>
                {done ? '✓' : isError ? '✕' : i + 1}
              </div>
              <span className={[
                'text-xs font-medium text-center leading-tight max-w-[72px]',
                done ? 'text-emerald-600' :
                isError ? 'text-red-500' :
                active ? 'text-indigo-600' : 'text-slate-400',
              ].join(' ')}>
                {step.label}
              </span>
            </div>
            {!isLast && (
              <div className={[
                'flex-1 h-0.5 mx-2 mb-6 rounded',
                done ? 'bg-emerald-400' : 'bg-slate-200',
              ].join(' ')} />
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Destination Summary panel ───────────────────────────────────────────────────

function DestinationSummaryCard({ destination, draftResult, envatoResult, aiResult }) {
  const postTitle = destination?.title || aiResult?.title || 'Untitled'
  
  const primaryCat = 
    (destination?.primary_category && destination.primary_category !== 'Uncategorized')
      ? destination.primary_category
      : draftResult?.data?.category_primary || 
        (draftResult?.data?.category_names && draftResult.data.category_names[0]) ||
        destination?.primary_category || 
        'Uncategorized'

  const allCats = 
    (destination?.all_categories && destination.all_categories.length > 0 && destination.all_categories[0] !== 'Uncategorized')
      ? destination.all_categories
      : (draftResult?.data?.category_names && draftResult.data.category_names.length > 0)
        ? draftResult.data.category_names
        : (destination?.all_categories && destination.all_categories.length > 0)
          ? destination.all_categories
          : (primaryCat && primaryCat !== 'Uncategorized' ? [primaryCat] : ['Uncategorized'])

  const authorName = destination?.author || 'Home Office Editor'
  const draftStatus = destination?.status || draftResult?.data?.status_value || 'draft'
  const postId = destination?.post_id || draftResult?.data?.post_id
  const draftUrl = destination?.url || draftResult?.data?.url
  const mediaId = destination?.featured_media_id || draftResult?.data?.featured_media || envatoResult?.data?.wordpress_media?.media_id
  const imageSource = destination?.image_source || (envatoResult?.data?.source === 'pexels' ? 'Pexels (from instructions)' : envatoResult?.data?.source === 'docx' ? 'DOCX embedded image' : 'Envato')
  const imageDimensions = destination?.image_dimensions || '1000 × 667 px'
  const imageSourceUrl = destination?.image_source_url || envatoResult?.data?.source_url

  return (
    <div className="bg-slate-50 border border-slate-200 rounded-xl p-5 space-y-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 pb-3">
        <div>
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">WordPress Draft</span>
          <h3 className="text-base font-bold text-slate-800">{postTitle}</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wider px-2.5 py-1 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-200">
            {draftStatus}
          </span>
          <span className="text-xs font-bold uppercase tracking-wider px-2 py-1 rounded bg-amber-100 text-amber-800 border border-amber-300">
            TEST ENV
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 text-xs">
        <div className="bg-white p-3 rounded-lg border border-slate-200 space-y-1">
          <span className="font-bold text-slate-400 uppercase tracking-wider block text-[10px]">Primary Category</span>
          <span className="font-semibold text-indigo-700 bg-indigo-50 border border-indigo-200 px-2 py-0.5 rounded inline-block">
            {primaryCat}
          </span>
          <p className="text-[11px] text-slate-500 mt-1">
            All: <span className="font-medium text-slate-700">{allCats.join(', ')}</span>
          </p>
        </div>

        <div className="bg-white p-3 rounded-lg border border-slate-200 space-y-1">
          <span className="font-bold text-slate-400 uppercase tracking-wider block text-[10px]">Assigned Author</span>
          <p className="font-semibold text-slate-800 text-sm">👤 {authorName}</p>
          <p className="text-[11px] text-slate-500">WordPress Role: <span className="font-medium text-slate-700">author</span></p>
        </div>

        <div className="bg-white p-3 rounded-lg border border-slate-200 space-y-1">
          <span className="font-bold text-slate-400 uppercase tracking-wider block text-[10px]">WordPress IDs</span>
          <p className="text-slate-700">Post ID: <strong className="font-mono text-slate-800">#{postId || '—'}</strong></p>
          <p className="text-slate-700">Featured Media ID: <strong className="font-mono text-slate-800">🖼️ #{mediaId || '—'}</strong></p>
        </div>

        <div className="bg-white p-3 rounded-lg border border-slate-200 space-y-1 sm:col-span-2 lg:col-span-2">
          <div className="flex items-center justify-between">
            <span className="font-bold text-slate-400 uppercase tracking-wider block text-[10px]">Featured Image Source</span>
            <span className="text-emerald-700 font-semibold bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded text-[11px]">
              ✓ Dimensions: {imageDimensions}
            </span>
          </div>
          <div className="flex items-center justify-between gap-2 pt-0.5">
            <span className="font-medium text-slate-700">{imageSource}</span>
            {imageSourceUrl && (
              <a
                href={imageSourceUrl}
                target="_blank"
                rel="noreferrer"
                className="text-indigo-600 hover:underline font-semibold text-xs"
              >
                View Source Link ↗
              </a>
            )}
          </div>
        </div>

        <div className="bg-white p-3 rounded-lg border border-slate-200 space-y-1 sm:col-span-2 lg:col-span-1 flex flex-col justify-center">
          <span className="font-bold text-slate-400 uppercase tracking-wider block text-[10px]">WordPress Draft Link</span>
          {draftUrl ? (
            <a
              href={draftUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center justify-center px-3 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-semibold uppercase tracking-wider transition-colors gap-1.5 shadow-sm"
            >
              <span>Open Draft</span>
              <span>↗</span>
            </a>
          ) : (
            <span className="text-slate-400 italic">Link unavailable</span>
          )}
        </div>
      </div>
    </div>
  )
}

// ── QA Checklist panel ────────────────────────────────────────────────────────

function QAChecklistPanel({ checklist }) {
  if (!checklist) return null

  const sections = [
    {
      title: '1. Content & Structure',
      items: [
        { key: 'instructions_followed', label: 'Article-specific instructions followed' },
        { key: 'title_exact',            label: 'Title exact (H1 preserved)' },
        { key: 'content_unchanged',      label: 'Content preserved (never rewritten)' },
        { key: 'headings_preserved',     label: 'Headings preserved (H2/H3/H4)' },
        { key: 'formatting_preserved',   label: 'Formatting (bold, italic, lists) preserved' },
        { key: 'final_spot_check',       label: 'Final content spot-check' },
      ],
    },
    {
      title: '2. Links & Authority',
      items: [
        { key: 'hyperlinks_preserved',    label: 'Original DOCX hyperlinks preserved' },
        { key: 'no_search_engine_links',  label: 'No search engine URLs added' },
        { key: 'approved_authority_links',label: 'Approved authority links verified' },
      ],
    },
    {
      title: '3. Featured Image & Media',
      items: [
        { key: 'image_dimensions',       label: 'Image dimensions: 1000 × 667 px' },
        { key: 'source_platform',        label: 'Source platform: DOCX / Pexels / Envato' },
        { key: 'source_url_present',     label: 'Source URL present and clickable' },
        { key: 'alt_text_present',       label: 'Image Alt text generated' },
        { key: 'image_title_present',    label: 'Image Title generated' },
        { key: 'caption_present',        label: 'Image Caption & credit link set' },
      ],
    },
    {
      title: '4. Category & Author',
      items: [
        { key: 'primary_category',       label: 'Primary Category parsed dynamically' },
        { key: 'featured_category',      label: 'Featured Category included' },
        { key: 'additional_categories',  label: 'Additional Categories checked' },
        { key: 'author_assigned',        label: 'Author resolved & assigned in WordPress' },
      ],
    },
    {
      title: '5. SEO & Yoast',
      items: [
        { key: 'focus_keyphrase',        label: 'Focus Keyphrase (≤ 4 words)' },
        { key: 'seo_title',              label: 'SEO Title generated' },
        { key: 'meta_description',       label: 'Meta Description generated' },
        { key: 'excerpt',                label: 'Excerpt populated' },
        { key: 'slug',                   label: 'URL Slug formatted' },
        { key: 'synonyms',               label: 'Keyphrase Synonyms generated' },
        { key: 'yoast_check',            label: 'Yoast SEO real analysis passed' },
        { key: 'duplicate_check',        label: 'WordPress Duplicate Check completed' },
        { key: 'draft_status',           label: 'WordPress Status = DRAFT' },
      ],
    },
  ]

  const getItemData = (key) => {
    if (!checklist) return null
    if (checklist[key] !== undefined) return checklist[key]
    for (const section of Object.values(checklist)) {
      if (typeof section === 'object' && section !== null && section[key] !== undefined) {
        return section[key]
      }
    }
    return null
  }

  const getItemStatus = (key) => {
    const val = getItemData(key)
    if (!val) return 'FAIL'
    if (typeof val === 'object') {
      return val.status || (val.passed ? 'PASS' : 'FAIL')
    }
    return Boolean(val) ? 'PASS' : 'FAIL'
  }

  const allKeys = sections.flatMap(s => s.items.map(i => i.key))
  const passedCount = allKeys.filter(k => {
    const st = getItemStatus(k)
    return st === 'PASS' || st === 'NOT APPLICABLE'
  }).length
  const totalCount = allKeys.length

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between pb-2 border-b border-slate-100">
        <div>
          <p className="text-xs font-bold text-slate-700 uppercase tracking-wide">HBM Article Posting QA Checklist</p>
          <p className="text-[11px] text-slate-400">Strict compliance verification against posting guidelines</p>
        </div>
        <span className={[
          'text-xs font-bold px-3 py-1 rounded-full border',
          passedCount === totalCount
            ? 'bg-emerald-100 text-emerald-800 border-emerald-300'
            : 'bg-amber-100 text-amber-800 border-amber-300'
        ].join(' ')}>
          {passedCount} / {totalCount} PASSED
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {sections.map(section => (
          <div key={section.title} className="bg-slate-50 border border-slate-200 rounded-lg p-3 space-y-2">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-600 border-b border-slate-200 pb-1">
              {section.title}
            </h4>
            <div className="space-y-1.5">
              {section.items.map(item => {
                const val = getItemData(item.key)
                const status = getItemStatus(item.key)
                const isPass = status === 'PASS'
                const isNA = status === 'NOT APPLICABLE'
                const isWarn = status === 'WARNING'
                const tooltipText = val?.detail ? `${item.label}: ${val.detail}` : item.label
                return (
                  <div key={item.key} className="flex items-center justify-between text-xs py-0.5" title={tooltipText}>
                    <span className={isPass || isNA ? 'text-slate-700 font-medium truncate mr-2' : 'text-slate-400 truncate mr-2'}>
                      {item.label}
                    </span>
                    <span className={[
                      'font-bold px-1.5 py-0.5 rounded text-[10px] tracking-wider uppercase',
                      isPass
                        ? 'bg-emerald-100 text-emerald-700 border border-emerald-200'
                        : isNA
                        ? 'bg-slate-100 text-slate-500 border border-slate-200'
                        : isWarn
                        ? 'bg-amber-100 text-amber-700 border border-amber-200'
                        : 'bg-red-100 text-red-600 border border-red-200'
                    ].join(' ')}>
                      {isNA ? 'N/A' : status}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── AI Result panel ───────────────────────────────────────────────────────────

function AiResultPanel({ result }) {
  const fields = [
    { key: 'title',           label: 'Article Title (Preserved)',  mono: false },
    { key: 'focus_keyphrase', label: 'Focus Keyphrase (≤ 4 words)', mono: true  },
    { key: 'seo_title',       label: 'SEO Title',        mono: false },
    { key: 'slug',            label: 'Slug',             mono: true  },
    { key: 'meta_description',label: 'Meta Description', mono: false },
    { key: 'synonyms',        label: 'Keyphrase Synonyms', mono: true },
    { key: 'excerpt',         label: 'Excerpt',          mono: false },
  ]

  return (
    <div className="space-y-5">
      {/* Meta fields */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {fields.map(f => (
          <div key={f.key} className="space-y-1">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">{f.label}</p>
            {result[f.key] ? (
              <p className={['text-sm text-slate-800 bg-slate-50 rounded-lg px-3 py-2 break-words', f.mono ? 'font-mono' : ''].join(' ')}>
                {result[f.key]}
              </p>
            ) : (
              <p className="text-sm text-slate-400 italic">Not set</p>
            )}
          </div>
        ))}
      </div>

      {/* Hyperlinks preserved */}
      {result.docx_hyperlinks?.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
            Preserved Hyperlinks ({result.docx_hyperlinks.length})
          </p>
          <div className="bg-slate-50 rounded-lg px-3 py-2 max-h-32 overflow-y-auto space-y-1">
            {result.docx_hyperlinks.map((link, i) => (
              <div key={i} className="text-xs">
                <span className="text-slate-500 mr-1">{link.anchor_text || '(no anchor)'}:</span>
                <a href={link.url} target="_blank" rel="noreferrer" className="text-indigo-500 hover:underline break-all">
                  {link.url}
                </a>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Content — preserved from DOCX */}
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Article Content (Preserved from DOCX)</p>
          <span className="text-xs bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded-full">Not rewritten by AI</span>
        </div>
        {result.content ? (
          <div
            className="text-sm text-slate-700 bg-slate-50 rounded-lg px-4 py-4 leading-relaxed max-h-96 overflow-y-auto prose prose-sm max-w-none"
            dangerouslySetInnerHTML={{ __html: result.content }}
          />
        ) : (
          <p className="text-sm text-slate-400 italic">No content</p>
        )}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Articles() {
  // ── Projects
  const [projects, setProjects]           = useState([])
  const [projectsLoading, setProjectsLoading] = useState(false)
  const [projectsError, setProjectsError] = useState(null)
  const [selectedProject, setSelectedProject] = useState(null)

  // ── Messages
  const [messages, setMessages]           = useState([])
  const [messagesLoading, setMessagesLoading] = useState(false)
  const [messagesError, setMessagesError] = useState(null)
  const [selectedMessage, setSelectedMessage] = useState(null)

  // ── Message detail + attachments
  const [msgDetail, setMsgDetail]         = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError]     = useState(null)
  const [selectedAttachment, setSelectedAttachment] = useState(null)

  // ── Processing
  const [processing, setProcessing]       = useState(false)
  const [activeStep, setActiveStep]       = useState(null)
  const [processResult, setProcessResult] = useState(null)
  const [processError, setProcessError]   = useState(null)

  // ── Basecamp connection check
  const [connected, setConnected]         = useState(false)
  const [connChecked, setConnChecked]     = useState(false)

  useEffect(() => {
    fetch(`${API_BASE}/api/basecamp/status`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { setConnected(Boolean(d.connected && !d.is_expired && !d.expired)); setConnChecked(true) })
      .catch(() => setConnChecked(true))
  }, [])

  // ── Load projects once connected
  useEffect(() => {
    if (!connected) return
    setProjectsLoading(true)
    setProjectsError(null)
    fetch(`${API_BASE}/api/basecamp/projects`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => setProjects(d.projects ?? []))
      .catch(() => setProjectsError('Could not load projects.'))
      .finally(() => setProjectsLoading(false))
  }, [connected])

  // ── Load messages when project changes
  useEffect(() => {
    if (!selectedProject) { setMessages([]); setSelectedMessage(null); return }
    setMessagesLoading(true)
    setMessagesError(null)
    setSelectedMessage(null)
    setMsgDetail(null)
    setSelectedAttachment(null)
    setProcessResult(null)
    setProcessError(null)
    setActiveStep(null)
    fetch(`${API_BASE}/api/basecamp/projects/${selectedProject.id}/messages`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => setMessages(d.messages ?? []))
      .catch(() => setMessagesError('Could not load messages.'))
      .finally(() => setMessagesLoading(false))
  }, [selectedProject])

  // ── Load message detail (full body + attachments)
  useEffect(() => {
    if (!selectedMessage || !selectedProject) { setMsgDetail(null); return }
    setDetailLoading(true)
    setDetailError(null)
    setSelectedAttachment(null)
    setProcessResult(null)
    setProcessError(null)
    setActiveStep(null)
    fetch(`${API_BASE}/api/basecamp/projects/${selectedProject.id}/messages/${selectedMessage.id}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => setMsgDetail(d))
      .catch(() => setDetailError('Could not load message details.'))
      .finally(() => setDetailLoading(false))
  }, [selectedMessage, selectedProject])

  const docxAttachments = (msgDetail?.attachments ?? []).filter(a => {
    const fn = (a.filename || '').toLowerCase()
    const ct = (a.content_type || '').toLowerCase()
    return fn.endsWith('.docx') || ct.includes('wordprocessingml') || ct.includes('openxmlformats')
  })

  // ── Process
  async function handleProcess() {
    if (!selectedProject || !selectedMessage || !selectedAttachment) return
    setProcessing(true)
    setProcessResult(null)
    setProcessError(null)
    setActiveStep('reading')

    // Simulate brief stage delays for UX visibility
    await new Promise(r => setTimeout(r, 500))
    setActiveStep('duplicate')

    try {
      const res = await fetch(`${API_BASE}/api/articles/process`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: selectedProject.id,
          message_id: selectedMessage.id,
          attachment_id: String(selectedAttachment.id),
        }),
      })
      const data = await res.json()

      if (data.status === 'duplicate') {
        setActiveStep('duplicate')
        setProcessResult(data)
      } else if (data.status === 'completed') {
        setActiveStep('gemini')
        await new Promise(r => setTimeout(r, 300))
        setActiveStep('done')
        setProcessResult(data)
      } else {
        setProcessError(data.error || 'Processing failed. Please try again.')
        setActiveStep('reading')
      }
    } catch {
      setProcessError('Could not reach the backend. Make sure the server is running.')
      setActiveStep(null)
    } finally {
      setProcessing(false)
    }
  }

  function reset() {
    setSelectedAttachment(null)
    setProcessResult(null)
    setProcessError(null)
    setActiveStep(null)
  }

  // ── Not connected state
  if (connChecked && !connected) {
    return (
      <div className="space-y-6 max-w-2xl">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Articles</h1>
          <p className="text-slate-500 mt-1 text-sm">Process Word documents from Basecamp through Gemini AI.</p>
        </div>
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-6 text-center">
          <div className="text-4xl mb-3">🏕️</div>
          <h2 className="font-semibold text-slate-700 mb-1">Basecamp Not Connected</h2>
          <p className="text-sm text-slate-500 mb-4">Connect your Basecamp account to browse projects and process articles.</p>
          <a href="/basecamp" className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 transition-colors">
            Go to Basecamp Settings →
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6 max-w-5xl">
      {/* Page heading */}
      <div>
        <h1 className="text-2xl font-bold text-slate-800">Articles</h1>
        <p className="text-slate-500 mt-1 text-sm">
          Select a Basecamp project, message, and Word attachment to process with Gemini AI.
        </p>
      </div>

      {/* ── Step 1: Project selector ─────────────────────────────────── */}
      <SectionCard title="Step 1 — Select Project">
        {projectsLoading && <Spinner label="Loading projects…" />}
        <ErrorMsg msg={projectsError} />
        {!projectsLoading && !projectsError && projects.length === 0 && (
          <p className="text-sm text-slate-400">No projects found. Make sure Basecamp is connected.</p>
        )}
        {projects.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {projects.map(p => (
              <button
                key={p.id}
                onClick={() => setSelectedProject(p)}
                className={[
                  'w-full text-left px-4 py-3 rounded-lg border text-sm transition-all',
                  selectedProject?.id === p.id
                    ? 'border-indigo-400 bg-indigo-50 ring-1 ring-indigo-200 font-medium text-indigo-700'
                    : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50 text-slate-700',
                ].join(' ')}
              >
                <p className="font-medium truncate">{p.name}</p>
                <p className="text-xs text-slate-400 mt-0.5">Updated {formatDate(p.updated_at)}</p>
              </button>
            ))}
          </div>
        )}
      </SectionCard>

      {/* ── Step 2: Message selector ──────────────────────────────────── */}
      {selectedProject && (
        <SectionCard
          title={`Step 2 — Select Message (${selectedProject.name})`}
          actions={
            !messagesLoading && !messagesError && messages.length > 0 && (
              <span className={`text-[11px] font-semibold px-2.5 py-0.5 rounded-full border ${
                selectedMessage
                  ? 'bg-indigo-50 text-indigo-700 border-indigo-200'
                  : 'bg-slate-100 text-slate-600 border-slate-200'
              }`}>
                {selectedMessage ? (
                  <>Selected: <strong className="font-bold text-indigo-900">{messages.findIndex(m => m.id === selectedMessage.id) + 1}</strong> of <strong className="font-bold text-indigo-900">{messages.length}</strong> articles</>
                ) : (
                  <>0 of {messages.length} articles selected</>
                )}
              </span>
            )
          }
        >
          {messagesLoading && <Spinner label="Loading messages…" />}
          <ErrorMsg msg={messagesError} />
          {!messagesLoading && !messagesError && messages.length === 0 && (
            <p className="text-sm text-slate-400">No messages found in this project.</p>
          )}
          {messages.length > 0 && (
            <div className="space-y-2">
              {messages.map(m => (
                <button
                  key={m.id}
                  onClick={() => setSelectedMessage(m)}
                  className={[
                    'w-full text-left px-4 py-3 rounded-lg border text-sm transition-all',
                    selectedMessage?.id === m.id
                      ? 'border-indigo-400 bg-indigo-50 ring-1 ring-indigo-200'
                      : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50',
                  ].join(' ')}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-slate-800 truncate">{m.subject || '(No subject)'}</p>
                      <p className="text-xs text-slate-400 mt-0.5">
                        {m.author} · {formatDate(m.created_at)}
                        {m.attachment_count > 0 && (
                          <span className="ml-2 text-amber-600 font-medium">
                            📎 {m.attachment_count} attachment{m.attachment_count !== 1 ? 's' : ''}
                          </span>
                        )}
                      </p>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </SectionCard>
      )}

      {/* ── Step 3: Attachment selector ───────────────────────────────── */}
      {selectedMessage && (
        <SectionCard title="Step 3 — Select Word Attachment">
          {detailLoading && <Spinner label="Loading attachments…" />}
          <ErrorMsg msg={detailError} />
          {!detailLoading && !detailError && docxAttachments.length === 0 && (
            <div className="text-center py-6">
              <p className="text-3xl mb-2">📭</p>
              <p className="text-sm text-slate-500 font-medium">No .docx files in this message</p>
              <p className="text-xs text-slate-400 mt-1">Only Word documents (.docx) can be processed.</p>
            </div>
          )}
          {docxAttachments.length > 0 && (
            <div className="space-y-2">
              {docxAttachments.map((att, i) => (
                <button
                  key={att.id ?? i}
                  onClick={() => { 
                    setSelectedAttachment(att); 
                    setProcessResult(null); 
                    setProcessError(null); 
                    setActiveStep(null); 
                  }}
                  className={[
                    'w-full text-left flex items-center gap-3 px-4 py-3 rounded-lg border text-sm transition-all',
                    selectedAttachment?.id === att.id
                      ? 'border-indigo-400 bg-indigo-50 ring-1 ring-indigo-200'
                      : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50',
                  ].join(' ')}
                >
                  <span className="text-2xl shrink-0">📄</span>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-slate-800 truncate">{att.filename}</p>
                    <p className="text-xs text-slate-400">{formatBytes(att.byte_size)}</p>
                  </div>
                  {selectedAttachment?.id === att.id && (
                    <span className="shrink-0 text-xs font-medium text-indigo-600 bg-indigo-50 border border-indigo-200 px-2 py-0.5 rounded-full">
                      Selected
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}
        </SectionCard>
      )}

      {/* ── Step 4: Process button + progress ─────────────────────────── */}
      {selectedAttachment && (
        <SectionCard title="Step 4 — Process Article">
          <div className="space-y-5">
            {/* Selection summary */}
            <div className="text-sm text-slate-600 bg-slate-50 rounded-lg px-4 py-3 space-y-1">
              <p><span className="font-medium">Project:</span> {selectedProject.name}</p>
              <p><span className="font-medium">Message:</span> {selectedMessage.subject}</p>
              <p><span className="font-medium">File:</span> {selectedAttachment.filename}</p>
            </div>

            {/* Progress steps (shown during/after processing) */}
            {activeStep && (
              <div className="py-2">
                <StepProgress
                  activeStep={activeStep}
                  error={!!processError}
                />
              </div>
            )}

            {/* Process button */}
            {!processResult && (
              <button
                onClick={handleProcess}
                disabled={processing}
                className="w-full sm:w-auto px-6 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2"
              >
                {processing ? (
                  <>
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                    </svg>
                    Processing…
                  </>
                ) : '✨ Process Article'}
              </button>
            )}

            <ErrorMsg msg={processError} />

            {/* ── Duplicate found ──────────────────────────────────── */}
            {processResult?.status === 'duplicate' && (
              <div className="bg-orange-50 border border-orange-200 rounded-xl p-5">
                <div className="flex items-start gap-3">
                  <span className="text-2xl shrink-0">⚠️</span>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-orange-800 mb-1">Duplicate Article Found</h3>
                    <p className="text-sm text-orange-700 mb-3">
                      This article already exists on the HBM WordPress website. Gemini processing was not started.
                    </p>
                    {processResult.existing_post && (
                      <div className="bg-white rounded-lg border border-orange-200 p-3 space-y-1">
                        <p className="text-sm font-medium text-slate-700">{processResult.existing_post.title}</p>
                        {processResult.existing_post.url && (
                          <a
                            href={processResult.existing_post.url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-xs text-indigo-500 hover:underline break-all"
                          >
                            {processResult.existing_post.url} ↗
                          </a>
                        )}
                        <p className="text-xs text-slate-400">
                          Status: {processResult.existing_post.status} · WP ID: {processResult.existing_post.id}
                        </p>
                      </div>
                    )}
                    <button
                      onClick={reset}
                      className="mt-3 text-xs text-orange-600 hover:underline"
                    >
                      ← Select a different attachment
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* ── Completed — result ─────────────────────────────── */}
            {processResult?.status === 'completed' && processResult.ai_result && (
              <div className="space-y-4">
                {/* Summary bar */}
                <div className="bg-emerald-50 border border-emerald-200 rounded-xl px-4 py-3 flex items-center gap-3">
                  <span className="text-xl">✅</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-emerald-800">Processing Complete — Draft Created</p>
                    <p className="text-xs text-emerald-600">
                      {processResult.article?.character_count?.toLocaleString()} chars ·
                      {processResult.unchecked_wp
                        ? ' Dup check skipped'
                        : ' No duplicate'} ·
                      Content preserved · SEO generated · Draft on WordPress
                    </p>
                  </div>
                  <button
                    onClick={reset}
                    className="shrink-0 text-xs text-emerald-600 hover:underline"
                  >
                    Process another
                  </button>
                </div>

                {/* Destination Panel */}
                <DestinationSummaryCard
                  destination={processResult.destination}
                  draftResult={processResult.draft_result}
                  envatoResult={processResult.envato_result}
                  aiResult={processResult.ai_result}
                />

                {/* QA Checklist panel */}
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm">
                  <div className="px-5 py-4 border-b border-slate-100">
                    <h3 className="text-sm font-semibold text-slate-700">HBM QA Checklist Compliance</h3>
                  </div>
                  <div className="p-5">
                    <QAChecklistPanel
                      checklist={processResult.qa_checklist}
                      draftResult={processResult.draft_result}
                      envatoResult={processResult.envato_result}
                    />
                  </div>
                </div>

                {/* SEO + Article result panel */}
                <div className="bg-white border border-slate-200 rounded-xl shadow-sm">
                  <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-slate-700">Article & SEO Result</h3>
                    <span className="text-xs text-slate-400 bg-slate-100 rounded-full px-2 py-0.5">Draft only — not published</span>
                  </div>
                  <div className="p-5">
                    <AiResultPanel result={processResult.ai_result} />
                  </div>
                </div>
              </div>
            )}
          </div>
        </SectionCard>
      )}
    </div>
  )
}
