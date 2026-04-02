import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'

export const useApiKeysStore = defineStore('apiKeys', () => {
  const keys = ref([])
  const loading = ref(false)

  async function fetchKeys() {
    loading.value = true
    try {
      const { data } = await client.get('/api-keys')
      keys.value = Array.isArray(data?.keys) ? data.keys : (Array.isArray(data) ? data : [])
    } catch (err) {
      const notify = useNotificationsStore()
      notify.error('Failed to load API keys')
      throw err
    } finally {
      loading.value = false
    }
  }

  async function createKey(payload) {
    const notify = useNotificationsStore()
    try {
      const { data } = await client.post('/api-keys', payload)
      keys.value.push(data.key_info || data)
      notify.success('API key created')
      return data
    } catch (err) {
      notify.error('Failed to create API key')
      throw err
    }
  }

  async function revokeKey(id) {
    if (!id) { console.warn('revokeKey called without id'); return }
    const notify = useNotificationsStore()
    try {
      await client.delete(`/api-keys/${id}`)
      keys.value = keys.value.filter(k => k.id !== id)
      notify.success('API key revoked')
    } catch (err) {
      notify.error('Failed to revoke API key')
      throw err
    }
  }

  return { keys, loading, fetchKeys, createKey, revokeKey }
})
