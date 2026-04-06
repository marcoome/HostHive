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

  async function createBackup(id) {
    const { data } = await client.post(`/databases/${id}/backup`)
    return data
  }

  async function listBackups(id) {
    const { data } = await client.get(`/databases/${id}/backups`)
    return data.backups || []
  }

  async function restoreBackup(id, backupName) {
    const { data } = await client.post(`/databases/${id}/restore`, { backup_name: backupName })
    return data
  }

  async function downloadBackup(id, backupName) {
    const response = await client.get(`/databases/${id}/backup/download`, {
      params: { backup_name: backupName },
      responseType: 'blob'
    })
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', backupName)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  }

  async function deleteBackup(id, backupName) {
    await client.delete(`/databases/${id}/backup/${encodeURIComponent(backupName)}`)
  }

  // ---------------------------------------------------------------
  // Remote access
  // ---------------------------------------------------------------
  async function updateRemoteAccess(id, { enabled, allowed_hosts }) {
    const { data } = await client.put(`/databases/${id}/remote-access`, {
      enabled,
      allowed_hosts,
    })
    const idx = databases.value.findIndex(d => d.id === id)
    if (idx !== -1) {
      databases.value[idx].remote_access = data.remote_access
      databases.value[idx].allowed_hosts = JSON.stringify(data.allowed_hosts)
    }
    return data
  }

  // ---------------------------------------------------------------
  // Additional database users
  // ---------------------------------------------------------------
  async function fetchUsers(dbId) {
    const { data } = await client.get(`/databases/${dbId}/users`)
    return data.users || []
  }

  async function createUser(dbId, payload) {
    const { data } = await client.post(`/databases/${dbId}/users`, payload)
    return data
  }

  async function deleteUser(dbId, userId) {
    await client.delete(`/databases/${dbId}/users/${userId}`)
  }

  async function updateUserPermissions(dbId, userId, permissions) {
    const { data } = await client.put(
      `/databases/${dbId}/users/${userId}/permissions`,
      { permissions }
    )
    return data
  }

  return {
    databases, loading, fetchAll, create, update, remove,
    createBackup, listBackups, restoreBackup, downloadBackup, deleteBackup,
    updateRemoteAccess, fetchUsers, createUser, deleteUser, updateUserPermissions,
  }
})
