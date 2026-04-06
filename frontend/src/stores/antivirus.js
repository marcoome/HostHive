import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'

export const useAntivirusStore = defineStore('antivirus', () => {
  const status = ref(null)
  const scans = ref([])
  const scansTotal = ref(0)
  const quarantine = ref([])
  const loading = ref(false)
  const statusLoading = ref(false)

  async function fetchStatus() {
    statusLoading.value = true
    try {
      const { data } = await client.get('/antivirus/status')
      status.value = data
      return data
    } finally {
      statusLoading.value = false
    }
  }

  async function triggerScan() {
    const { data } = await client.post('/antivirus/scan')
    const notify = useNotificationsStore()
    notify.success('Full scan dispatched')
    return data
  }

  async function triggerPathScan(path) {
    if (!path) { console.warn('triggerPathScan called without path'); return }
    const { data } = await client.post('/antivirus/scan/path', { path })
    const notify = useNotificationsStore()
    notify.success(`Scan dispatched for: ${path}`)
    return data
  }

  async function fetchScans(skip = 0, limit = 50) {
    loading.value = true
    try {
      const { data } = await client.get('/antivirus/scans', { params: { skip, limit } })
      scans.value = data.items || []
      scansTotal.value = data.total || 0
      return data
    } finally {
      loading.value = false
    }
  }

  async function fetchScanDetail(scanId) {
    if (!scanId) { console.warn('fetchScanDetail called without scanId'); return }
    const { data } = await client.get(`/antivirus/scans/${scanId}`)
    return data
  }

  async function restoreQuarantine(fileId) {
    if (!fileId) { console.warn('restoreQuarantine called without fileId'); return }
    const { data } = await client.post(`/antivirus/quarantine/${fileId}/restore`)
    const notify = useNotificationsStore()
    notify.success('File restored to original location')
    return data
  }

  async function deleteQuarantine(fileId) {
    if (!fileId) { console.warn('deleteQuarantine called without fileId'); return }
    const { data } = await client.post(`/antivirus/quarantine/${fileId}/delete`)
    const notify = useNotificationsStore()
    notify.success('File permanently deleted')
    return data
  }

  async function updateDatabase() {
    const { data } = await client.post('/antivirus/update')
    const notify = useNotificationsStore()
    if (data.status === 'updated') {
      notify.success('Virus database updated successfully')
    } else {
      notify.error('Database update failed: ' + (data.stderr || 'Unknown error'))
    }
    return data
  }

  return {
    status,
    scans,
    scansTotal,
    quarantine,
    loading,
    statusLoading,
    fetchStatus,
    triggerScan,
    triggerPathScan,
    fetchScans,
    fetchScanDetail,
    restoreQuarantine,
    deleteQuarantine,
    updateDatabase
  }
})
