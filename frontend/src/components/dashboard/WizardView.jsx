import { useState, useEffect, useCallback } from 'react'
import { API_BASE } from '../../config'

const STAGE_CONFIG = [
  { stage: 1, title: 'Confirm & Setup', short: 'Setup', icon: '📝' },
  { stage: 2, title: 'Inspect DOCX', short: 'DOCX', icon: '📥' },
  { stage: 3, title: 'Headings & Duplicate', short: 'Headings', icon: '🔍' },
  { stage: 4, title: 'Content & Links', short: 'Links', icon: '🔗' },
  { stage: 5, title: 'SEO Metadata', short: 'SEO', icon: '📈' },
  { stage: 6, title: 'Featured Image (Gate)', short: 'Image Gate', icon: '🖼️' },
  { stage: 7, title: 'Create Draft (Gate)', short: 'Draft Gate', icon: '🚀' },
  { stage: 8, title: 'Verify Saved Draft', short: 'Verify', icon: '✅' },
  { stage: 9, title: '10-Category QA', short: 'QA Audit', icon: '🛡️' },
]

export default function WizardView({
  projectId,
  messageId,
  attachment,
  siteId,
  destinationSite,
  onResetArticle,
}) {
  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [viewStage, setViewStage] = useState(1)

  // Stage 5 SEO form edits
  const [seoEdits, setSeoEdits] = useState({
    focus_keyphrase: '',
    seo_title: '',
    slug: '',
    meta_description: '',
    excerpt: '',
  })

  // Stage 6 image approval state
  const [imageSearchQuery, setImageSearchQuery] = useState('')
  const [selectedCandidate, setSelectedCandidate] = useState(null)
  const [imageSearching, setImageSearching] = useState(false)

  // ── Load or Restore Session from Server ───────────────────────────────────
  const fetchSession = useCallback(async () => {
    if (!projectId || !messageId || !attachment?.id) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(
        `${API_BASE}/api/wizard/session?project_id=${projectId}&message_id=${messageId}&attachment_id=${attachment.id}&site_id=${siteId || ''}`
      )
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `Failed to load wizard session (HTTP ${res.status})`)
      }
      const data = await res.json()
      setSession(data)
      setViewStage(data.current_stage || 1)

      // Initialize SEO edits if present in stage 5
      if (data.shared?.seo_fields) {
        setSeoEdits({
          focus_keyphrase: data.shared.seo_fields.focus_keyphrase || '',
          seo_title: data.shared.seo_fields.seo_title || '',
          slug: data.shared.seo_fields.slug || '',
          meta_description: data.shared.seo_fields.meta_description || '',
          excerpt: data.shared.seo_fields.excerpt || '',
        })
      }
    } catch (err) {
      setError(err.message || 'Error restoring wizard session')
    } finally {
      setLoading(false)
    }
  }, [projectId, messageId, attachment?.id, siteId])

  useEffect(() => {
    fetchSession()
  }, [fetchSession])

  // ── Advance Wizard Stage ──────────────────────────────────────────────────
  const advanceStage = async (stageNum, action = null, payload = null) => {
    setLoading(true)
    setError(null)
    try {
      const body = {
        project_id: projectId,
        message_id: messageId,
        attachment_id: String(attachment.id),
        site_id: siteId ? Number(siteId) : null,
        target_stage: stageNum,
        action,
        payload,
      }

      const res = await fetch(`${API_BASE}/api/wizard/advance`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `Stage ${stageNum} execution failed (HTTP ${res.status})`)
      }

      const data = await res.json()
      setSession(data)
      setViewStage(data.current_stage || stageNum)

      // Sync SEO edits
      if (data.shared?.seo_fields) {
        setSeoEdits({
          focus_keyphrase: data.shared.seo_fields.focus_keyphrase || '',
          seo_title: data.shared.seo_fields.seo_title || '',
          slug: data.shared.seo_fields.slug || '',
          meta_description: data.shared.seo_fields.meta_description || '',
          excerpt: data.shared.seo_fields.excerpt || '',
        })
      }
    } catch (err) {
      setError(err.message || `Failed to advance wizard stage ${stageNum}`)
    } finally {
      setLoading(false)
    }
  }

  // ── Reset Wizard ──────────────────────────────────────────────────────────
  const handleReset = async () => {
    if (!window.confirm('Reset this wizard session? All saved stage data will be cleared.')) return
    setLoading(true)
    try {
      await fetch(`${API_BASE}/api/wizard/reset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: projectId,
          message_id: messageId,
          attachment_id: String(attachment.id),
        }),
      })
      await fetchSession()
    } catch (err) {
      setError('Failed to reset session')
    } finally {
      setLoading(false)
    }
  }

  if (!attachment) {
    return (
      <div className="bg-white border border-slate-200 rounded-xl p-8 text-center text-slate-500">
        <p className="text-sm font-medium">Please select an article attachment from Panel 1 to start the Create Draft Wizard.</p>
      </div>
    )
  }

  const currentStage = session?.current_stage || 1
  const stageData = session?.stages?.[String(viewStage)]?.data
  const stageStatus = session?.stages?.[String(viewStage)]?.status || 'pending'
  const isCurrentView = viewStage === currentStage

  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-sm flex flex-col h-full overflow-hidden">
      {/* ── Wizard Header & Progress Bar ── */}
      <div className="px-5 py-3 border-b border-slate-100 bg-slate-50/70 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold uppercase tracking-wider text-indigo-700 bg-indigo-50 border border-indigo-200 px-2 py-0.5 rounded">
              9-Stage Guided Wizard
            </span>
            <span className="text-xs text-slate-500 font-medium">
              Stage {currentStage} of 9
            </span>
            {session?.created_post_id && (
              <span className="text-xs font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded">
                Draft #{session.created_post_id}
              </span>
            )}
          </div>
          <p className="text-xs text-slate-600 font-semibold truncate max-w-lg mt-0.5">
            {attachment.filename}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={fetchSession}
            disabled={loading}
            className="text-xs text-slate-500 hover:text-slate-800 border border-slate-300 bg-white px-2.5 py-1 rounded-lg font-medium transition-colors"
            title="Refresh session state from server"
          >
            ↻ Sync
          </button>
          <button
            onClick={handleReset}
            disabled={loading}
            className="text-xs text-red-600 hover:text-red-800 border border-red-200 bg-red-50 hover:bg-red-100 px-2.5 py-1 rounded-lg font-semibold transition-colors"
          >
            Reset Wizard
          </button>
        </div>
      </div>

      {/* ── 9-Stage Stepper Bar ── */}
      <div className="px-4 py-2.5 bg-slate-100/60 border-b border-slate-200 overflow-x-auto">
        <div className="flex items-center gap-1.5 min-w-max">
          {STAGE_CONFIG.map(({ stage, short, icon }) => {
            const st = session?.stages?.[String(stage)]?.status || 'pending'
            const isCompleted = st === 'completed'
            const isWaiting = st === 'waiting_for_review'
            const isFailed = st === 'failed'
            const isSelected = viewStage === stage
            const isCurrent = currentStage === stage

            let badgeClass = 'bg-slate-200 text-slate-600 border-slate-300'
            if (isCompleted) badgeClass = 'bg-emerald-100 text-emerald-800 border-emerald-300 font-bold'
            else if (isWaiting) badgeClass = 'bg-amber-100 text-amber-800 border-amber-300 font-bold animate-pulse'
            else if (isFailed) badgeClass = 'bg-red-100 text-red-800 border-red-300 font-bold'
            else if (isCurrent) badgeClass = 'bg-indigo-100 text-indigo-800 border-indigo-400 font-bold ring-2 ring-indigo-200'

            return (
              <button
                key={stage}
                onClick={() => setViewStage(stage)}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs transition-all border ${badgeClass} ${
                  isSelected ? 'ring-2 ring-indigo-500 shadow-xs' : 'opacity-90 hover:opacity-100'
                }`}
              >
                <span>{icon}</span>
                <span className="font-semibold">{stage}. {short}</span>
                {isCompleted && <span className="text-[10px] text-emerald-600">✓</span>}
                {isWaiting && <span className="text-[10px] text-amber-600 font-bold">⏸</span>}
              </button>
            )
          })}
        </div>
      </div>

      {/* ── Error Banner ── */}
      {error && (
        <div className="mx-5 mt-3 p-3 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="font-bold">⚠️ Error:</span>
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-red-500 hover:text-red-700 font-bold">✕</button>
        </div>
      )}

      {/* ── Stage Content Workspace ── */}
      <div className="p-5 flex-1 overflow-y-auto space-y-4">
        {/* Stage Header */}
        <div className="flex items-center justify-between border-b border-slate-100 pb-2.5">
          <div>
            <h3 className="text-sm font-bold text-slate-800">
              Stage {viewStage}: {STAGE_CONFIG[viewStage - 1].title}
            </h3>
            <p className="text-xs text-slate-500">
              {stageStatus === 'completed' && <span className="text-emerald-700 font-semibold">✓ Completed</span>}
              {stageStatus === 'waiting_for_review' && <span className="text-amber-700 font-semibold">⏸ Action / Approval Required</span>}
              {stageStatus === 'pending' && <span className="text-slate-400">Pending</span>}
              {stageStatus === 'failed' && <span className="text-red-600 font-semibold">✗ Failed</span>}
            </p>
          </div>

          {viewStage !== currentStage && (
            <button
              onClick={() => setViewStage(currentStage)}
              className="text-xs text-indigo-600 hover:underline font-semibold"
            >
              Go to active Stage {currentStage} →
            </button>
          )}
        </div>

        {/* ── STAGE 1: Confirm Article & Instructions ── */}
        {viewStage === 1 && (
          <div className="space-y-4 text-xs">
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-2">
              <h4 className="font-bold text-slate-700 uppercase tracking-wide text-[11px]">Selected Article Details</h4>
              <div className="grid grid-cols-2 gap-2 text-slate-600">
                <div><strong className="text-slate-700">Project:</strong> {stageData?.project_name || 'Selected Project'}</div>
                <div><strong className="text-slate-700">Message Subject:</strong> {stageData?.message_subject || 'Selected Message'}</div>
                <div><strong className="text-slate-700">DOCX File:</strong> {attachment.filename}</div>
                <div><strong className="text-slate-700">File Size:</strong> {(attachment.byte_size / 1024).toFixed(1)} KB</div>
              </div>
            </div>

            <div className="bg-indigo-50/60 border border-indigo-200 rounded-xl p-4 space-y-1.5">
              <h4 className="font-bold text-indigo-900 uppercase tracking-wide text-[11px]">Destination Safety Verification</h4>
              <p className="text-slate-700">
                Target WordPress Site: <strong className="text-indigo-800">{destinationSite?.url || 'https://espialsolutions.com'}</strong>
              </p>
              <p className="text-emerald-700 font-semibold">
                ✓ Post Status: DRAFT ONLY | Production (homebusinessmag.com) strictly isolated
              </p>
            </div>

            {session?.shared?.client_instructions_plain && (
              <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5 space-y-1">
                <span className="font-bold text-slate-700 text-[11px] uppercase">Basecamp Client Instructions</span>
                <p className="text-slate-600 max-h-32 overflow-y-auto whitespace-pre-wrap font-mono text-[11px] bg-white p-2 rounded border border-slate-200">
                  {session.shared.client_instructions_plain}
                </p>
              </div>
            )}

            <div className="pt-2">
              <button
                onClick={() => advanceStage(1)}
                disabled={loading}
                className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded-xl shadow-xs transition-colors flex items-center justify-center gap-2"
              >
                {loading ? 'Confirming...' : 'Confirm & Proceed to Stage 2 (DOCX Inspect) →'}
              </button>
            </div>
          </div>
        )}

        {/* ── STAGE 2: Download & Inspect DOCX ── */}
        {viewStage === 2 && (
          <div className="space-y-4 text-xs">
            {stageData ? (
              <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-white p-3 rounded-lg border border-slate-200">
                    <span className="text-[10px] uppercase font-bold text-slate-400 block">Character Count</span>
                    <span className="text-base font-bold text-indigo-700">{stageData.character_count?.toLocaleString()} chars</span>
                  </div>
                  <div className="bg-white p-3 rounded-lg border border-slate-200">
                    <span className="text-[10px] uppercase font-bold text-slate-400 block">File Size</span>
                    <span className="text-base font-bold text-indigo-700">{(stageData.byte_size / 1024).toFixed(1)} KB</span>
                  </div>
                </div>
                <div className="bg-white p-3 rounded-lg border border-slate-200 space-y-1">
                  <span className="text-[10px] uppercase font-bold text-slate-400 block">Local Backup Location</span>
                  <code className="text-[11px] text-slate-700 break-all">{stageData.backup_path}</code>
                </div>
              </div>
            ) : (
              <p className="text-slate-500">Ready to download and inspect the DOCX file.</p>
            )}

            <div className="pt-2">
              <button
                onClick={() => advanceStage(2)}
                disabled={loading}
                className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded-xl shadow-xs transition-colors"
              >
                {loading ? 'Inspecting DOCX...' : 'Inspect DOCX & Proceed to Stage 3 (Headings & Duplicate Check) →'}
              </button>
            </div>
          </div>
        )}

        {/* ── STAGE 3: Headings & Duplicate Check ── */}
        {viewStage === 3 && (
          <div className="space-y-4 text-xs">
            {stageData ? (
              <div className="space-y-3">
                <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5 space-y-1">
                  <span className="text-[10px] uppercase font-bold text-slate-400 block">Extracted Article Title</span>
                  <span className="text-sm font-bold text-slate-800">{stageData.article_title}</span>
                </div>

                <div className="grid grid-cols-4 gap-2 text-center">
                  <div className="bg-slate-50 border border-slate-200 p-2 rounded-lg">
                    <span className="text-[10px] text-slate-500 uppercase block">H1</span>
                    <span className="font-bold text-slate-800">{stageData.headings_count?.h1 || 0}</span>
                  </div>
                  <div className="bg-slate-50 border border-slate-200 p-2 rounded-lg">
                    <span className="text-[10px] text-slate-500 uppercase block">H2</span>
                    <span className="font-bold text-slate-800">{stageData.headings_count?.h2 || 0}</span>
                  </div>
                  <div className="bg-slate-50 border border-slate-200 p-2 rounded-lg">
                    <span className="text-[10px] text-slate-500 uppercase block">H3</span>
                    <span className="font-bold text-slate-800">{stageData.headings_count?.h3 || 0}</span>
                  </div>
                  <div className="bg-slate-50 border border-slate-200 p-2 rounded-lg">
                    <span className="text-[10px] text-slate-500 uppercase block">Images</span>
                    <span className="font-bold text-slate-800">{stageData.embedded_images_count || 0}</span>
                  </div>
                </div>

                {stageData.duplicate_check?.duplicate ? (
                  <div className="p-3 bg-amber-50 border border-amber-300 rounded-xl text-amber-900 space-y-1">
                    <span className="font-bold block">⚠️ Duplicate Found on Destination Site</span>
                    <p>Post #{stageData.duplicate_check.existing_post?.id}: {stageData.duplicate_check.existing_post?.title}</p>
                  </div>
                ) : (
                  <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-xl text-emerald-800 font-semibold">
                    ✓ Duplicate Check Passed: No matching post found on test WordPress site.
                  </div>
                )}
              </div>
            ) : (
              <p className="text-slate-500">Ready to extract headings and check duplicates.</p>
            )}

            <div className="pt-2">
              <button
                onClick={() => advanceStage(3)}
                disabled={loading}
                className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded-xl shadow-xs transition-colors"
              >
                {loading ? 'Checking...' : 'Extract Content & Proceed to Stage 4 (Review Links) →'}
              </button>
            </div>
          </div>
        )}

        {/* ── STAGE 4: Review Content & Links ── */}
        {viewStage === 4 && (
          <div className="space-y-4 text-xs">
            {stageData ? (
              <div className="space-y-3">
                {/* Internal Links Table */}
                <div className="border border-slate-200 rounded-xl p-3 bg-slate-50 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-slate-800 text-[11px] uppercase">
                      Internal Links ({stageData.internal_links?.length || 0})
                    </span>
                    <span className="text-[10px] text-slate-500 font-semibold">Rule: 3–5 words anchor</span>
                  </div>
                  {stageData.internal_links?.length > 0 ? (
                    <div className="space-y-1.5">
                      {stageData.internal_links.map((l, i) => (
                        <div key={i} className="bg-white p-2 rounded border border-slate-200 flex justify-between items-center">
                          <div className="truncate mr-2">
                            <span className="font-semibold text-slate-800">"{l.anchor}"</span>
                            <span className="text-slate-400 ml-1">({l.word_count} words)</span>
                            <p className="text-[10px] text-slate-400 truncate">{l.url}</p>
                          </div>
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${l.is_compliant ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-800'}`}>
                            {l.is_compliant ? 'COMPLIANT (3-5 words)' : 'NON-COMPLIANT'}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-slate-400 italic">No internal homebusinessmag.com links found.</p>
                  )}
                </div>

                {/* Authority Links Table */}
                <div className="border border-slate-200 rounded-xl p-3 bg-slate-50 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-slate-800 text-[11px] uppercase">
                      Authority Links ({stageData.authority_links?.length || 0})
                    </span>
                    <span className="text-[10px] text-slate-500 font-semibold">Rule: 3–4 words anchor</span>
                  </div>
                  {stageData.authority_links?.length > 0 ? (
                    <div className="space-y-1.5">
                      {stageData.authority_links.map((l, i) => (
                        <div key={i} className="bg-white p-2 rounded border border-slate-200 flex justify-between items-center">
                          <div className="truncate mr-2">
                            <span className="font-semibold text-slate-800">"{l.anchor}"</span>
                            <span className="text-slate-400 ml-1">({l.word_count} words)</span>
                            <p className="text-[10px] text-slate-400 truncate">{l.url}</p>
                          </div>
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${l.is_compliant ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-800'}`}>
                            {l.is_compliant ? 'COMPLIANT (3-4 words)' : 'NON-COMPLIANT'}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-slate-400 italic">No approved authority domain links detected.</p>
                  )}
                </div>
              </div>
            ) : (
              <p className="text-slate-500">Ready to audit content and link compliance.</p>
            )}

            <div className="pt-2">
              <button
                onClick={() => advanceStage(4)}
                disabled={loading}
                className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded-xl shadow-xs transition-colors"
              >
                {loading ? 'Auditing Links...' : 'Approve Content & Proceed to Stage 5 (SEO Metadata) →'}
              </button>
            </div>
          </div>
        )}

        {/* ── STAGE 5: SEO Metadata Review & Editor ── */}
        {viewStage === 5 && (
          <div className="space-y-4 text-xs">
            <div className="space-y-3 bg-slate-50 border border-slate-200 rounded-xl p-4">
              <div>
                <label className="block text-[10px] font-bold uppercase text-slate-600 mb-1">Focus Keyphrase</label>
                <input
                  type="text"
                  value={seoEdits.focus_keyphrase}
                  onChange={e => setSeoEdits(prev => ({ ...prev, focus_keyphrase: e.target.value }))}
                  className="w-full border border-slate-300 rounded-lg p-2 bg-white text-xs font-semibold text-slate-800"
                />
              </div>

              <div>
                <label className="block text-[10px] font-bold uppercase text-slate-600 mb-1">SEO Title</label>
                <input
                  type="text"
                  value={seoEdits.seo_title}
                  onChange={e => setSeoEdits(prev => ({ ...prev, seo_title: e.target.value }))}
                  className="w-full border border-slate-300 rounded-lg p-2 bg-white text-xs text-slate-800"
                />
              </div>

              <div>
                <label className="block text-[10px] font-bold uppercase text-slate-600 mb-1">Slug</label>
                <input
                  type="text"
                  value={seoEdits.slug}
                  onChange={e => setSeoEdits(prev => ({ ...prev, slug: e.target.value }))}
                  className="w-full border border-slate-300 rounded-lg p-2 bg-white text-xs font-mono text-slate-800"
                />
              </div>

              <div>
                <div className="flex justify-between items-center mb-1">
                  <label className="text-[10px] font-bold uppercase text-slate-600">Meta Description</label>
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                    seoEdits.meta_description.length >= 140 && seoEdits.meta_description.length <= 155
                      ? 'bg-emerald-100 text-emerald-800'
                      : 'bg-amber-100 text-amber-800'
                  }`}>
                    {seoEdits.meta_description.length} / 140–155 chars
                  </span>
                </div>
                <textarea
                  rows={3}
                  value={seoEdits.meta_description}
                  onChange={e => setSeoEdits(prev => ({ ...prev, meta_description: e.target.value }))}
                  className="w-full border border-slate-300 rounded-lg p-2 bg-white text-xs text-slate-800"
                />
              </div>

              <div>
                <label className="block text-[10px] font-bold uppercase text-slate-600 mb-1">Excerpt</label>
                <textarea
                  rows={2}
                  value={seoEdits.excerpt}
                  onChange={e => setSeoEdits(prev => ({ ...prev, excerpt: e.target.value }))}
                  className="w-full border border-slate-300 rounded-lg p-2 bg-white text-xs text-slate-800"
                />
              </div>
            </div>

            <div className="pt-2">
              <button
                onClick={() => advanceStage(5, 'save_seo', { seo_fields: seoEdits })}
                disabled={loading}
                className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded-xl shadow-xs transition-colors"
              >
                {loading ? 'Saving SEO...' : 'Approve SEO & Proceed to Stage 6 (Image Approval Gate) →'}
              </button>
            </div>
          </div>
        )}

        {/* ── STAGE 6: Manual Featured-Image Selection & Approval Gate ── */}
        {viewStage === 6 && (
          <div className="space-y-4 text-xs">
            <div className="bg-amber-50 border border-amber-300 rounded-xl p-3.5 text-amber-900 space-y-1">
              <span className="font-bold block flex items-center gap-1.5 text-sm">
                <span>⏸</span>
                <span>Genuine Approval Gate: Featured Image Review</span>
              </span>
              <p className="text-[11px]">
                No image will be uploaded to WordPress until you select a candidate and explicitly click <strong>Approve Selected Image</strong>.
              </p>
            </div>

            {/* Candidate Gallery */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-bold text-slate-800 uppercase text-[11px]">
                  Available Image Candidates ({stageData?.candidates?.length || 0})
                </span>
                <span className="text-[10px] text-slate-500">1000×667 px banner required</span>
              </div>

              {stageData?.candidates?.length > 0 ? (
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  {stageData.candidates.map((cand, idx) => {
                    const isSelected = selectedCandidate?.filename === cand.filename || (stageData.approved && session?.shared?.approved_image?.filename === cand.filename)
                    return (
                      <div
                        key={idx}
                        onClick={() => setSelectedCandidate(cand)}
                        className={`cursor-pointer rounded-xl border p-2 bg-white space-y-1.5 transition-all ${
                          isSelected ? 'border-indigo-600 ring-2 ring-indigo-300 shadow-sm' : 'border-slate-200 hover:border-slate-300'
                        }`}
                      >
                        <img
                          src={cand.thumbnail_url || cand.preview_url}
                          alt={cand.label}
                          className="w-full h-24 object-cover rounded-lg bg-slate-100"
                        />
                        <div className="text-[10px]">
                          <span className="font-bold text-slate-700 block truncate">{cand.label}</span>
                          <span className="text-slate-400 block truncate">{cand.credit_text || 'Envato'}</span>
                        </div>
                        {isSelected && (
                          <div className="text-center bg-indigo-50 text-indigo-700 font-bold text-[10px] py-0.5 rounded">
                            ✓ Selected
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              ) : (
                <p className="text-slate-500 py-3 text-center">Click Gather Candidates to load image choices.</p>
              )}
            </div>

            {/* Approval Action */}
            <div className="pt-2 flex gap-2">
              <button
                onClick={() => advanceStage(6, 'gather_candidates', { search_query: imageSearchQuery })}
                disabled={loading}
                className="px-4 py-2.5 border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 font-bold rounded-xl shadow-xs transition-colors"
              >
                ↻ Re-scan Candidates
              </button>
              <button
                onClick={() => {
                  if (!selectedCandidate && !stageData?.candidates?.[0]) {
                    alert('Please click on an image candidate to select it before approving.')
                    return
                  }
                  advanceStage(6, 'approve_image', {
                    selected_image: selectedCandidate || stageData?.candidates?.[0],
                  })
                }}
                disabled={loading || (!selectedCandidate && !stageData?.candidates?.[0])}
                className="flex-1 py-2.5 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-300 text-white font-bold rounded-xl shadow-xs transition-colors"
              >
                {loading ? 'Approving Image...' : '✓ Approve Selected Image & Unlock Stage 7 →'}
              </button>
            </div>
          </div>
        )}

        {/* ── STAGE 7: WordPress Draft Creation Gate ── */}
        {viewStage === 7 && (
          <div className="space-y-4 text-xs">
            <div className="bg-indigo-50 border border-indigo-300 rounded-xl p-4 text-indigo-950 space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-lg">🛡️</span>
                <div>
                  <h4 className="font-bold text-sm">Genuine Draft Creation Gateway</h4>
                  <p className="text-[11px] text-indigo-800">
                    Draft will be created strictly on <strong>https://espialsolutions.com</strong> under <strong>draft</strong> status.
                  </p>
                </div>
              </div>
              <div className="p-2.5 bg-white/80 rounded-lg border border-indigo-200 text-[11px] space-y-1">
                <div><strong>Production Protection:</strong> homebusinessmag.com is completely isolated with zero write requests.</div>
                <div><strong>Idempotency Guard:</strong> Active — retry requests reuse existing draft to prevent duplicates.</div>
                {session?.created_post_id && (
                  <div className="text-emerald-700 font-bold">✓ Draft already created: Post #{session.created_post_id}</div>
                )}
              </div>
            </div>

            <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-2">
              <span className="font-bold text-slate-700 uppercase text-[11px] block">Approved Draft Payload Summary</span>
              <div className="grid grid-cols-2 gap-2 text-slate-600 text-[11px]">
                <div><strong className="text-slate-700">Title:</strong> {session?.shared?.article_title || 'Untitled'}</div>
                <div><strong className="text-slate-700">Author:</strong> {session?.shared?.parsed_instructions?.author || 'Richard Henderson'}</div>
                <div><strong className="text-slate-700">Keyphrase:</strong> {session?.shared?.seo_fields?.focus_keyphrase || '—'}</div>
                <div><strong className="text-slate-700">Approved Image:</strong> {session?.shared?.approved_image?.filename || 'None'}</div>
              </div>
            </div>

            <div className="pt-2">
              <button
                onClick={() => advanceStage(7, 'create_draft')}
                disabled={loading}
                className="w-full py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-sm rounded-xl shadow-sm transition-all flex items-center justify-center gap-2"
              >
                {loading ? 'Creating WordPress Draft on Test Site...' : '🚀 Create WordPress Draft on Test Site (Post Status: draft) →'}
              </button>
            </div>
          </div>
        )}

        {/* ── STAGE 8: Verify Saved WordPress Draft ── */}
        {viewStage === 8 && (
          <div className="space-y-4 text-xs">
            {stageData ? (
              <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-3">
                <div className="flex items-center justify-between pb-2 border-b border-slate-200">
                  <span className="font-bold text-emerald-800 text-sm flex items-center gap-1.5">
                    <span>✓</span> Verified Draft #{stageData.post_id}
                  </span>
                  <span className="font-bold uppercase text-emerald-800 bg-emerald-100 border border-emerald-300 px-2.5 py-0.5 rounded-full">
                    {stageData.post_status}
                  </span>
                </div>

                <div className="space-y-1.5 text-slate-700">
                  <div><strong>Title:</strong> {stageData.post_title}</div>
                  <div><strong>Featured Media ID:</strong> #{stageData.featured_media_id}</div>
                  <div><strong>Focus Keyphrase:</strong> {stageData.yoast_meta?.focus_keyphrase || '—'}</div>
                </div>

                {stageData.edit_url && (
                  <div className="pt-2">
                    <a
                      href={stageData.edit_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center justify-center w-full px-4 py-2.5 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200 font-bold rounded-xl transition-colors gap-1.5"
                    >
                      <span>Open WordPress Draft in WP-Admin</span>
                      <span>↗</span>
                    </a>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-slate-500">Ready to verify the saved WordPress draft.</p>
            )}

            <div className="pt-2">
              <button
                onClick={() => advanceStage(8)}
                disabled={loading}
                className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded-xl shadow-xs transition-colors"
              >
                {loading ? 'Verifying Draft...' : 'Verify Draft & Proceed to Stage 9 (10-Category QA Audit) →'}
              </button>
            </div>
          </div>
        )}

        {/* ── STAGE 9: Authoritative 10-Category Read-Only QA Checklist ── */}
        {viewStage === 9 && (
          <div className="space-y-4 text-xs">
            {stageData ? (
              <div className="space-y-3">
                {/* Overall Verdict Banner */}
                <div className={`p-4 rounded-xl border flex items-center justify-between ${
                  stageData.verdict === 'PASS'
                    ? 'bg-emerald-50 border-emerald-300 text-emerald-900'
                    : stageData.verdict === 'WARNING'
                    ? 'bg-amber-50 border-amber-300 text-amber-900'
                    : 'bg-red-50 border-red-300 text-red-900'
                }`}>
                  <div>
                    <span className="text-[10px] font-bold uppercase tracking-wider block">QA Final Verdict</span>
                    <span className="text-base font-bold">{stageData.verdict}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-[11px] block">{stageData.counts?.pass || 0} PASS | {stageData.counts?.fail || 0} FAIL</span>
                    <span className="text-[10px] text-slate-500">{stageData.counts?.not_applicable || 0} N/A | {stageData.counts?.warning || 0} WARNING</span>
                  </div>
                </div>

                {/* Categories Accordion */}
                <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
                  {stageData.categories && Object.entries(stageData.categories).map(([catKey, cat]) => (
                    <div key={catKey} className="bg-slate-50 border border-slate-200 rounded-lg p-2.5 space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-slate-800 text-[11px]">{cat.title}</span>
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                          cat.status === 'PASS' ? 'bg-emerald-100 text-emerald-800' :
                          cat.status === 'FAIL' ? 'bg-red-100 text-red-800' :
                          cat.status === 'WARNING' ? 'bg-amber-100 text-amber-800' : 'bg-slate-200 text-slate-600'
                        }`}>
                          {cat.status}
                        </span>
                      </div>
                      <p className="text-[10px] text-slate-500">{cat.summary}</p>
                    </div>
                  ))}
                </div>

                <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-3 text-emerald-800 text-center font-medium">
                  ✓ Workflow Report saved server-side in persistent database.
                </div>
              </div>
            ) : (
              <p className="text-slate-500">Ready to execute authoritative 10-category QA analysis.</p>
            )}

            <div className="pt-2">
              <button
                onClick={() => advanceStage(9)}
                disabled={loading}
                className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded-xl shadow-xs transition-colors"
              >
                {loading ? 'Running 10-Category QA Audit...' : 'Run Authoritative 10-Category QA Audit →'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
