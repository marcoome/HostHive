import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'

export const useCronStore = defineStore('cron', () => {
  const jobs = ref([])
  const loading = ref(false)

  async function fetchJobs() {
    loading.value = true
    try {
      const { data } = await client.get('/cron')
      jobs.value = data.items || data
    } finally {
      loading.value = false
    }
  }

  async function createJob(payload) {
    const { data } = await client.post('/cron', payload)
    jobs.value.push(data)
    return data
  }

  async function updateJob(id, payload) {
    const { data } = await client.put(`/cron/${id}`, payload)
    const idx = jobs.value.findIndex(j => j.id === id)
    if (idx !== -1) jobs.value[idx] = data
    return data
  }

  async function removeJob(id) {
    await client.delete(`/cron/${id}`)
    jobs.value = jobs.value.filter(j => j.id !== id)
  }

  async function runJob(id) {
    const { data } = await client.post(`/cron/${id}/run-now`)
    const idx = jobs.value.findIndex(j => j.id === id)
    if (idx !== -1) jobs.value[idx] = data
    return data
  }

  // NOTE: toggleJob - no backend endpoint yet; wrapped in try-catch
  async function toggleJob(id) {
    try {
      const { data } = await client.post(`/cron/${id}/toggle`)
      const idx = jobs.value.findIndex(j => j.id === id)
      if (idx !== -1) jobs.value[idx] = data
      return data
    } catch {
      console.warn('Cron toggle endpoint not available')
    }
  }

  return {
    jobs, loading,
    fetchJobs, createJob, updateJob, removeJob, runJob, toggleJob
  }
})
