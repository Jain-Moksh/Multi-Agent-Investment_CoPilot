import { useCallback, useEffect, useRef, useState } from 'react'
import { Bot, Hammer, Info, SendHorizontal, Sparkles } from 'lucide-react'
import ConversationList from '../components/chat/ConversationList'
import MessageBubble, { TypingIndicator } from '../components/chat/MessageBubble'
import EmptyState from '../components/EmptyState'
import ErrorBanner from '../components/ErrorBanner'
import { getConversation, listConversations, sendMessage } from '../api/chat'
import { getErrorMessage, isNotBuilt } from '../api/client'

const MAX_LENGTH = 2000

const SUGGESTIONS = [
  'Should I buy Tata Motors?',
  'Why is my portfolio down today?',
  'Which sectors look promising?',
  "Explain today's market news",
  'How risky is my portfolio?',
]

function fromHistory(rows) {
  let previousUserStatus = null
  return rows.map((row) => {
    if (row.role === 'user') {
      previousUserStatus = row.security_status
      return { key: `m-${row.id}`, role: 'user', content: row.content, created_at: row.created_at }
    }
    const message = {
      key: `m-${row.id}`,
      role: 'assistant',
      content: row.content,
      created_at: row.created_at,
      meta: null,
      inferredVerdict: previousUserStatus,
    }
    previousUserStatus = null
    return message
  })
}

