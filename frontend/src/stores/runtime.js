import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'

export const useRuntimeStore = defineStore('runtime', () => {
  const apps = ref([])
  const versions = ref({ node: [], python: [] })
  const loading = ref(false)
  const actionLoading = ref(false)

  async function fetchApps() {
    loading.value = true
    try {
      const { data } = await client.get('/runtime/apps')
      apps.value = data.items || []
    } catch (err) {
      console.error('Failed to fetch runtime apps:', err)
    } finally {
      loading.value = false
    }
  }

  async function fetchVersions() {
    try {
      const { data } = await client.get('/runtime/versions')
      versions.value = data
    } catch (err) {
      console.error('Failed to fetch runtime versions:', err)
      // Provide defaults
      versions.value = { node: ['18', '20', '22'], python: ['3.11', '3.12'] }
    }
  }

  async function createApp(payload) {
    const notify = useNotificationsStore()
    actionLoading.value = true
    try {
      const { data } = await client.post('/runtime/apps', payload)
      notify.success(`${payload.app_type === 'node' ? 'Node.js' : 'Python'} app created successfully`)
      await fetchApps()
      return data
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to create app'
      notify.error(msg)
      throw err
    } finally {
      actionLoading.value = false
    }
  }

  async function updateApp(id, payload) {
    const notify = useNotificationsStore()
    actionLoading.value = true
    try {
      const { data } = await client.put(`/runtime/apps/${id}`, payload)
      notify.success('App updated successfully')
      await fetchApps()
      return data
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to update app'
      notify.error(msg)
      throw err
    } finally {
      actionLoading.value = false
    }
  }

  async function deleteApp(id) {
    const notify = useNotificationsStore()
    actionLoading.value = true
    try {
      await client.delete(`/runtime/apps/${id}`)
      notify.success('App deleted successfully')
      await fetchApps()
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to delete app'
      notify.error(msg)
      throw err
    } finally {
      actionLoading.value = false
    }
  }

  async function startApp(id) {
    const notify = useNotificationsStore()
    actionLoading.value = true
    try {
      const { data } = await client.post(`/runtime/apps/${id}/start`)
      notify.success('App started')
      await fetchApps()
      return data
    } catch (err) {
      notify.error(err.response?.data?.detail || 'Failed to start app')
      throw err
    } finally {
      actionLoading.value = false
    }
  }

  async function stopApp(id) {
    const notify = useNotificationsStore()
    actionLoading.value = true
    try {
      const { data } = await client.post(`/runtime/apps/${id}/stop`)
      notify.success('App stopped')
      await fetchApps()
      return data
    } catch (err) {
      notify.error(err.response?.data?.detail || 'Failed to stop app')
      throw err
    } finally {
      actionLoading.value = false
    }
  }

  async function restartApp(id) {
    const notify = useNotificationsStore()
    actionLoading.value = true
    try {
      const { data } = await client.post(`/runtime/apps/${id}/restart`)
      notify.success('App restarted')
      await fetchApps()
      return data
    } catch (err) {
      notify.error(err.response?.data?.detail || 'Failed to restart app')
      throw err
    } finally {
      actionLoading.value = false
    }
  }

  async function getAppLogs(id, logType = 'all', lines = 200) {
    try {
      const { data } = await client.get(`/runtime/apps/${id}/logs`, {
        params: { log_type: logType, lines }
      })
      return data.logs || {}
    } catch (err) {
      console.error('Failed to fetch logs:', err)
      return {}
    }
  }

  async function installDeps(id) {
    const notify = useNotificationsStore()
    actionLoading.value = true
    try {
      const { data } = await client.post(`/runtime/apps/${id}/install-deps`)
      notify.success('Dependencies installed successfully')
      return data
    } catch (err) {
      const msg = err.response?.data?.detail || 'Failed to install dependencies'
      notify.error(msg)
      throw err
    } finally {
      actionLoading.value = false
    }
  }

  return {
    apps,
    versions,
    loading,
    actionLoading,
    fetchApps,
    fetchVersions,
    createApp,
    updateApp,
    deleteApp,
    startApp,
    stopApp,
    restartApp,
    getAppLogs,
    installDeps
  }
})
