import React from 'react'

export const PIPELINE_STEPS = [
  { key: 'basecamp', label: 'Basecamp', implemented: true },
  { key: 'instructions', label: 'Instructions', implemented: true },
  { key: 'docx', label: 'DOCX', implemented: true },
  { key: 'duplicate', label: 'Duplicate', implemented: true },
  { key: 'seo', label: 'SEO', implemented: false },
  { key: 'envato', label: 'Envato', implemented: false },
  { key: 'wp', label: 'WordPress Draft', implemented: false },
  { key: 'qa', label: 'QA', implemented: false },
]

export default function ProcessingPipeline({
  activeStep,
  processResult,
  processError,
  processing,
  selectedAttachment,
  selectedProject,
  onProcess
}) {
  const activeIdx = PIPELINE_STEPS.findIndex(s => s.key === activeStep)
  // If activeIdx is -1 and processResult is present, it might mean we are fully done or error'd out before starting properly.
  // Actually, we manage activeStep tightly in Dashboard.jsx.

  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-sm flex flex-col min-h-0 overflow-hidden">
      {/* Panel Header */}
      <div className="px-4 py-3 border-b border-slate-100 bg-slate-50 shrink-0 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
          <span>⚙️</span> 2. Processing Status
        </h2>
        {selectedAttachment && !processing && (
          <button 
            onClick={onProcess}
            className="px-3 py-1 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium rounded transition-colors shadow-sm"
          >
            Start Processing
          </button>
        )}
        {processing && (
          <span className="text-xs font-semibold text-indigo-600 bg-indigo-50 px-2 py-1 rounded animate-pulse">
            Processing...
          </span>
        )}
      </div>
      
      <div className="p-4 overflow-y-auto flex-1 space-y-6">
        {/* Current Article Info */}
        {selectedAttachment ? (
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs shadow-sm">
            <p className="font-semibold text-slate-800 mb-1.5 uppercase tracking-wide text-[10px]">Current Article</p>
            <div className="space-y-1 text-slate-600">
              <p className="truncate" title={selectedAttachment.filename}>
                <span className="font-medium text-slate-500">File:</span> {selectedAttachment.filename}
              </p>
              <p className="truncate" title={selectedProject?.name}>
                <span className="font-medium text-slate-500">Project:</span> {selectedProject?.name}
              </p>
            </div>
          </div>
        ) : (
          <div className="bg-slate-50 border border-slate-200 border-dashed rounded-lg p-3 text-xs text-slate-400 text-center">
            Select an article from Basecamp to begin
          </div>
        )}

        {/* Pipeline Diagram */}
        <div className="relative pl-1">
          {/* Vertical line connecting steps */}
          <div className="absolute left-[15px] top-4 bottom-4 w-[2px] bg-slate-100 -z-10" />
          
          <div className="space-y-4">
            {PIPELINE_STEPS.map((step, i) => {
              const isDone = activeIdx !== -1 && i < activeIdx
              const isActive = i === activeIdx
              const isError = isActive && !!processError
              const isStoppedByDuplicate = isActive && processResult?.status === 'duplicate' && step.key === 'duplicate'

              let circleClasses = 'w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-all shrink-0 '
              if (!step.implemented) {
                circleClasses += 'bg-slate-50 border-slate-200 text-slate-300'
              } else if (isDone || (isActive && processResult && !isError && !isStoppedByDuplicate)) {
                circleClasses += 'bg-emerald-500 border-emerald-500 text-white shadow-sm'
              } else if (isStoppedByDuplicate) {
                circleClasses += 'bg-orange-500 border-orange-500 text-white shadow-sm'
              } else if (isError) {
                circleClasses += 'bg-red-500 border-red-500 text-white shadow-sm'
              } else if (isActive) {
                circleClasses += 'bg-indigo-600 border-indigo-600 text-white shadow-md ring-4 ring-indigo-50 animate-pulse'
              } else {
                circleClasses += 'bg-white border-slate-300 text-slate-400'
              }

              let textClasses = 'text-sm font-medium '
              if (!step.implemented) textClasses += 'text-slate-400'
              else if (isDone || (isActive && processResult && !isError && !isStoppedByDuplicate)) textClasses += 'text-emerald-700'
              else if (isStoppedByDuplicate) textClasses += 'text-orange-700'
              else if (isError) textClasses += 'text-red-600'
              else if (isActive) textClasses += 'text-indigo-700 font-bold'
              else textClasses += 'text-slate-500'

              return (
                <div key={step.key} className="flex items-center gap-4 relative group">
                  <div className={circleClasses}>
                    {!step.implemented ? '—' : 
                     (isDone || (isActive && processResult && !isError && !isStoppedByDuplicate)) ? '✓' : 
                     isStoppedByDuplicate ? '!' :
                     isError ? '✕' : 
                     i + 1}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className={textClasses}>{step.label}</span>
                      {/* Status Badges */}
                      {!step.implemented && (
                        <span className="text-[10px] uppercase font-bold text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded">Pending</span>
                      )}
                      {step.implemented && (isDone || (isActive && processResult && !isError && !isStoppedByDuplicate)) && (
                        <span className="text-[10px] uppercase font-bold text-emerald-600 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded">Passed</span>
                      )}
                      {step.implemented && isStoppedByDuplicate && (
                        <span className="text-[10px] uppercase font-bold text-orange-700 bg-orange-100 border border-orange-200 px-1.5 py-0.5 rounded">Skipped (Duplicate)</span>
                      )}
                      {step.implemented && isError && (
                        <span className="text-[10px] uppercase font-bold text-red-600 bg-red-50 border border-red-200 px-1.5 py-0.5 rounded">Failed</span>
                      )}
                      {step.implemented && isActive && processing && (
                        <span className="text-[10px] uppercase font-bold text-indigo-600 bg-indigo-50 border border-indigo-200 px-1.5 py-0.5 rounded">Processing</span>
                      )}
                    </div>

                    {/* Active State Subtext */}
                    {isActive && processing && <p className="text-xs text-indigo-500 mt-1">Running...</p>}
                    
                    {isStoppedByDuplicate && (
                       <p className="text-xs text-orange-700 mt-1.5 font-medium bg-orange-50 px-2 py-1.5 rounded border border-orange-100 inline-block">Duplicate found. Pipeline stopped.</p>
                    )}
                    {isError && (
                      <p className="text-xs text-red-600 mt-1.5 font-medium bg-red-50 px-2 py-1.5 rounded border border-red-100">{processError}</p>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>

      </div>
    </div>
  )
}
