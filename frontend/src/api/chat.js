import client from './client'

export async function sendMessage(message, conversationId) {
  const { data } = await client.post(
    '/chat/message',
    { message, conversation_id: conversationId || null },
    { timeout: 120000 },
  )
  return data
}

export async function listConversations() {
  const { data } = await client.get('/chat/conversations')
  return data
}

export async function getConversation(conversationId) {
  const { data } = await client.get(`/chat/conversations/${conversationId}`)
  return data
}
