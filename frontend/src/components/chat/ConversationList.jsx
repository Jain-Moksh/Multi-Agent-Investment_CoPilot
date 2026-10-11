import { MessageSquare, Plus } from 'lucide-react'
import ErrorBanner from '../ErrorBanner'
import { formatDateTime, timeAgo } from '../../utils/format'

export default function ConversationList({ conversations, loading, error, activeId, disabled, onSelect, onNew, onRetry }) {
  return (
    <div className="flex h-full min-h-0 flex-col rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 p-3">
        <button
          type="button"
          onClick={onNew}
          disabled={disabled}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <Plus size={16} />
          New chat
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {loading && (
          <div className="space-y-2 p-1">
            {Array.from({ length: 5 }, (_, index) => (
              <div key={index} className="animate-pulse rounded-xl p-2">
                <div className="mb-2 h-3 w-4/5 rounded bg-slate-200" />
                <div className="h-2.5 w-1/3 rounded bg-slate-100" />
              </div>
            ))}
          </div>
        )}

        {!loading && error && (
          <div className="p-1">
            <ErrorBanner message={error} onRetry={onRetry} />
          </div>
        )}

        {!loading && !error && conversations.length === 0 && (
          <div className="flex flex-col items-center px-4 py-10 text-center text-sm text-slate-500">
            <MessageSquare size={22} className="mb-2 text-slate-400" />
            No conversations yet. Your chats will appear here.
          </div>
        )}

        {!loading &&
          !error &&
          conversations.map((conversation) => {
            const active = conversation.id === activeId
            return (
              <button
                key={conversation.id}
                type="button"
                onClick={() => onSelect(conversation.id)}
                disabled={disabled}
                title={conversation.title}
                className={`mb-1 w-full rounded-xl px-3 py-2 text-left transition disabled:cursor-not-allowed ${
                  active ? 'bg-indigo-50 ring-1 ring-inset ring-indigo-200' : 'hover:bg-slate-50'
                }`}
              >
                <p className={`truncate text-sm font-medium ${active ? 'text-indigo-800' : 'text-slate-800'}`}>
                  {conversation.title || 'Untitled chat'}
                </p>
                <p className="mt-0.5 text-xs text-slate-500" title={formatDateTime(conversation.updated_at)}>
                  {timeAgo(conversation.updated_at)}
                </p>
              </button>
            )
          })}
      </div>
    </div>
  )
}
