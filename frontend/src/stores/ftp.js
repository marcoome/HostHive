import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'

export const useFtpStore = defineStore('ftp', () => {
  const accounts = ref([])
  const loading = ref(false)

  async function fetchAccounts() {
    loading.value = true
    try {
      const { data } = await client.get('/ftp/accounts')
      accounts.value = Array.isArray(data) ? data : (data.items || [])
    } finally {
      loading.value = false
    }
  }

  async function createAccount(payload) {
    const { data } = await client.post('/ftp/accounts', payload)
    accounts.value.push(data)
    return data
  }

  async function updateAccount(id, payload) {
    if (!id) { console.warn('updateAccount called without id'); return }
    const { data } = await client.put(`/ftp/accounts/${id}`, payload)
    const idx = accounts.value.findIndex(a => a.id === id)
    if (idx !== -1) accounts.value[idx] = data
    return data
  }

  async function removeAccount(id) {
    if (!id) { console.warn('removeAccount called without id'); return }
    await client.delete(`/ftp/accounts/${id}`)
    accounts.value = accounts.value.filter(a => a.id !== id)
  }

  async function toggleStatus(id) {
    if (!id) { console.warn('toggleStatus called without id'); return }
    const { data } = await client.post(`/ftp/accounts/${id}/toggle`)
    const idx = accounts.value.findIndex(a => a.id === id)
    if (idx !== -1) accounts.value[idx] = data
    return data
  }

  return {
    accounts, loading,
    fetchAccounts, createAccount, updateAccount, removeAccount, toggleStatus
  }
})
