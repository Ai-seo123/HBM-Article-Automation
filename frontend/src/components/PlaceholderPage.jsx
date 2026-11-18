export default function PlaceholderPage({ title, description, icon }) {
  return (
    <div className="max-w-2xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-800">{title}</h1>
        <p className="text-slate-500 mt-1 text-sm">{description}</p>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-10 text-center">
        <div className="text-5xl mb-4">{icon}</div>
        <h2 className="text-lg font-semibold text-slate-700 mb-2">Coming Soon</h2>
        <p className="text-sm text-slate-500 max-w-sm mx-auto">
          This section is under development. It will be available in a future release.
        </p>
        <span className="mt-5 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-indigo-50 text-indigo-600 text-xs font-medium ring-1 ring-indigo-100">
          🚧 Planned
        </span>
      </div>
    </div>
  )
}
