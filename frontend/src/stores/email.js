import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'

export const useEmailStore = defineStore('email', () => {
  const mailboxes = ref([])
  const aliases = ref([])
  const loading = ref(false)

  async function fetchMailboxes() {
    loading.value = true
    try {
      const { data } = await client.get('/email/mailboxes')
      mailboxes.value = Array.isArray(data) ? data : (data.items || [])
    } finally {
      loading.value = false
    }
  }

  async function createMailbox(payload) {
    const { data } = await client.post('/email/mailboxes', payload)
    mailboxes.value.push(data)
    return data
  }

  async function updateMailbox(id, payload) {
    if (!id) { console.warn('updateMailbox called without id'); return }
    const { data } = await client.put(`/email/mailboxes/${id}`, payload)
    const idx = mailboxes.value.findIndex(m => m.id === id)
    if (idx !== -1) mailboxes.value[idx] = data
    return data
  }

  async function removeMailbox(id) {
    if (!id) { console.warn('removeMailbox called without id'); return }
    await client.delete(`/email/mailboxes/${id}`)
    mailboxes.value = mailboxes.value.filter(m => m.id !== id)
  }

  async function fetchAliases() {
    loading.value = true
    try {
      const { data } = await client.get('/email/aliases')
      aliases.value = Array.isArray(data) ? data : (data.aliases || data.items || [])
    } finally {
      loading.value = false
    }
  }

  async function createAlias(payload) {
    const { data } = await client.post('/email/aliases', payload)
    aliases.value.push(data)
    return data
  }

  async function updateAlias(id, payload) {
    if (!id) { console.warn('updateAlias called without id'); return }
    const { data } = await client.put(`/email/aliases/${id}`, payload)
    const idx = aliases.value.findIndex(a => a.id === id)
    if (idx !== -1) aliases.value[idx] = data
    return data
  }

  async function removeAlias(id) {
    if (!id) { console.warn('removeAlias called without id'); return }
    await client.delete(`/email/aliases/${id}`)
    aliases.value = aliases.value.filter(a => a.id !== id)
  }

  return {
    mailboxes, aliases, loading,
    fetchMailboxes, createMailbox, updateMailbox, removeMailbox,
    fetchAliases, createAlias, updateAlias, removeAlias
  }
})
