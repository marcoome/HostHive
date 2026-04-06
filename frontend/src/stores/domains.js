import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'

export const useDomainsStore = defineStore('domains', () => {
  const domains = ref([])
  const loading = ref(false)
  const currentDomain = ref(null)

  async function fetchAll() {
    loading.value = true
    try {
      const { data } = await client.get('/domains')
      domains.value = Array.isArray(data) ? data : (data.items || [])
    } finally {
      loading.value = false
    }
  }

  async function fetchOne(id) {
    if (!id) { console.warn('domains.fetchOne called without id'); return }
    loading.value = true
    try {
      const { data } = await client.get(`/domains/${id}`)
      currentDomain.value = data
      return data
    } finally {
      loading.value = false
    }
  }

  async function create(payload) {
    const { data } = await client.post('/domains', payload)
    domains.value.push(data)
    return data
  }

  async function update(id, payload) {
    if (!id) { console.warn('domains.update called without id'); return }
    const { data } = await client.put(`/domains/${id}`, payload)
    const idx = domains.value.findIndex(d => d.id === id)
    if (idx !== -1) domains.value[idx] = data
    return data
  }

  async function remove(id) {
    if (!id) { console.warn('domains.remove called without id'); return }
    await client.delete(`/domains/${id}`)
    domains.value = domains.value.filter(d => d.id !== id)
  }

  // --- Subdomain methods ---
  const subdomains = ref([])
  const subdomainsLoading = ref(false)

  async function fetchSubdomains(domainId) {
    if (!domainId) return
    subdomainsLoading.value = true
    try {
      const { data } = await client.get(`/domains/${domainId}/subdomains`)
      subdomains.value = data.items || []
      return subdomains.value
    } finally {
      subdomainsLoading.value = false
    }
  }

  async function createSubdomain(domainId, payload) {
    const { data } = await client.post(`/domains/${domainId}/subdomains`, payload)
    subdomains.value.unshift(data)
    return data
  }

  async function updateSubdomain(domainId, subId, payload) {
    const { data } = await client.put(`/domains/${domainId}/subdomains/${subId}`, payload)
    const idx = subdomains.value.findIndex(s => s.id === subId)
    if (idx !== -1) subdomains.value[idx] = data
    return data
  }

  async function removeSubdomain(domainId, subId) {
    await client.delete(`/domains/${domainId}/subdomains/${subId}`)
    subdomains.value = subdomains.value.filter(s => s.id !== subId)
  }

  return {
    domains, loading, currentDomain,
    fetchAll, fetchOne, create, update, remove,
    subdomains, subdomainsLoading,
    fetchSubdomains, createSubdomain, updateSubdomain, removeSubdomain,
  }
})
