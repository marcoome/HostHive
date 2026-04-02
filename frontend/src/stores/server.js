import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'

export const useServerStore = defineStore('server', () => {
  const stats = ref(null)
  const services = ref([])
  const firewallRules = ref([])
  const fail2banJails = ref([])
  const loading = ref(false)

  async function fetchStats() {
    loading.value = true
    try {
      const { data } = await client.get('/server/stats')
      stats.value = data
    } finally {
      loading.value = false
    }
  }

  async function fetchServices() {
    const { data } = await client.get('/server/services')
    services.value = Array.isArray(data) ? data : []
  }

  async function restartService(name) {
    if (!name) { console.warn('restartService called without name'); return }
    await client.post(`/server/services/${name}/restart`)
    await fetchServices()
  }

  async function toggleService(name, action) {
    if (!name || !action) { console.warn('toggleService called without name or action'); return }
    await client.post(`/server/services/${name}/${action}`)
    await fetchServices()
  }

  async function fetchFirewallRules() {
    const { data } = await client.get('/server/firewall')
    firewallRules.value = Array.isArray(data) ? data : []
  }

  async function addFirewallRule(payload) {
    const { data } = await client.post('/server/firewall', payload)
    firewallRules.value.push(data)
    return data
  }

  async function removeFirewallRule(id) {
    if (!id) { console.warn('removeFirewallRule called without id'); return }
    await client.delete(`/server/firewall/${id}`)
    firewallRules.value = firewallRules.value.filter(r => r.id !== id)
  }

  async function fetchFail2ban() {
    const { data } = await client.get('/server/fail2ban')
    fail2banJails.value = Array.isArray(data) ? data : []
  }

  async function toggleFail2banJail(jail, action) {
    if (!jail || !action) { console.warn('toggleFail2banJail called without jail or action'); return }
    await client.post(`/server/fail2ban/${jail}/${action}`)
    await fetchFail2ban()
  }

  return {
    stats, services, firewallRules, fail2banJails, loading,
    fetchStats, fetchServices, restartService, toggleService,
    fetchFirewallRules, addFirewallRule, removeFirewallRule,
    fetchFail2ban, toggleFail2banJail
  }
})
