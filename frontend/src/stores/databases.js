import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'

export const useDatabasesStore = defineStore('databases', () => {
  const databases = ref([])
  const loading = ref(false)

  async function fetchAll() {
    loading.value = true
    try {
      const { data } = await client.get('/databases')
      databases.value = Array.isArray(data) ? data : (data.items || [])
    } finally {
      loading.value = false
    }
  }

  async function create(payload) {
    const { data } = await client.post('/databases', payload)
    databases.value.push(data)
    return data
  }

  async function update(id, payload) {
    if (!id) { console.warn('databases.update called without id'); return }
    const { data } = await client.put(`/databases/${id}`, payload)
    const idx = databases.value.findIndex(d => d.id === id)
    if (idx !== -1) databases.value[idx] = data
    return data
  }

  async function remove(id) {
    if (!id) { console.warn('databases.remove called without id'); return }
    await client.delete(`/databases/${id}`)
    databases.value = databases.value.filter(d => d.id !== id)
  }

  return { databases, loading, fetchAll, create, update, remove }
})
