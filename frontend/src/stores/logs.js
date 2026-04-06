import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'

export const useLogsStore = defineStore('logs', () => {
  const lines = ref([])
  const availableServices = ref([])
  const loading = ref(false)
  const loadingServices = ref(false)
  const totalLines = ref(0)
  const currentService = ref('')
  const searchQuery = ref('')
  const searchResults = ref([])
  const searchCount = ref(0)
  const isSearching = ref(false)

  // WebSocket / auto-refresh state
  const autoRefreshInterval = ref(null)
  const autoRefreshTimer = ref(null)
  const isStreaming = ref(false)

  async function fetchAvailableServices() {
    loadingServices.value = true
    try {
      const { data } = await client.get('/logs/available')
      availableServices.value = data.logs || []
      return availableServices.value
    } catch (err) {
      const notify = useNotificationsStore()
      notify.error('Failed to load available log services')
      throw err
    } finally {
      loadingServices.value = false
    }
  }

  async function fetchLogs(service, lineCount = 200, filter = '') {
    if (!service) return
    loading.value = true
    currentService.value = service
    try {
      if (filter) {
        // Use search endpoint when filter is active
        const { data } = await client.get(`/logs/${service}/search`, {
          params: {
            q: filter,
            lines: lineCount,
            case_sensitive: false
          }
        })
        lines.value = data.matches || []
        totalLines.value = data.match_count || 0
        searchQuery.value = filter
      } else {
        const { data } = await client.get(`/logs/${service}`, {
          params: {
            lines: lineCount,
            order: 'asc'
          }
        })
        lines.value = data.lines || []
        totalLines.value = data.total_lines || data.count || 0
        searchQuery.value = ''
      }
    } catch (err) {
      const notify = useNotificationsStore()
      notify.error(`Failed to load logs for ${service}`)
      throw err
    } finally {
      loading.value = false
    }
  }

  function startAutoRefresh(service, lineCount, filter, intervalMs) {
    stopAutoRefresh()
    if (!service || !intervalMs) return

    isStreaming.value = true
    autoRefreshInterval.value = intervalMs

    autoRefreshTimer.value = setInterval(() => {
      fetchLogs(service, lineCount, filter)
    }, intervalMs)
  }

  function stopAutoRefresh() {
    if (autoRefreshTimer.value) {
      clearInterval(autoRefreshTimer.value)
      autoRefreshTimer.value = null
    }
    isStreaming.value = false
    autoRefreshInterval.value = null
  }

  async function searchLogs(service, query, lineCount = 500) {
    if (!service || !query) return
    isSearching.value = true
    try {
      const { data } = await client.get(`/logs/${service}/search`, {
        params: {
          q: query,
          lines: lineCount,
          case_sensitive: false
        }
      })
      searchResults.value = data.matches || []
      searchCount.value = data.match_count || 0
    } catch (err) {
      const notify = useNotificationsStore()
      notify.error('Log search failed')
      throw err
    } finally {
      isSearching.value = false
    }
  }

  async function rotateLogs() {
    try {
      const { data } = await client.post('/logs/rotate')
      const notify = useNotificationsStore()
      notify.success('Log rotation completed')
      return data
    } catch (err) {
      const notify = useNotificationsStore()
      notify.error('Failed to rotate logs')
      throw err
    }
  }

  function clearState() {
    lines.value = []
    searchResults.value = []
    searchCount.value = 0
    searchQuery.value = ''
    totalLines.value = 0
    stopAutoRefresh()
  }

  return {
    lines,
    availableServices,
    loading,
    loadingServices,
    totalLines,
    currentService,
    searchQuery,
    searchResults,
    searchCount,
    isSearching,
    isStreaming,
    autoRefreshInterval,
    fetchAvailableServices,
    fetchLogs,
    searchLogs,
    startAutoRefresh,
    stopAutoRefresh,
    rotateLogs,
    clearState
  }
})
