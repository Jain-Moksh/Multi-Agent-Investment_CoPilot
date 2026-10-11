import { AlertCircle } from 'lucide-react'

export default function ErrorBanner({ message, onRetry }) {
  if (!message) return null
  return (
    <div
      className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
      role="alert"
    >
      <AlertCircle size={18} className="mt-0.5 shrink-0" />
      <p className="flex-1">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded-lg border border-red-300 bg-white px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
        >
          Retry
        </button>
      )}
    </div>
  )
}
