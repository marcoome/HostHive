import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import client from '@/api/client'

export const useSslStore = defineStore('ssl', () => {
  const certificates = ref([])
  const loading = ref(false)

  const expiringCerts = computed(() =>
    certificates.value.filter(c => {
      const days = daysUntilExpiry(c.expires_at)
      return days < 14 && days >= 0
    })
  )

  function daysUntilExpiry(dateStr) {
    if (!dateStr) return Infinity
    const now = new Date()
    const expiry = new Date(dateStr)
    return Math.ceil((expiry - now) / (1000 * 60 * 60 * 24))
  }

  async function fetchCertificates() {
    loading.value = true
    try {
      const { data } = await client.get('/ssl')
      certificates.value = data.items || data
    } finally {
      loading.value = false
    }
  }

  async function issueCertificate(domainId) {
    const { data } = await client.post(`/ssl/issue/${domainId}`)
    certificates.value.push(data)
    return data
  }

  async function uploadCertificate(domainId, payload) {
    const { data } = await client.post(`/ssl/install/${domainId}`, payload)
    certificates.value.push(data)
    return data
  }

  async function renewCertificate(domainId) {
    const { data } = await client.post(`/ssl/renew/${domainId}`)
    const idx = certificates.value.findIndex(c => c.domain_id === domainId)
    if (idx !== -1) certificates.value[idx] = data
    return data
  }

  // NOTE: revokeCertificate - no backend endpoint yet; wrapped in try-catch
  async function revokeCertificate(id) {
    try {
      await client.post(`/ssl/certificates/${id}/revoke`)
      const idx = certificates.value.findIndex(c => c.id === id)
      if (idx !== -1) certificates.value[idx].status = 'revoked'
    } catch {
      console.warn('SSL revoke endpoint not available')
    }
  }

  // NOTE: toggleAutoRenew - no backend endpoint yet; wrapped in try-catch
  async function toggleAutoRenew(id) {
    try {
      const { data } = await client.post(`/ssl/certificates/${id}/auto-renew`)
      const idx = certificates.value.findIndex(c => c.id === id)
      if (idx !== -1) certificates.value[idx] = data
      return data
    } catch {
      console.warn('SSL auto-renew endpoint not available')
    }
  }

  // NOTE: removeCertificate - no backend DELETE endpoint yet; wrapped in try-catch
  async function removeCertificate(id) {
    try {
      await client.delete(`/ssl/${id}`)
      certificates.value = certificates.value.filter(c => c.id !== id)
    } catch {
      console.warn('SSL delete endpoint not available')
    }
  }

  return {
    certificates, loading, expiringCerts, daysUntilExpiry,
    fetchCertificates, issueCertificate, uploadCertificate,
    renewCertificate, revokeCertificate, toggleAutoRenew, removeCertificate
  }
})
