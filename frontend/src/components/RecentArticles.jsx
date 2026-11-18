const articles = [
  {
    title: '7 Ways to Support Mindfulness and Emotional Well-Being as an Entrepreneur',
    status: 'Pending',
    seo: 'Not Processed',
    wordpress: 'Draft',
    updated: 'Today',
  },
  {
    title: 'How Small Businesses Can Improve Their Online Presence',
    status: 'Processing',
    seo: 'In Progress',
    wordpress: 'Not Created',
    updated: 'Today',
  },
  {
    title: 'Effective Strategies for Growing a Home Business',
    status: 'Completed',
    seo: 'Optimized',
    wordpress: 'Draft',
    updated: 'Yesterday',
  },
]

const statusBadge = {
  Pending:    'bg-amber-100 text-amber-700',
  Processing: 'bg-sky-100 text-sky-700',
  Completed:  'bg-emerald-100 text-emerald-700',
}

const seoBadge = {
  'Not Processed': 'bg-slate-100 text-slate-500',
  'In Progress':   'bg-sky-100 text-sky-700',
  Optimized:       'bg-emerald-100 text-emerald-700',
}

const wpBadge = {
  Draft:       'bg-amber-100 text-amber-700',
  'Not Created': 'bg-slate-100 text-slate-500',
  Published:   'bg-emerald-100 text-emerald-700',
}

function Badge({ label, colorMap }) {
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${colorMap[label] ?? 'bg-slate-100 text-slate-600'}`}>
      {label}
    </span>
  )
}

export default function RecentArticles() {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700">Recent Articles</h2>
        <span className="text-xs text-slate-400">{articles.length} articles</span>
      </div>

      {/* Scrollable table wrapper */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 text-left">
              <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">Title</th>
              <th className="px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">Status</th>
              <th className="px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">SEO</th>
              <th className="px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">WordPress</th>
              <th className="px-4 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">Updated</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {articles.map((a, i) => (
              <tr key={i} className="hover:bg-slate-50 transition-colors">
                <td className="px-5 py-3.5 text-slate-700 font-medium max-w-xs">
                  <p className="truncate" title={a.title}>{a.title}</p>
                </td>
                <td className="px-4 py-3.5 whitespace-nowrap">
                  <Badge label={a.status} colorMap={statusBadge} />
                </td>
                <td className="px-4 py-3.5 whitespace-nowrap">
                  <Badge label={a.seo} colorMap={seoBadge} />
                </td>
                <td className="px-4 py-3.5 whitespace-nowrap">
                  <Badge label={a.wordpress} colorMap={wpBadge} />
                </td>
                <td className="px-4 py-3.5 text-slate-500 whitespace-nowrap">{a.updated}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
