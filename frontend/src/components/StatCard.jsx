export default function StatCard({ label, value, sub, valueClass = 'text-slate-900', icon: Icon }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">{label}</p>
        {Icon && <Icon size={18} className="text-slate-400" />}
      </div>
      <p className={`mt-2 text-2xl font-semibold ${valueClass}`}>{value}</p>
      {sub && <p className="mt-1 text-sm">{sub}</p>}
    </div>
  )
}
