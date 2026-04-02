import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'

export const useMonitoringStore = defineStore('monitoring', () => {
  const healthChecks = ref([])
  const incidents = ref([])
  const anomalies = ref([])
  const diskPrediction = ref(null)
  const heatmapData = ref([])
  const realtimeStats = ref({
    cpu: [],
    ram: [],
    diskIo: [],
    networkIo: []
  })
  const loading = ref(false)

  async function fetchHealth() {
    const { data } = await client.get('/monitoring/health')
    healthChecks.value = data
    return data
  }

  async function fetchIncidents() {
    const { data } = await client.get('/monitoring/incidents')
    incidents.value = data
    return data
  }

  async function fetchAnomalies() {
    const { data } = await client.get('/monitoring/anomalies')
    anomalies.value = data
    return data
  }

  async function acknowledgeAnomaly(id) {
    const { data } = await client.post(`/monitoring/anomalies/${id}/acknowledge`)
    const notify = useNotificationsStore()
    notify.success('Anomaly acknowledged')
    anomalies.value = anomalies.value.map(a =>
      a.id === id ? { ...a, acknowledged: true } : a
    )
    return data
  }

  async function fetchDiskPrediction() {
    const { data } = await client.get('/monitoring/disk-prediction')
    diskPrediction.value = data
    return data
  }

  async function fetchBandwidth(domain) {
    const { data } = await client.get(`/monitoring/bandwidth/${domain}`)
    return data
  }

  async function fetchHeatmap() {
    const { data } = await client.get('/monitoring/heatmap')
    heatmapData.value = data
    return data
  }

  async function fetchRealtimeStats() {
    const { data } = await client.get('/monitoring/realtime')
    const now = new Date().toLocaleTimeString()
    const maxPoints = 30

    for (const key of ['cpu', 'ram', 'diskIo', 'networkIo']) {
      realtimeStats.value[key].push({ time: now, value: data[key] || 0 })
      if (realtimeStats.value[key].length > maxPoints) {
        realtimeStats.value[key].shift()
      }
    }
    return data
  }

  return {
    healthChecks,
    incidents,
    anomalies,
    diskPrediction,
    heatmapData,
    realtimeStats,
    loading,
    fetchHealth,
    fetchIncidents,
    fetchAnomalies,
    acknowledgeAnomaly,
    fetchDiskPrediction,
    fetchBandwidth,
    fetchHeatmap,
    fetchRealtimeStats
  }
})
