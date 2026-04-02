import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'

export const useIntegrationsStore = defineStore('integrations', () => {
  const integrations = ref([])
  const loading = ref(false)

  async function fetchIntegrations() {
    loading.value = true
    try {
      const { data } = await client.get('/integrations')
      integrations.value = data
    } catch (err) {
      const notify = useNotificationsStore()
      notify.error('Failed to load integrations')
      throw err
    } finally {
      loading.value = false
    }
  }

  async function updateIntegration(name, config) {
    const notify = useNotificationsStore()
    try {
      const { data } = await client.put(`/integrations/${name}`, { config })
      const idx = integrations.value.findIndex(i => i.name === name)
      if (idx !== -1) integrations.value[idx] = data
      notify.success(`${name} configuration updated`)
      return data
    } catch (err) {
      notify.error(`Failed to update ${name}`)
      throw err
    }
  }

  async function toggleIntegration(name) {
    const notify = useNotificationsStore()
    try {
      const current = integrations.value.find(i => i.name === name)
      const newState = !(current?.is_enabled)
      const { data } = await client.post(`/integrations/${name}/toggle`, { enabled: newState })
      const idx = integrations.value.findIndex(i => i.name === name)
      if (idx !== -1) integrations.value[idx] = data
      notify.success(`${name} ${data.is_enabled ? 'enabled' : 'disabled'}`)
      return data
    } catch (err) {
      notify.error(`Failed to toggle ${name}`)
      throw err
    }
  }

  async function testConnection(name) {
    const notify = useNotificationsStore()
    try {
      const { data } = await client.post(`/integrations/${name}/test`)
      if (data.success) {
        notify.success(`${name} connection successful`)
      } else {
        notify.error(`${name} connection failed: ${data.message || 'Unknown error'}`)
      }
      return data
    } catch (err) {
      notify.error(`${name} connection test failed`)
      throw err
    }
  }

  return { integrations, loading, fetchIntegrations, updateIntegration, toggleIntegration, testConnection }
})
