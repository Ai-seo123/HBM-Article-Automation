import React from 'react'

export function Spinner({ label }) {
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

function formatBytes(bytes) {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function BasecampPanel({
  connected,
  connChecked,
  projects,
  projectsLoading,
  selectedProject,
  onSelectProject,
  messages,
  messagesLoading,
  selectedMessage,
  onSelectMessage,
  msgDetail,
  detailLoading,
  docxAttachments,
  selectedAttachment,
  onSelectAttachment,
  onConnect,
  onDisconnect,
  actionLoading
}) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-sm flex flex-col min-h-0 overflow-hidden">
      {/* Panel Header */}
      <div className="px-4 py-3 border-b border-slate-100 bg-slate-50 shrink-0">
        <h2 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
          <span>🏕️</span> 1. Basecamp Source
        </h2>
      </div>

      <div className="p-4 overflow-y-auto flex-1 space-y-5 text-sm">
        {/* Basecamp Connection */}
        <div className="space-y-3 pb-4 border-b border-slate-100">
          <div className="flex items-center justify-between">
             <div className="flex items-center gap-2">
               {connChecked ? (
                 <>
                   <div className={`w-2.5 h-2.5 rounded-full ${connected ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                   <span className="font-semibold text-slate-700">
                     {connected ? 'Basecamp Connected' : 'Basecamp Not Connected'}
                   </span>
                 </>
               ) : (
                 <Spinner label="Checking connection..." />
               )}
             </div>
             {connected && (
               <button 
                 onClick={onDisconnect}
                 disabled={actionLoading}
                 className="text-xs text-red-600 hover:text-red-700 hover:bg-red-50 px-2 py-1 rounded transition-colors disabled:opacity-50"
               >
                 Disconnect
               </button>
             )}
          </div>
          
          {!connected && connChecked && (
            <button
              onClick={onConnect}
              disabled={actionLoading}
              className="w-full py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
            >
              Connect Basecamp
            </button>
          )}
          {connected && (
             <button
              onClick={onConnect}
              disabled={actionLoading}
              className="w-full py-2 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
            >
              Reconnect Basecamp
            </button>
          )}
        </div>

        {connected && (
          <>
            {/* Project Selector */}
            <div className="space-y-2">
              <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Project</label>
              {projectsLoading ? <Spinner label="Loading projects..." /> : (
                <select 
                  className="w-full border border-slate-200 rounded-lg p-2 bg-white text-slate-700"
                  value={selectedProject?.id || ''}
                  onChange={e => {
                    const p = projects.find(x => String(x.id) === e.target.value)
                    onSelectProject(p || null)
                  }}
                >
                  <option value="">-- Select Project --</option>
                  {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              )}
            </div>

            {/* Message / Article Selector */}
            {selectedProject && (
              <div className="space-y-2">
                <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Messages / Articles</label>
                {messagesLoading ? <Spinner label="Loading messages..." /> : (
                  <select 
                    className="w-full border border-slate-200 rounded-lg p-2 bg-white text-slate-700"
                    value={selectedMessage?.id || ''}
                    onChange={e => {
                      const m = messages.find(x => String(x.id) === e.target.value)
                      onSelectMessage(m || null)
                    }}
                  >
                    <option value="">-- Select Message --</option>
                    {messages.map(m => (
                      <option key={m.id} value={m.id}>
                        {(m.subject || '(No subject)').replace(/\s*\(📎\s*\d+\)/g, '').trim()}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )}

            {/* Client Instructions */}
            {selectedMessage && (
              <div className="space-y-2">
                <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Client Instructions</label>
                {detailLoading ? <Spinner label="Loading details..." /> : (
                  <div className="bg-slate-50 p-3 rounded-lg border border-slate-100 max-h-32 overflow-y-auto">
                     <div
                        className="prose prose-sm max-w-none text-slate-600 text-xs"
                        dangerouslySetInnerHTML={{ __html: msgDetail?.content || '<em>No instructions provided</em>' }}
                      />
                  </div>
                )}
              </div>
            )}

            {/* DOCX Attachment & Selected Article */}
            {selectedMessage && msgDetail && (
               <div className="space-y-2">
                 <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">DOCX Attachment</label>
                 {docxAttachments.length === 0 ? (
                   <p className="text-xs text-amber-600 bg-amber-50 px-3 py-2 rounded-lg border border-amber-200">No .docx attachments found in this message.</p>
                 ) : (
                    <div className="space-y-1">
                      {docxAttachments.map(att => (
                        <button
                          key={att.id}
                          onClick={() => onSelectAttachment(att)}
                          className={[
                            'w-full text-left flex items-center justify-between px-3 py-2 rounded-lg border text-xs transition-all relative overflow-hidden',
                            selectedAttachment?.id === att.id ? 'border-indigo-400 bg-indigo-50 ring-1 ring-indigo-200' : 'border-slate-200 hover:bg-slate-50 text-slate-600'
                          ].join(' ')}
                        >
                          <div className="flex items-center gap-2 truncate">
                            <span className="text-base shrink-0">📄</span>
                            <span className={`truncate font-medium ${selectedAttachment?.id === att.id ? 'text-indigo-800' : ''}`}>{att.filename}</span>
                          </div>
                          <span className="text-slate-400 shrink-0 ml-2">{formatBytes(att.byte_size)}</span>
                          
                          {/* Selected Indicator */}
                          {selectedAttachment?.id === att.id && (
                             <div className="absolute left-0 top-0 bottom-0 w-1 bg-indigo-500"></div>
                          )}
                        </button>
                      ))}
                    </div>
                 )}
               </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
