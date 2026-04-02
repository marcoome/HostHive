import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'

export const useResellerStore = defineStore('reseller', () => {
  const dashboard = ref(null)
  const users = ref([])
  const usersTotal = ref(0)
  const branding = ref(null)
  const limits = ref(null)
  const packages = ref([])
  const loading = ref(false)

  async function fetchDashboard() {
    loading.value = true
    try {
      const { data } = await client.get('/reseller/dashboard')
      dashboard.value = data
    } finally {
      loading.value = false
    }
  }

  async function fetchUsers(skip = 0, limit = 50) {
    loading.value = true
    try {
      const { data } = await client.get('/reseller/users', { params: { skip, limit } })
      users.value = Array.isArray(data?.items) ? data.items : (Array.isArray(data) ? data : [])
      usersTotal.value = data?.total || users.value.length
    } finally {
      loading.value = false
    }
  }

  async function createUser(payload) {
    const { data } = await client.post('/reseller/users', payload)
    users.value.unshift(data)
    usersTotal.value++
    return data
  }

  async function updateUser(id, payload) {
    if (!id) { console.warn('reseller.updateUser called without id'); return }
    const { data } = await client.put(`/reseller/users/${id}`, payload)
    const idx = users.value.findIndex(u => u.id === id)
    if (idx !== -1) users.value[idx] = data
    return data
  }

  async function deleteUser(id) {
    if (!id) { console.warn('reseller.deleteUser called without id'); return }
    await client.delete(`/reseller/users/${id}`)
    users.value = users.value.filter(u => u.id !== id)
    usersTotal.value--
  }

  async function suspendUser(id) {
    if (!id) { console.warn('reseller.suspendUser called without id'); return }
    const { data } = await client.post(`/reseller/users/${id}/suspend`)
    const idx = users.value.findIndex(u => u.id === id)
    if (idx !== -1) users.value[idx] = data
    return data
  }

  async function unsuspendUser(id) {
    if (!id) { console.warn('reseller.unsuspendUser called without id'); return }
    const { data } = await client.post(`/reseller/users/${id}/unsuspend`)
    const idx = users.value.findIndex(u => u.id === id)
    if (idx !== -1) users.value[idx] = data
    return data
  }

  async function fetchBranding() {
    try {
      const { data } = await client.get('/reseller/branding')
      branding.value = data
    } catch (err) {
      if (err.response?.status === 404) {
        branding.value = null
      } else {
        throw err
      }
    }
  }

  async function updateBranding(payload) {
    const { data } = await client.put('/reseller/branding', payload)
    branding.value = data
    return data
  }

  async function fetchLimits() {
    try {
      const { data } = await client.get('/reseller/limits')
      limits.value = data
    } catch (err) {
      if (err.response?.status === 404) {
        limits.value = null
      } else {
        throw err
      }
    }
  }

  async function fetchPackages() {
    const { data } = await client.get('/reseller/packages')
    packages.value = Array.isArray(data?.items) ? data.items : (Array.isArray(data) ? data : [])
  }

  return {
    dashboard, users, usersTotal, branding, limits, packages, loading,
    fetchDashboard, fetchUsers, createUser, updateUser, deleteUser,
    suspendUser, unsuspendUser, fetchBranding, updateBranding,
    fetchLimits, fetchPackages
  }
})
