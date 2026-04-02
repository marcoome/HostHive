import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'

export const useAiStore = defineStore('ai', () => {
  const conversations = ref([])
  const currentConversation = ref(null)
  const insights = ref([])
  const settings = ref({
    provider: 'openai',
    model: 'gpt-4',
    apiKey: '',
    baseUrl: 'http://localhost:11434',
    autoFix: false,
    logAnalysisInterval: 'daily',
    tokenLimit: 2000
  })
  const streaming = ref(false)
  const streamingText = ref('')

  const notify = useNotificationsStore

  async function fetchConversations() {
    const { data } = await client.get('/ai/conversations')
    conversations.value = Array.isArray(data) ? data : []
    return conversations.value
  }

  async function fetchInsights() {
    const { data } = await client.get('/ai/insights')
    insights.value = Array.isArray(data) ? data : []
    return insights.value
  }

  async function sendMessage(message, context = null) {
    if (!currentConversation.value) {
      currentConversation.value = {
        id: Date.now(),
        title: message.slice(0, 50),
        messages: [],
        created_at: new Date().toISOString()
      }
    }

    currentConversation.value.messages.push({
      role: 'user',
      content: message,
      timestamp: new Date().toISOString()
    })

    streaming.value = true
    streamingText.value = ''

    try {
      const tokens = JSON.parse(localStorage.getItem('hosthive_tokens') || '{}')
      const response = await fetch('/api/v1/ai/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${tokens.access}`
        },
        body: JSON.stringify({
          conversation_id: currentConversation.value.id,
          message,
          context
        })
      })

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const payload = line.slice(6)
            if (payload === '[DONE]') break
            try {
              const parsed = JSON.parse(payload)
              if (parsed.content) {
                streamingText.value += parsed.content
              }
            } catch {
              streamingText.value += payload
            }
          }
        }
      }

      currentConversation.value.messages.push({
        role: 'assistant',
        content: streamingText.value,
        timestamp: new Date().toISOString()
      })
    } catch (err) {
      currentConversation.value.messages.push({
        role: 'assistant',
        content: 'Sorry, an error occurred while processing your request.',
        timestamp: new Date().toISOString()
      })
    } finally {
      streaming.value = false
      streamingText.value = ''
    }
  }

  async function resolveInsight(id) {
    if (!id) { console.warn('resolveInsight called without id'); return }
    const { data } = await client.post(`/ai/insights/${id}/resolve`)
    insights.value = insights.value.filter(i => i.id !== id)
    return data
  }

  async function applyAutofix(id) {
    if (!id) { console.warn('applyAutofix called without id'); return }
    const { data } = await client.post(`/ai/insights/${id}/autofix`)
    const notify = useNotificationsStore()
    notify.success('Auto-fix applied successfully')
    insights.value = insights.value.filter(i => i.id !== id)
    return data
  }

  async function fetchSettings() {
    const { data } = await client.get('/ai/settings')
    settings.value = { ...settings.value, ...data }
    return data
  }

  async function updateSettings(newSettings) {
    const { data } = await client.put('/ai/settings', newSettings)
    settings.value = { ...settings.value, ...data }
    const notify = useNotificationsStore()
    notify.success('AI settings updated')
    return data
  }

  function startNewConversation() {
    currentConversation.value = null
  }

  function selectConversation(conv) {
    currentConversation.value = conv
  }

  return {
    conversations,
    currentConversation,
    insights,
    settings,
    streaming,
    streamingText,
    fetchConversations,
    fetchInsights,
    sendMessage,
    resolveInsight,
    applyAutofix,
    fetchSettings,
    updateSettings,
    startNewConversation,
    selectConversation
  }
})
