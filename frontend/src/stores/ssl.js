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
      const { data } = await client.get('/ssl/certificates')
      certificates.value = data
    } finally {
      loading.value = false
    }
  }

  async function issueCertificate(payload) {
    const { data } = await client.post('/ssl/certificates', payload)
    certificates.value.push(data)
    return data
  }

  async function uploadCertificate(payload) {
    const { data } = await client.post('/ssl/certificates/upload', payload)
    certificates.value.push(data)
    return data
  }

  async function renewCertificate(id) {
    const { data } = await client.post(`/ssl/certificates/${id}/renew`)
    const idx = certificates.value.findIndex(c => c.id === id)
    if (idx !== -1) certificates.value[idx] = data
    return data
  }

  async function revokeCertificate(id) {
    await client.post(`/ssl/certificates/${id}/revoke`)
    const idx = certificates.value.findIndex(c => c.id === id)
    if (idx !== -1) certificates.value[idx].status = 'revoked'
  }

  async function toggleAutoRenew(id) {
    const { data } = await client.post(`/ssl/certificates/${id}/auto-renew`)
    const idx = certificates.value.findIndex(c => c.id === id)
    if (idx !== -1) certificates.value[idx] = data
    return data
  }

  async function removeCertificate(id) {
    await client.delete(`/ssl/certificates/${id}`)
    certificates.value = certificates.value.filter(c => c.id !== id)
  }

  return {
    certificates, loading, expiringCerts, daysUntilExpiry,
    fetchCertificates, issueCertificate, uploadCertificate,
    renewCertificate, revokeCertificate, toggleAutoRenew, removeCertificate
  }
})
