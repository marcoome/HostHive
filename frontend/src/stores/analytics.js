import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'

export const useAnalyticsStore = defineStore('analytics', () => {
  const overview = ref(null)
  const trafficByDomain = ref([])
  const bandwidthHistory = ref([])
  const topPages = ref([])
  const topReferrers = ref([])
  const responseCodes = ref([])
  const visitorStats = ref({})
  const loading = ref(false)
  const error = ref(null)

  function _handleError(err) {
    error.value = err?.response?.data?.detail || err.message || 'Request failed'
  }

  async function fetchOverview(period = '7d') {
    try {
      loading.value = true
      error.value = null
      const { data } = await client.get('/analytics/overview', { params: { period } })
      overview.value = data
      return data
    } catch (err) {
      _handleError(err)
      return null
    } finally {
      loading.value = false
    }
  }

  async function fetchTrafficByDomain(period = '7d') {
    try {
      error.value = null
      const { data } = await client.get('/analytics/traffic-by-domain', { params: { period } })
      trafficByDomain.value = Array.isArray(data) ? data : (data.domains || [])
      return trafficByDomain.value
    } catch (err) {
      _handleError(err)
      return []
    }
  }

  async function fetchBandwidthHistory(period = '7d') {
    try {
      error.value = null
      const { data } = await client.get('/analytics/bandwidth-history', { params: { period } })
      bandwidthHistory.value = Array.isArray(data) ? data : (data.history || [])
      return bandwidthHistory.value
    } catch (err) {
      _handleError(err)
      return []
    }
  }

  async function fetchTopPages(period = '7d', limit = 20) {
    try {
      error.value = null
      const { data } = await client.get('/analytics/top-pages', { params: { period, limit } })
      topPages.value = Array.isArray(data) ? data : (data.pages || [])
      return topPages.value
    } catch (err) {
      _handleError(err)
      return []
    }
  }

  async function fetchTopReferrers(period = '7d', limit = 20) {
    try {
      error.value = null
      const { data } = await client.get('/analytics/top-referrers', { params: { period, limit } })
      topReferrers.value = Array.isArray(data) ? data : (data.referrers || [])
      return topReferrers.value
    } catch (err) {
      _handleError(err)
      return []
    }
  }

  async function fetchResponseCodes(period = '7d') {
    try {
      error.value = null
      const { data } = await client.get('/analytics/response-codes', { params: { period } })
      responseCodes.value = Array.isArray(data) ? data : (data.codes || [])
      return responseCodes.value
    } catch (err) {
      _handleError(err)
      return []
    }
  }

  async function fetchVisitorStats(domain, period = '7d') {
    try {
      error.value = null
      const { data } = await client.get(`/analytics/${domain}/stats`, { params: { period } })
      visitorStats.value = data
      return data
    } catch (err) {
      _handleError(err)
      return null
    }
  }

  async function fetchAll(period = '7d') {
    loading.value = true
    error.value = null
    try {
      await Promise.all([
        fetchOverview(period),
        fetchTrafficByDomain(period),
        fetchBandwidthHistory(period),
        fetchTopPages(period),
        fetchTopReferrers(period),
        fetchResponseCodes(period)
      ])
    } catch (err) {
      _handleError(err)
    } finally {
      loading.value = false
    }
  }

  return {
    overview,
    trafficByDomain,
    bandwidthHistory,
    topPages,
    topReferrers,
    responseCodes,
    visitorStats,
    loading,
    error,
    fetchOverview,
    fetchTrafficByDomain,
    fetchBandwidthHistory,
    fetchTopPages,
    fetchTopReferrers,
    fetchResponseCodes,
    fetchVisitorStats,
    fetchAll
  }
})
