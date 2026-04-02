import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'

export const useAuditStore = defineStore('audit', () => {
  const entries = ref([])
  const suspicious = ref([])
  const loading = ref(false)
  const filters = reactive({
    user: '',
    action: '',
    date_from: '',
    date_to: '',
    ip: ''
  })
  const pagination = reactive({
    page: 1,
    perPage: 25,
    total: 0,
    totalPages: 1
  })

  async function fetchEntries(filterOverrides = {}) {
    loading.value = true
    try {
      const params = {
        page: pagination.page,
        per_page: pagination.perPage,
        ...filters,
        ...filterOverrides
      }
      // Remove empty params
      Object.keys(params).forEach(k => {
        if (!params[k]) delete params[k]
      })
      const { data } = await client.get('/audit-log', { params })
      entries.value = data.entries || data.items || []
      pagination.total = data.total || 0
      pagination.totalPages = data.total_pages || Math.ceil(pagination.total / pagination.perPage) || 1
    } catch (err) {
      const notify = useNotificationsStore()
      notify.error('Failed to load audit log')
      throw err
    } finally {
      loading.value = false
    }
  }

  async function exportCsv() {
    const notify = useNotificationsStore()
    try {
      const params = { ...filters }
      Object.keys(params).forEach(k => {
        if (!params[k]) delete params[k]
      })
      const { data } = await client.get('/audit-log/export', {
        params,
        responseType: 'blob'
      })
      const url = window.URL.createObjectURL(new Blob([data]))
      const a = document.createElement('a')
      a.href = url
      a.download = `audit-log-${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      window.URL.revokeObjectURL(url)
      notify.success('Audit log exported')
    } catch (err) {
      notify.error('Failed to export audit log')
      throw err
    }
  }

  async function fetchSuspicious() {
    try {
      const { data } = await client.get('/audit-log/suspicious')
      suspicious.value = data.entries || data || []
    } catch (err) {
      const notify = useNotificationsStore()
      notify.error('Failed to load suspicious activity')
      throw err
    }
  }

  return { entries, suspicious, loading, filters, pagination, fetchEntries, exportCsv, fetchSuspicious }
})
