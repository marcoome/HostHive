import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'

export const useDnsStore = defineStore('dns', () => {
  const zones = ref([])
  const records = ref([])
  const currentZone = ref(null)
  const loading = ref(false)

  async function fetchZones() {
    loading.value = true
    try {
      const { data } = await client.get('/dns/zones')
      zones.value = data
    } finally {
      loading.value = false
    }
  }

  async function fetchZone(id) {
    loading.value = true
    try {
      const { data } = await client.get(`/dns/zones/${id}`)
      currentZone.value = data
      return data
    } finally {
      loading.value = false
    }
  }

  async function createZone(payload) {
    const { data } = await client.post('/dns/zones', payload)
    zones.value.push(data)
    return data
  }

  async function updateZone(id, payload) {
    const { data } = await client.put(`/dns/zones/${id}`, payload)
    const idx = zones.value.findIndex(z => z.id === id)
    if (idx !== -1) zones.value[idx] = data
    return data
  }

  async function removeZone(id) {
    await client.delete(`/dns/zones/${id}`)
    zones.value = zones.value.filter(z => z.id !== id)
  }

  async function fetchRecords(zoneId) {
    loading.value = true
    try {
      const { data } = await client.get(`/dns/zones/${zoneId}/records`)
      records.value = data
    } finally {
      loading.value = false
    }
  }

  async function createRecord(zoneId, payload) {
    const { data } = await client.post(`/dns/zones/${zoneId}/records`, payload)
    records.value.push(data)
    return data
  }

  async function updateRecord(zoneId, recordId, payload) {
    const { data } = await client.put(`/dns/zones/${zoneId}/records/${recordId}`, payload)
    const idx = records.value.findIndex(r => r.id === recordId)
    if (idx !== -1) records.value[idx] = data
    return data
  }

  async function removeRecord(zoneId, recordId) {
    await client.delete(`/dns/zones/${zoneId}/records/${recordId}`)
    records.value = records.value.filter(r => r.id !== recordId)
  }

  return {
    zones, records, currentZone, loading,
    fetchZones, fetchZone, createZone, updateZone, removeZone,
    fetchRecords, createRecord, updateRecord, removeRecord
  }
})
