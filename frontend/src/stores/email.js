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

  async function getAutoresponder(id) {
    const { data } = await client.get(`/email/${id}/autoresponder`)
    return data
  }

  async function updateAutoresponder(id, payload) {
    const { data } = await client.put(`/email/${id}/autoresponder`, payload)
    // Update local mailbox autoresponder_enabled flag
    const idx = mailboxes.value.findIndex(m => m.id === id)
    if (idx !== -1) mailboxes.value[idx].autoresponder_enabled = payload.enabled
    return data
  }

  async function disableAutoresponder(id) {
    const { data } = await client.delete(`/email/${id}/autoresponder`)
    const idx = mailboxes.value.findIndex(m => m.id === id)
    if (idx !== -1) mailboxes.value[idx].autoresponder_enabled = false
    return data
  }

  async function changePassword(id, newPassword) {
    if (!id) { console.warn('changePassword called without id'); return }
    const { data } = await client.put(`/email/${id}/password`, { new_password: newPassword })
    return data
  }

  async function getQuota(id) {
    if (!id) { console.warn('getQuota called without id'); return }
    const { data } = await client.get(`/email/${id}/quota`)
    const idx = mailboxes.value.findIndex(m => m.id === id)
    if (idx !== -1) {
      mailboxes.value[idx].quota_used_mb = data.quota_used_mb
    }
    return data
  }

  async function updateRateLimit(id, maxPerHour) {
    if (!id) { console.warn('updateRateLimit called without id'); return }
    const { data } = await client.put(`/email/${id}/rate-limit`, { max_emails_per_hour: maxPerHour })
    const idx = mailboxes.value.findIndex(m => m.id === id)
    if (idx !== -1) {
      mailboxes.value[idx].max_emails_per_hour = data.max_emails_per_hour
    }
    return data
  }

  // Mailing list state
  const mailingLists = ref([])

  async function fetchMailingLists() {
    loading.value = true
    try {
      const { data } = await client.get('/email/lists')
      mailingLists.value = Array.isArray(data) ? data : (data.items || [])
    } finally {
      loading.value = false
    }
  }

  async function createMailingList(payload) {
    const { data } = await client.post('/email/lists', payload)
    mailingLists.value.push(data)
    return data
  }

  async function getMailingList(id) {
    const { data } = await client.get(`/email/lists/${id}`)
    return data
  }

  async function updateMailingList(id, payload) {
    if (!id) { console.warn('updateMailingList called without id'); return }
    const { data } = await client.put(`/email/lists/${id}`, payload)
    const idx = mailingLists.value.findIndex(l => l.id === id)
    if (idx !== -1) mailingLists.value[idx] = data
    return data
  }

  async function removeMailingList(id) {
    if (!id) { console.warn('removeMailingList called without id'); return }
    await client.delete(`/email/lists/${id}`)
    mailingLists.value = mailingLists.value.filter(l => l.id !== id)
  }

  async function addListMembers(listId, payload) {
    const { data } = await client.post(`/email/lists/${listId}/members`, payload)
    return data
  }

  async function removeListMember(listId, memberId) {
    await client.delete(`/email/lists/${listId}/members/${memberId}`)
  }

  async function sendToList(listId, payload) {
    const { data } = await client.post(`/email/lists/${listId}/send`, payload)
    return data
  }

  // Sieve filter methods
  async function getSieveFilters(id) {
    if (!id) { console.warn('getSieveFilters called without id'); return }
    const { data } = await client.get(`/email/accounts/${id}/filters`)
    return data
  }

  async function saveSieveFilters(id, payload) {
    if (!id) { console.warn('saveSieveFilters called without id'); return }
    const { data } = await client.put(`/email/accounts/${id}/filters`, payload)
    return data
  }

  async function testSieveScript(id, script) {
    if (!id) { console.warn('testSieveScript called without id'); return }
    const { data } = await client.post(`/email/accounts/${id}/filters/test`, { script })
    return data
  }

  // Deliverability test methods
  const deliverabilityReport = ref(null)
  const deliverabilityLoading = ref(false)

  async function runDeliverabilityTest(domain) {
    deliverabilityLoading.value = true
    try {
      const { data } = await client.post('/email/deliverability/test', { domain })
      deliverabilityReport.value = data
      return data
    } finally {
      deliverabilityLoading.value = false
    }
  }

  async function fetchDeliverabilityReport(domain) {
    deliverabilityLoading.value = true
    try {
      const { data } = await client.get(`/email/deliverability/report/${domain}`)
      deliverabilityReport.value = data
      return data
    } finally {
      deliverabilityLoading.value = false
    }
  }

  // Spam filter methods
  async function fetchSpamSettings(id) {
    if (!id) { console.warn('fetchSpamSettings called without id'); return }
    const { data } = await client.get(`/email/accounts/${id}/spam`)
    return data
  }

  async function updateSpamSettings(id, payload) {
    if (!id) { console.warn('updateSpamSettings called without id'); return }
    const { data } = await client.put(`/email/accounts/${id}/spam`, payload)
    return data
  }

  return {
    mailboxes, aliases, loading, mailingLists,
    fetchMailboxes, createMailbox, updateMailbox, removeMailbox,
    fetchAliases, createAlias, updateAlias, removeAlias,
    getAutoresponder, updateAutoresponder, disableAutoresponder,
    changePassword, getQuota, updateRateLimit,
    getSieveFilters, saveSieveFilters, testSieveScript,
    fetchSpamSettings, updateSpamSettings,
    deliverabilityReport, deliverabilityLoading,
    runDeliverabilityTest, fetchDeliverabilityReport,
    fetchMailingLists, createMailingList, getMailingList,
    updateMailingList, removeMailingList,
    addListMembers, removeListMember, sendToList
  }
})