export default function Assistant() {
  const [conversations, setConversations] = useState([])
  const [conversationsLoading, setConversationsLoading] = useState(true)
  const [conversationsError, setConversationsError] = useState('')
  const [notBuilt, setNotBuilt] = useState(false)

  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [messagesLoading, setMessagesLoading] = useState(false)
  const [messagesError, setMessagesError] = useState('')

  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState('')

  const scrollRef = useRef(null)
  const inputRef = useRef(null)
  const loadId = useRef(0)

  const loadConversations = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setConversationsLoading(true)
    setConversationsError('')
    try {
      setConversations(await listConversations())
    } catch (err) {
      if (isNotBuilt(err)) setNotBuilt(true)
      else if (!quiet) setConversationsError(getErrorMessage(err, 'Could not load conversations.'))
    } finally {
      if (!quiet) setConversationsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadConversations()
  }, [loadConversations])

  useEffect(() => {
    const node = scrollRef.current
    if (node) node.scrollTo({ top: node.scrollHeight, behavior: 'smooth' })
  }, [messages, sending])

  useEffect(() => {
    const node = inputRef.current
    if (!node) return
    node.style.height = 'auto'
    node.style.height = `${Math.min(node.scrollHeight, 160)}px`
  }, [input])

  const openConversation = async (id, { force = false } = {}) => {
    if (sending || (id === activeId && !force)) return
    const requestId = ++loadId.current
    setActiveId(id)
    setMessages([])
    setSendError('')
    setMessagesError('')
    setMessagesLoading(true)
    try {
      const rows = await getConversation(id)
      if (requestId === loadId.current) setMessages(fromHistory(rows))
    } catch (err) {
      if (requestId === loadId.current) setMessagesError(getErrorMessage(err, 'Could not load this conversation.'))
    } finally {
      if (requestId === loadId.current) setMessagesLoading(false)
    }
  }

  const startNewChat = () => {
    if (sending) return
    loadId.current += 1
    setActiveId(null)
    setMessages([])
    setMessagesError('')
    setMessagesLoading(false)
    setSendError('')
    setInput('')
    inputRef.current?.focus()
  }

  const send = async (rawText) => {
    const text = rawText.trim()
    if (!text || sending) return
    const tempKey = `temp-${Date.now()}`
    setMessages((previous) => [
      ...previous,
      { key: tempKey, role: 'user', content: text, created_at: new Date().toISOString() },
    ])
    setInput('')
    setSendError('')
    setSending(true)
    try {
      const data = await sendMessage(text, activeId)
      const now = new Date().toISOString()
      setMessages((previous) => [
        ...previous.map((message) =>
          message.key === tempKey ? { ...message, key: `m-${data.user_message_id}` } : message,
        ),
        {
          key: `m-${data.assistant_message_id}`,
          role: 'assistant',
          content: data.reply,
          created_at: now,
          question: text,
          meta: {
            status: data.status,
            mode: data.mode,
            detected_symbols: data.detected_symbols || [],
            security: data.security,
            sources: data.sources || [],
          },
        },
      ])
      if (!activeId) setActiveId(data.conversation_id)
      loadConversations({ quiet: true })
    } catch (err) {
      setMessages((previous) => previous.filter((message) => message.key !== tempKey))
      setInput(text)
      setSendError(getErrorMessage(err, 'Could not send your message.'))
    } finally {
      setSending(false)
      setTimeout(() => inputRef.current?.focus(), 0)
    }
  }

  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      send(input)
    }
  }

  if (notBuilt) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <EmptyState icon={Hammer} title="Not built yet" message="The chat endpoints are not available on this backend." />
      </div>
    )
  }

  const showEmpty = !messagesLoading && !messagesError && messages.length === 0 && !sending

  return (
    <div className="grid h-[calc(100vh-11.5rem)] min-h-[560px] gap-4 md:grid-cols-[260px_minmax(0,1fr)]">
      <div className="hidden min-h-0 md:block">
        <ConversationList
          conversations={conversations}
          loading={conversationsLoading}
          error={conversationsError}
          activeId={activeId}
          disabled={sending}
          onSelect={openConversation}
          onNew={startNewChat}
          onRetry={() => loadConversations()}
        />
      </div>

      <section className="flex min-h-0 flex-col rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-slate-900">
              {activeId ? conversations.find((c) => c.id === activeId)?.title || 'Conversation' : 'New chat'}
            </h2>
            <p className="text-xs text-slate-500">Every message is scanned by the security layer before the AI sees it.</p>
          </div>
          <button
            type="button"
            onClick={startNewChat}
            disabled={sending}
            className="rounded-xl border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60 md:hidden"
          >
            New chat
          </button>
        </div>

        <div ref={scrollRef} className="min-h-0 flex-1 space-y-5 overflow-y-auto bg-slate-50/60 px-5 py-5">
          {messagesLoading && (
            <div className="space-y-4">
              {[0, 1, 2].map((index) => (
                <div key={index} className={`flex ${index % 2 ? 'justify-start' : 'justify-end'}`}>
                  <div className="h-12 w-2/3 animate-pulse rounded-2xl bg-slate-200" />
                </div>
              ))}
            </div>
          )}

          {messagesError && (
            <ErrorBanner message={messagesError} onRetry={() => openConversation(activeId, { force: true })} />
          )}

          {showEmpty && (
            <div className="flex h-full flex-col items-center justify-center px-4 text-center">
              <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-indigo-100 text-indigo-600">
                <Bot size={24} />
              </div>
              <h3 className="text-lg font-semibold text-slate-900">Ask your investment copilot</h3>
              <p className="mt-1 max-w-md text-sm text-slate-500">
                Ask about your holdings, the market or recent news. Name a stock you hold to get an answer grounded in
                your portfolio.
              </p>
              <div className="mt-5 flex max-w-xl flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    onClick={() => send(suggestion)}
                    className="inline-flex items-center gap-1.5 rounded-full border border-indigo-200 bg-white px-3 py-1.5 text-sm text-indigo-700 shadow-sm hover:bg-indigo-50"
                  >
                    <Sparkles size={14} />
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          )}

          {!messagesLoading &&
            messages.map((message) => (
              <MessageBubble key={message.key} message={message} retryDisabled={sending} onRetry={send} />
            ))}

          {sending && <TypingIndicator />}
        </div>

        <div className="border-t border-slate-200 p-4">
          {sendError && (
            <div className="mb-3">
              <ErrorBanner message={sendError} />
            </div>
          )}
          <form
            onSubmit={(event) => {
              event.preventDefault()
              send(input)
            }}
            className="flex items-end gap-2"
          >
            <textarea
              ref={inputRef}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
              disabled={sending || messagesLoading}
              rows={1}
              maxLength={MAX_LENGTH}
              placeholder={sending ? 'Waiting for the assistant…' : 'Ask about your portfolio, a stock or the market'}
              className="max-h-40 min-h-[44px] flex-1 resize-none rounded-xl border border-slate-300 px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-50 disabled:text-slate-500"
            />
            <button
              type="submit"
              disabled={sending || messagesLoading || !input.trim()}
              aria-label="Send message"
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {sending ? (
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
              ) : (
                <SendHorizontal size={18} />
              )}
            </button>
          </form>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-500">
            <p className="flex items-center gap-1">
              <Info size={12} />
              Replies are grounded in your portfolio only when you name a stock you hold.
            </p>
            <p>
              Enter to send, Shift+Enter for a new line · {input.length}/{MAX_LENGTH}
            </p>
          </div>
        </div>
      </section>
    </div>
  )
}
