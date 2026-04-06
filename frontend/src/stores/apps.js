import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'

export const useAppsStore = defineStore('apps', () => {
  const catalog = ref([])
  const installedApps = ref([])
  const loading = ref(false)
  const installing = ref(false)
  const installProgress = ref(null) // { slug, steps, currentStep, status }

  const categories = computed(() => {
    const cats = new Set(catalog.value.map(a => a.category))
    return ['All', ...Array.from(cats).sort()]
  })

  async function fetchCatalog(category = null) {
    loading.value = true
    try {
      const params = category && category !== 'All' ? { category } : {}
      const { data } = await client.get('/apps/catalog', { params })
      catalog.value = Array.isArray(data) ? data : []
    } catch (err) {
      console.error('Failed to fetch app catalog:', err)
    } finally {
      loading.value = false
    }
  }

  async function fetchInstalledApps() {
    loading.value = true
    try {
      const { data } = await client.get('/apps')
      installedApps.value = Array.isArray(data) ? data : (data.items || [])
    } catch (err) {
      console.error('Failed to fetch installed apps:', err)
    } finally {
      loading.value = false
    }
  }

  async function installApp(payload) {
    const notify = useNotificationsStore()
    installing.value = true

    // Simulate step-based progress
    const steps = ['Downloading', 'Configuring', 'Installing DB', 'Setting up', 'Done']
    installProgress.value = {
      slug: payload.slug,
      steps,
      currentStep: 0,
      status: 'in_progress'
    }

    // Advance progress through steps with timed intervals
    const progressInterval = setInterval(() => {
      if (installProgress.value && installProgress.value.currentStep < steps.length - 2) {
        installProgress.value = {
          ...installProgress.value,
          currentStep: installProgress.value.currentStep + 1
        }
      }
    }, 3000)

    try {
      const { data } = await client.post('/apps/catalog/install', payload)
      clearInterval(progressInterval)
      installProgress.value = {
        slug: payload.slug,
        steps,
        currentStep: steps.length - 1,
        status: 'done'
      }
      notify.success(`${data.name || payload.slug} installed successfully`)
      await fetchInstalledApps()
      return data
    } catch (err) {
      clearInterval(progressInterval)
      const msg = err.response?.data?.detail || 'Installation failed'
      installProgress.value = {
        ...installProgress.value,
        status: 'error',
        error: msg
      }
      notify.error(msg)
      throw err
    } finally {
      installing.value = false
    }
  }

  async function uninstallApp(domain) {
    const notify = useNotificationsStore()
    try {
      await client.post(`/apps/${domain}/stop`)
      notify.success(`${domain} stopped and uninstalled`)
      await fetchInstalledApps()
    } catch (err) {
      const msg = err.response?.data?.detail || 'Uninstall failed'
      notify.error(msg)
      throw err
    }
  }

  async function startApp(domain) {
    const notify = useNotificationsStore()
    try {
      await client.post(`/apps/${domain}/start`)
      notify.success(`${domain} started`)
      await fetchInstalledApps()
    } catch (err) {
      notify.error(err.response?.data?.detail || 'Start failed')
      throw err
    }
  }

  async function stopApp(domain) {
    const notify = useNotificationsStore()
    try {
      await client.post(`/apps/${domain}/stop`)
      notify.success(`${domain} stopped`)
      await fetchInstalledApps()
    } catch (err) {
      notify.error(err.response?.data?.detail || 'Stop failed')
      throw err
    }
  }

  async function restartApp(domain) {
    const notify = useNotificationsStore()
    try {
      await client.post(`/apps/${domain}/restart`)
      notify.success(`${domain} restarted`)
      await fetchInstalledApps()
    } catch (err) {
      notify.error(err.response?.data?.detail || 'Restart failed')
      throw err
    }
  }

  function clearProgress() {
    installProgress.value = null
  }

  return {
    catalog,
    installedApps,
    loading,
    installing,
    installProgress,
    categories,
    fetchCatalog,
    fetchInstalledApps,
    installApp,
    uninstallApp,
    startApp,
    stopApp,
    restartApp,
    clearProgress
  }
})
