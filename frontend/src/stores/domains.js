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
      domains.value = data
    } finally {
      loading.value = false
    }
  }

  async function fetchOne(id) {
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
    const { data } = await client.put(`/domains/${id}`, payload)
    const idx = domains.value.findIndex(d => d.id === id)
    if (idx !== -1) domains.value[idx] = data
    return data
  }

  async function remove(id) {
    await client.delete(`/domains/${id}`)
    domains.value = domains.value.filter(d => d.id !== id)
  }

  return { domains, loading, currentDomain, fetchAll, fetchOne, create, update, remove }
})
