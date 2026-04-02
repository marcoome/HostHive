import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'

export const useWordPressStore = defineStore('wordpress', () => {
  const installs = ref([])
  const loading = ref(false)

  async function fetchInstalls() {
    loading.value = true
    try {
      const { data } = await client.get('/wordpress/installs')
      installs.value = data
      return data
    } finally {
      loading.value = false
    }
  }

  async function getWpInfo(domain) {
    const { data } = await client.get(`/wordpress/${domain}/info`)
    return data
  }

  async function updateCore(domain) {
    const { data } = await client.post(`/wordpress/${domain}/update-core`)
    const notify = useNotificationsStore()
    notify.success(`WordPress core updated for ${domain}`)
    await fetchInstalls()
    return data
  }

  async function updatePlugins(domain) {
    const { data } = await client.post(`/wordpress/${domain}/update-plugins`)
    const notify = useNotificationsStore()
    notify.success(`Plugins updated for ${domain}`)
    return data
  }

  async function backupWp(domain) {
    const { data } = await client.post(`/wordpress/${domain}/backup`)
    const notify = useNotificationsStore()
    notify.success(`Backup created for ${domain}`)
    return data
  }

  async function cloneWp(domain, targetDomain) {
    const { data } = await client.post(`/wordpress/${domain}/clone`, { target_domain: targetDomain })
    const notify = useNotificationsStore()
    notify.success(`${domain} cloned to ${targetDomain}`)
    await fetchInstalls()
    return data
  }

  async function securityCheck(domain) {
    const { data } = await client.post(`/wordpress/${domain}/security-check`)
    return data
  }

  return {
    installs,
    loading,
    fetchInstalls,
    getWpInfo,
    updateCore,
    updatePlugins,
    backupWp,
    cloneWp,
    securityCheck
  }
})
