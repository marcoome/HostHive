import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'

export const useIpManagerStore = defineStore('ipManager', () => {
  const addresses = ref([])
  const blacklist = ref([])
  const whitelist = ref([])
  const loading = ref(false)
  const blacklistLoading = ref(false)
  const whitelistLoading = ref(false)

  // ---- Server IPs ----

  async function fetchIPs() {
    loading.value = true
    try {
      const { data } = await client.get('/ip/addresses')
      addresses.value = Array.isArray(data?.addresses) ? data.addresses : []
      return data
    } finally {
      loading.value = false
    }
  }

  async function addIP(payload) {
    const { data } = await client.post('/ip/addresses', payload)
    // Refresh full list after adding
    await fetchIPs()
    return data
  }

  async function removeIP(ip, iface = 'eth0') {
    const encoded = encodeURIComponent(ip)
    const { data } = await client.delete(`/ip/addresses/${encoded}`, {
      params: { interface: iface }
    })
    // Refresh full list after removing
    await fetchIPs()
    return data
  }

  // ---- Blacklist ----

  async function fetchBlacklist() {
    blacklistLoading.value = true
    try {
      const { data } = await client.get('/ip/blacklist')
      blacklist.value = Array.isArray(data?.blocked) ? data.blocked : []
      return data
    } finally {
      blacklistLoading.value = false
    }
  }

  async function addToBlacklist(payload) {
    const { data } = await client.post('/ip/blacklist', payload)
    await fetchBlacklist()
    return data
  }

  async function removeFromBlacklist(ip) {
    const encoded = encodeURIComponent(ip)
    const { data } = await client.delete(`/ip/blacklist/${encoded}`)
    await fetchBlacklist()
    return data
  }

  // ---- Whitelist ----

  async function fetchWhitelist() {
    whitelistLoading.value = true
    try {
      const { data } = await client.get('/ip/whitelist')
      whitelist.value = Array.isArray(data?.whitelisted) ? data.whitelisted : []
      return data
    } finally {
      whitelistLoading.value = false
    }
  }

  async function addToWhitelist(payload) {
    const { data } = await client.post('/ip/whitelist', payload)
    await fetchWhitelist()
    return data
  }

  async function removeFromWhitelist(ip) {
    const encoded = encodeURIComponent(ip)
    // Uses the same UFW allow rule deletion pattern
    const { data } = await client.delete(`/ip/whitelist/${encoded}`)
    await fetchWhitelist()
    return data
  }

  return {
    addresses, blacklist, whitelist,
    loading, blacklistLoading, whitelistLoading,
    fetchIPs, addIP, removeIP,
    fetchBlacklist, addToBlacklist, removeFromBlacklist,
    fetchWhitelist, addToWhitelist, removeFromWhitelist
  }
})
