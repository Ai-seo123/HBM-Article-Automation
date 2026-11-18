import React from 'react'

export default function DestinationPanel({ processResult }) {
  const destination = processResult?.destination || {}
  const draftData = processResult?.draft_result?.data || {}
  const envatoData = processResult?.envato_result?.data || {}
  const aiResult = processResult?.ai_result || {}

  const postTitle = destination.title || aiResult.title || 'Untitled'
  
  const primaryCat = 
    (destination.primary_category && destination.primary_category !== 'Uncategorized')
      ? destination.primary_category
      : draftData.category_primary || 
        (draftData.category_names && draftData.category_names[0]) ||
        destination.primary_category || 
        'Uncategorized'

  const allCats = 
    (destination.all_categories && destination.all_categories.length > 0 && destination.all_categories[0] !== 'Uncategorized')
      ? destination.all_categories
      : (draftData.category_names && draftData.category_names.length > 0)
        ? draftData.category_names
        : (destination.all_categories && destination.all_categories.length > 0)
          ? destination.all_categories
          : (primaryCat && primaryCat !== 'Uncategorized' ? [primaryCat] : ['Uncategorized'])

  const authorName = destination.author || 'Home Office Editor'
  const draftStatus = destination.status || draftData.status_value || 'draft'
  const postId = destination.post_id || draftData.post_id
  const draftUrl = destination.url || draftData.url
  const mediaId = destination.featured_media_id || draftData.featured_media || envatoData.wordpress_media?.media_id
  const imageSource = destination.image_source || (envatoData.source === 'pexels' ? 'Pexels (from instructions)' : envatoData.source === 'docx' ? 'DOCX embedded image' : 'Envato')
  const imageDimensions = destination.image_dimensions || '1000 × 667 px'
  const imageSourceUrl = destination.image_source_url || envatoData.source_url

  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-sm flex flex-col min-h-0 overflow-hidden relative">
      {/* Panel Header */}
      <div className="px-4 py-3 border-b border-slate-100 bg-slate-50 shrink-0 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
          <span>🔷</span> 3. Destination
        </h2>
        {/* Environment Badge */}
        <span className="text-[10px] font-bold tracking-widest uppercase px-2 py-1 bg-amber-100 text-amber-800 rounded shadow-sm border border-amber-300">
          TEST ENV
        </span>
      </div>
      
      <div className="p-5 overflow-y-auto flex-1 flex flex-col space-y-5">
        {/* Environment Config Info */}
        <div className="pb-4 border-b border-slate-100 space-y-2">
           <h3 className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">WordPress Configuration</h3>
           <div className="text-xs text-slate-700 space-y-1.5">
             <div className="flex items-center gap-2">
               <div className="w-1.5 h-1.5 rounded-full bg-emerald-500"></div>
               <p><span className="text-slate-500 font-medium">Site URL:</span> <a href="https://espialsolutions.com" target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline font-medium">https://espialsolutions.com</a></p>
             </div>
             <div className="flex items-center gap-2">
               <div className="w-1.5 h-1.5 rounded-full bg-amber-500"></div>
               <p><span className="text-slate-500 font-medium">Target:</span> <span className="font-semibold text-amber-700 uppercase">Drafts Only (Safe Mode)</span></p>
             </div>
           </div>
        </div>

        {/* Duplicate State */}
        {processResult?.status === 'duplicate' && processResult.existing_post && (
           <div className="bg-orange-50 border border-orange-200 rounded-xl p-4 text-sm shadow-sm">
             <h4 className="font-semibold text-orange-900 mb-1 flex items-center gap-2">
               <span className="text-lg">⚠️</span> Duplicate Draft Exists
             </h4>
             <p className="text-orange-800 mb-3 text-xs">An article with matching title already exists in WordPress.</p>
             <div className="bg-white p-3 rounded-lg border border-orange-100 shadow-sm space-y-1.5">
               <p className="font-medium text-slate-800 text-xs">{processResult.existing_post.title}</p>
               <div className="flex flex-wrap gap-2 text-xs text-slate-500">
                 <span>Status: <strong className="uppercase text-slate-700">{processResult.existing_post.status}</strong></span>
                 <span>·</span>
                 <span>WP ID: <strong className="text-slate-700">{processResult.existing_post.id}</strong></span>
               </div>
               
               {processResult.existing_post.url && (
                 <div className="mt-2 pt-2 border-t border-orange-50">
                   <a 
                     href={processResult.existing_post.url} 
                     target="_blank" 
                     rel="noreferrer" 
                     className="inline-flex items-center justify-center w-full px-3 py-1.5 bg-orange-100 hover:bg-orange-200 text-orange-800 rounded text-xs font-medium transition-colors"
                   >
                     Open Existing WP Post ↗
                   </a>
                 </div>
               )}
             </div>
           </div>
        )}

        {/* Processed/Draft State */}
        {processResult?.status === 'completed' && (
          <div className="space-y-4 flex-1">
            <div className="flex items-center justify-between">
              <h4 className="font-semibold text-slate-800 text-sm flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-500"></span> Draft Created Successfully
              </h4>
              <span className="text-[10px] font-bold uppercase tracking-wider bg-emerald-100 text-emerald-800 px-2 py-0.5 rounded-full border border-emerald-200">
                {draftStatus}
              </span>
            </div>
            
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 text-xs space-y-3 shadow-sm">
              <div>
                <p className="font-bold uppercase tracking-wider text-slate-400 mb-0.5">Draft Title</p>
                <p className="font-semibold text-slate-800 text-sm">{postTitle}</p>
              </div>

              <div className="grid grid-cols-2 gap-3 pt-2 border-t border-slate-200">
                <div>
                  <p className="font-bold uppercase tracking-wider text-slate-400 mb-0.5">Primary Category</p>
                  <p className="font-medium text-indigo-700 bg-indigo-50 border border-indigo-200 px-2 py-1 rounded inline-block">
                    {primaryCat}
                  </p>
                </div>
                <div>
                  <p className="font-bold uppercase tracking-wider text-slate-400 mb-0.5">All Categories</p>
                  <div className="flex flex-wrap gap-1 mt-0.5">
                    {allCats.map((c, i) => (
                      <span key={i} className="bg-white border border-slate-200 px-1.5 py-0.5 rounded text-slate-700 font-medium text-[11px]">
                        {c}
                      </span>
                    ))}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 pt-2 border-t border-slate-200">
                <div>
                  <p className="font-bold uppercase tracking-wider text-slate-400 mb-0.5">Assigned Author</p>
                  <p className="font-medium text-slate-800 bg-white border border-slate-200 px-2 py-1 rounded">
                    👤 {authorName}
                  </p>
                </div>
                <div>
                  <p className="font-bold uppercase tracking-wider text-slate-400 mb-0.5">WordPress Post ID</p>
                  <p className="font-mono text-slate-700 bg-white border border-slate-200 px-2 py-1 rounded">
                    #{postId || '—'}
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 pt-2 border-t border-slate-200">
                <div>
                  <p className="font-bold uppercase tracking-wider text-slate-400 mb-0.5">Featured Media ID</p>
                  <p className="font-mono text-slate-700 bg-white border border-slate-200 px-2 py-1 rounded">
                    🖼️ #{mediaId || '—'}
                  </p>
                </div>
                <div>
                  <p className="font-bold uppercase tracking-wider text-slate-400 mb-0.5">Image Dimensions</p>
                  <p className="font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-1 rounded">
                    ✓ {imageDimensions}
                  </p>
                </div>
              </div>

              <div className="pt-2 border-t border-slate-200">
                <p className="font-bold uppercase tracking-wider text-slate-400 mb-0.5">Image Source</p>
                <div className="flex items-center justify-between gap-2 bg-white border border-slate-200 p-2 rounded">
                  <span className="font-medium text-slate-700 truncate">{imageSource}</span>
                  {imageSourceUrl && (
                    <a
                      href={imageSourceUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="text-indigo-600 hover:underline shrink-0 text-[11px] font-semibold"
                    >
                      View Source ↗
                    </a>
                  )}
                </div>
              </div>

              {aiResult.slug && (
                <div className="pt-2 border-t border-slate-200">
                  <p className="font-bold uppercase tracking-wider text-slate-400 mb-0.5">Post Slug</p>
                  <p className="font-mono text-[11px] bg-white border border-slate-200 px-2 py-1 rounded text-slate-600 truncate">
                    /{aiResult.slug}
                  </p>
                </div>
              )}
            </div>

            {/* Draft Action Button */}
            <div className="mt-auto pt-3">
              {draftUrl ? (
                <a
                  href={draftUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center justify-center w-full px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-semibold uppercase tracking-wider shadow-sm transition-colors gap-1.5"
                >
                  <span>Open WordPress Draft</span>
                  <span>↗</span>
                </a>
              ) : (
                <button disabled className="px-4 py-2.5 bg-slate-100 border border-slate-200 text-slate-400 rounded-lg text-xs font-medium w-full cursor-not-allowed">
                  Draft URL Pending
                </button>
              )}
            </div>
          </div>
        )}

        {/* Empty State */}
        {!processResult && (
           <div className="flex flex-col items-center justify-center flex-1 text-center py-10">
             <div className="w-16 h-16 bg-slate-50 rounded-full flex items-center justify-center text-2xl mb-4 border border-slate-100 shadow-sm">
               📝
             </div>
             <p className="text-sm font-semibold text-slate-600 mb-1">No Active Draft</p>
             <p className="text-xs text-slate-400 max-w-[200px] leading-relaxed">
               Select an article in Panel 1 and click Process Workflow in Panel 2 to generate WordPress draft details.
             </p>
           </div>
        )}
      </div>
    </div>
  )
}
