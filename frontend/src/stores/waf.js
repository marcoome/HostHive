import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'

export const useWafStore = defineStore('waf', () => {
  // WAF status per domain
  const statuses = ref([])
  const rules = ref({})       // domain -> { domain, rules, total }
  const blockedLog = ref({})  // domain -> { domain, entries, total }
  const stats = ref({
    total_blocked: 0,
    top_attack_types: [],
    top_ips: [],
    domains_with_waf: 0
  })

  // Geo-blocking
  const geoStatus = ref({
    installed: false,
    db_exists: false,
    db_path: '',
    db_last_modified: null,
    geoipupdate_installed: false,
    enabled: false
  })
  const geoRules = ref({ mode: 'blacklist', rules: [], total: 0 })

  const loading = ref(false)
  const geoLoading = ref(false)

  // ---------- WAF Status ----------

  async function fetchWafStatus() {
    loading.value = true
    try {
      const { data } = await client.get('/waf/status')
      statuses.value = Array.isArray(data) ? data : []
      return data
    } catch (err) {
      throw err
    } finally {
      loading.value = false
    }
  }

  async function enableWaf(domain) {
    const { data } = await client.post(`/waf/${domain}/enable`)
    const notify = useNotificationsStore()
    notify.success(`WAF enabled for ${domain}`)
    await fetchWafStatus()
    return data
  }

  async function disableWaf(domain) {
    const { data } = await client.post(`/waf/${domain}/disable`)
    const notify = useNotificationsStore()
    notify.success(`WAF disabled for ${domain}`)
    await fetchWafStatus()
    return data
  }

  async function setWafMode(domain, mode) {
    const { data } = await client.put(`/waf/${domain}/mode`, { mode })
    const notify = useNotificationsStore()
    notify.success(`WAF mode set to "${mode}" for ${domain}`)
    await fetchWafStatus()
    return data
  }

  // ---------- Rules ----------

  async function fetchRules(domain) {
    const { data } = await client.get(`/waf/${domain}/rules`)
    rules.value[domain] = data
    return data
  }

  async function addRule(domain, rule) {
    const { data } = await client.post(`/waf/${domain}/rules`, { rule })
    const notify = useNotificationsStore()
    notify.success('WAF rule added')
    await fetchRules(domain)
    return data
  }

  async function deleteRule(domain, ruleId) {
    const { data } = await client.delete(`/waf/${domain}/rules/${ruleId}`)
    const notify = useNotificationsStore()
    notify.success('WAF rule deleted')
    await fetchRules(domain)
    return data
  }

  // ---------- Blocked Requests Log ----------

  async function fetchBlockedRequests(domain, lines = 100) {
    const { data } = await client.get(`/waf/${domain}/log`, { params: { lines } })
    blockedLog.value[domain] = data
    return data
  }

  // ---------- Stats ----------

  async function fetchStats() {
    const { data } = await client.get('/waf/stats')
    stats.value = data
    return data
  }

  // ---------- Geo-Blocking ----------

  async function fetchGeoStatus() {
    geoLoading.value = true
    try {
      const { data } = await client.get('/waf/geo/status')
      geoStatus.value = data
      return data
    } finally {
      geoLoading.value = false
    }
  }

  async function fetchGeoRules() {
    const { data } = await client.get('/waf/geo/rules')
    geoRules.value = data
    return data
  }

  async function addGeoRule(countryCode, action) {
    const { data } = await client.post('/waf/geo/rules', {
      country_code: countryCode.toUpperCase(),
      action
    })
    const notify = useNotificationsStore()
    notify.success(`Geo rule added for ${countryCode.toUpperCase()}`)
    geoRules.value = data
    return data
  }

  async function deleteGeoRule(countryCode) {
    const { data } = await client.delete(`/waf/geo/rules/${countryCode.toUpperCase()}`)
    const notify = useNotificationsStore()
    notify.success(`Geo rule removed for ${countryCode.toUpperCase()}`)
    geoRules.value = data
    return data
  }

  async function setGeoMode(mode) {
    const { data } = await client.put('/waf/geo/mode', { mode })
    const notify = useNotificationsStore()
    notify.success(`Geo-blocking mode set to "${mode}"`)
    geoRules.value = data
    return data
  }

  async function updateGeoDb() {
    const { data } = await client.post('/waf/geo/update-db')
    const notify = useNotificationsStore()
    if (data.ok) {
      notify.success('GeoIP database updated successfully')
    } else {
      notify.error(data.error || 'GeoIP database update failed')
    }
    await fetchGeoStatus()
    return data
  }

  return {
    statuses,
    rules,
    blockedLog,
    stats,
    geoStatus,
    geoRules,
    loading,
    geoLoading,
    fetchWafStatus,
    enableWaf,
    disableWaf,
    setWafMode,
    fetchRules,
    addRule,
    deleteRule,
    fetchBlockedRequests,
    fetchStats,
    fetchGeoStatus,
    fetchGeoRules,
    addGeoRule,
    deleteGeoRule,
    setGeoMode,
    updateGeoDb
  }
})
