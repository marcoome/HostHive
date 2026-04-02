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
    model: 'gpt-4o',
    apiKey: '',
    baseUrl: 'http://localhost:11434',
    autoFix: false,
    logAnalysisInterval: 'daily',
    tokenLimit: 2000
  })
  const streaming = ref(false)
  const streamingText = ref('')

  const notify = useNotificationsStore()

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
      // Get fresh token (may have been refreshed by interceptor)
      const storedTokens = JSON.parse(localStorage.getItem('hosthive_tokens') || '{}')
      const authHeader = storedTokens.access ? `Bearer ${storedTokens.access}` : ''

      if (!authHeader) {
        throw new Error('Not authenticated. Please log in again.')
      }

      const response = await fetch('/api/v1/ai/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
          'Authorization': authHeader
        },
        body: JSON.stringify({
          message,
          context: context || {}
        })
      })

      // Handle auth errors
      if (response.status === 401) {
        // Try to refresh token
        try {
          const refreshResp = await fetch('/api/v1/auth/refresh', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: storedTokens.refresh })
          })
          if (refreshResp.ok) {
            const refreshData = await refreshResp.json()
            const newTokens = { access: refreshData.access_token, refresh: refreshData.refresh_token || storedTokens.refresh }
            localStorage.setItem('hosthive_tokens', JSON.stringify(newTokens))
            // Retry with new token
            return sendMessage(message, context)
          }
        } catch {}
        throw new Error('Session expired. Please log in again.')
      }

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
              if (parsed.conversation_id) {
                currentConversation.value.id = parsed.conversation_id
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
    // Map backend snake_case to frontend camelCase
    settings.value = {
      provider: data.provider || 'openai',
      model: data.model || 'gpt-4o',
      apiKey: data.api_key || data.apiKey || '',
      baseUrl: data.base_url || data.baseUrl || '',
      autoFix: data.auto_fix_enabled ?? data.autoFix ?? false,
      logAnalysisInterval: data.log_analysis_interval || data.logAnalysisInterval || 'daily',
      tokenLimit: data.max_tokens_per_request || data.tokenLimit || 2000,
      isEnabled: data.is_enabled ?? data.isEnabled ?? false,
      hasApiKey: data.has_api_key ?? data.hasApiKey ?? false,
    }
    return settings.value
  }

  async function updateSettings(newSettings) {
    // Map frontend camelCase keys to backend snake_case keys
    const payload = {}
    if (newSettings.provider !== undefined) payload.provider = newSettings.provider
    if (newSettings.model !== undefined) payload.model = newSettings.model
    if (newSettings.apiKey !== undefined) payload.api_key = newSettings.apiKey
    if (newSettings.baseUrl !== undefined) payload.base_url = newSettings.baseUrl
    if (newSettings.autoFix !== undefined) payload.auto_fix_enabled = newSettings.autoFix
    if (newSettings.logAnalysisInterval !== undefined) payload.log_analysis_interval = newSettings.logAnalysisInterval
    if (newSettings.tokenLimit !== undefined) payload.max_tokens_per_request = newSettings.tokenLimit
    // Also pass is_enabled = true when saving settings with an API key
    if (payload.api_key) payload.is_enabled = true

    const { data } = await client.put('/ai/settings', payload)
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
