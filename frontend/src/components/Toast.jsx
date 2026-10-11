import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import { CheckCircle2, X, XCircle } from 'lucide-react'

const ToastContext = createContext(null)

const DISMISS_AFTER_MS = 4000

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const nextId = useRef(1)

  const dismiss = useCallback((id) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
  }, [])

  const show = useCallback(
    (variant, message) => {
      const id = nextId.current++
      setToasts((current) => [...current, { id, variant, message }])
      setTimeout(() => dismiss(id), DISMISS_AFTER_MS)
    },
    [dismiss],
  )

  const api = useMemo(
    () => ({
      success: (message) => show('success', message),
      error: (message) => show('error', message),
    }),
    [show],
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
        {toasts.map((toast) => {
          const isSuccess = toast.variant === 'success'
          const Icon = isSuccess ? CheckCircle2 : XCircle
          return (
            <div
              key={toast.id}
              role="status"
              className={`flex items-start gap-3 rounded-xl border bg-white px-4 py-3 text-sm shadow-lg ${
                isSuccess ? 'border-green-200 text-green-800' : 'border-red-200 text-red-800'
              }`}
            >
              <Icon size={18} className="mt-0.5 shrink-0" />
              <p className="flex-1">{toast.message}</p>
              <button type="button" onClick={() => dismiss(toast.id)} aria-label="Dismiss">
                <X size={16} />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToast must be used inside ToastProvider')
  return context
}
