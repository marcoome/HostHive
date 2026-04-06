import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'

export const useDnsStore = defineStore('dns', () => {
  const zones = ref([])
  const records = ref([])
  const currentZone = ref(null)
  const loading = ref(false)

  // Cloudflare state
  const cfStatus = ref({ enabled: false, cf_zone_id: null, email: null })
  const cfLoading = ref(false)

  // DNSSEC state
  const dnssecStatus = ref({ enabled: false, algorithm: null, ds_record: null })
  const dnssecLoading = ref(false)

  // DNS Cluster state
  const clusterNodes = ref([])
  const clusterStatus = ref(null)
  const clusterLoading = ref(false)
  const clusterSyncing = ref(false)

  async function fetchZones() {
    loading.value = true
    try {
      const { data } = await client.get('/dns/zones')
      zones.value = Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : [])
    } finally {
      loading.value = false
    }
  }

  async function fetchZone(id) {
    if (!id) { console.warn('dns.fetchZone called without id'); return }
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
    if (!id) { console.warn('dns.updateZone called without id'); return }
    const { data } = await client.put(`/dns/zones/${id}`, payload)
    const idx = zones.value.findIndex(z => z.id === id)
    if (idx !== -1) zones.value[idx] = data
    return data
  }

  async function removeZone(id) {
    if (!id) { console.warn('dns.removeZone called without id'); return }
    await client.delete(`/dns/zones/${id}`)
    zones.value = zones.value.filter(z => z.id !== id)
  }

  async function fetchRecords(zoneId) {
    if (!zoneId) { console.warn('dns.fetchRecords called without zoneId'); return }
    loading.value = true
    try {
      const { data } = await client.get(`/dns/zones/${zoneId}/records`)
      records.value = Array.isArray(data) ? data : []
    } finally {
      loading.value = false
    }
  }

  async function createRecord(zoneId, payload) {
    if (!zoneId) { console.warn('dns.createRecord called without zoneId'); return }
    const { data } = await client.post(`/dns/zones/${zoneId}/records`, payload)
    records.value.push(data)
    return data
  }

  async function updateRecord(zoneId, recordId, payload) {
    if (!zoneId || !recordId) { console.warn('dns.updateRecord called without zoneId or recordId'); return }
    const { data } = await client.put(`/dns/zones/${zoneId}/records/${recordId}`, payload)
    const idx = records.value.findIndex(r => r.id === recordId)
    if (idx !== -1) records.value[idx] = data
    return data
  }

  async function removeRecord(zoneId, recordId) {
    if (!zoneId || !recordId) { console.warn('dns.removeRecord called without zoneId or recordId'); return }
    await client.delete(`/dns/zones/${zoneId}/records/${recordId}`)
    records.value = records.value.filter(r => r.id !== recordId)
  }

  // ----- Cloudflare actions -----

  async function cfFetchStatus(zoneId) {
    if (!zoneId) return
    cfLoading.value = true
    try {
      const { data } = await client.get(`/dns/zones/${zoneId}/cloudflare/status`)
      cfStatus.value = data
      return data
    } finally {
      cfLoading.value = false
    }
  }

  async function cfEnable(zoneId, payload) {
    if (!zoneId) return
    cfLoading.value = true
    try {
      const { data } = await client.post(`/dns/zones/${zoneId}/cloudflare/enable`, payload)
      cfStatus.value = { enabled: true, cf_zone_id: payload.cf_zone_id, email: payload.email }
      if (currentZone.value) currentZone.value.cloudflare_enabled = true
      return data
    } finally {
      cfLoading.value = false
    }
  }

  async function cfDisable(zoneId) {
    if (!zoneId) return
    cfLoading.value = true
    try {
      const { data } = await client.delete(`/dns/zones/${zoneId}/cloudflare/disable`)
      cfStatus.value = { enabled: false, cf_zone_id: null, email: null }
      if (currentZone.value) currentZone.value.cloudflare_enabled = false
      return data
    } finally {
      cfLoading.value = false
    }
  }

  async function cfSync(zoneId) {
    if (!zoneId) return
    cfLoading.value = true
    try {
      const { data } = await client.post(`/dns/zones/${zoneId}/cloudflare/sync`)
      return data
    } finally {
      cfLoading.value = false
    }
  }

  async function cfImport(zoneId) {
    if (!zoneId) return
    cfLoading.value = true
    try {
      const { data } = await client.post(`/dns/zones/${zoneId}/cloudflare/import`)
      // Refresh records after import
      await fetchRecords(zoneId)
      return data
    } finally {
      cfLoading.value = false
    }
  }

  async function cfToggleProxy(zoneId, recordId, proxied) {
    if (!zoneId || !recordId) return
    const { data } = await client.put(
      `/dns/zones/${zoneId}/cloudflare/proxy/${recordId}`,
      { proxied }
    )
    return data
  }

  // ----- DNSSEC actions -----

  async function dnssecFetchStatus(zoneId) {
    if (!zoneId) return
    dnssecLoading.value = true
    try {
      const { data } = await client.get(`/dns/zones/${zoneId}/dnssec/status`)
      dnssecStatus.value = data
      return data
    } finally {
      dnssecLoading.value = false
    }
  }

  async function dnssecEnable(zoneId, payload = {}) {
    if (!zoneId) return
    dnssecLoading.value = true
    try {
      const { data } = await client.post(`/dns/zones/${zoneId}/dnssec/enable`, payload)
      dnssecStatus.value = {
        enabled: true,
        algorithm: data.algorithm || payload.algorithm || 'ECDSAP256SHA256',
        ds_record: data.ds_record || null,
      }
      if (currentZone.value) currentZone.value.dnssec_enabled = true
      return data
    } finally {
      dnssecLoading.value = false
    }
  }

  async function dnssecDisable(zoneId) {
    if (!zoneId) return
    dnssecLoading.value = true
    try {
      const { data } = await client.delete(`/dns/zones/${zoneId}/dnssec/disable`)
      dnssecStatus.value = { enabled: false, algorithm: null, ds_record: null }
      if (currentZone.value) currentZone.value.dnssec_enabled = false
      return data
    } finally {
      dnssecLoading.value = false
    }
  }

  async function dnssecFetchDsRecord(zoneId) {
    if (!zoneId) return
    dnssecLoading.value = true
    try {
      const { data } = await client.get(`/dns/zones/${zoneId}/dnssec/ds-record`)
      if (data.ds_record) {
        dnssecStatus.value = { ...dnssecStatus.value, ds_record: data.ds_record }
      }
      return data
    } finally {
      dnssecLoading.value = false
    }
  }

  // ----- DNS Cluster actions -----

  async function clusterFetchNodes() {
    clusterLoading.value = true
    try {
      const { data } = await client.get('/dns/cluster/nodes')
      clusterNodes.value = Array.isArray(data?.items) ? data.items : (Array.isArray(data) ? data : [])
      return data
    } finally {
      clusterLoading.value = false
    }
  }

  async function clusterFetchStatus() {
    clusterLoading.value = true
    try {
      const { data } = await client.get('/dns/cluster/status')
      clusterStatus.value = data
      clusterNodes.value = Array.isArray(data?.nodes) ? data.nodes : []
      return data
    } finally {
      clusterLoading.value = false
    }
  }

  async function clusterAddNode(payload) {
    const { data } = await client.post('/dns/cluster/nodes', payload)
    clusterNodes.value.push(data)
    return data
  }

  async function clusterRemoveNode(nodeId) {
    if (!nodeId) return
    await client.delete(`/dns/cluster/nodes/${nodeId}`)
    clusterNodes.value = clusterNodes.value.filter(n => n.id !== nodeId)
  }

  async function clusterSync() {
    clusterSyncing.value = true
    try {
      const { data } = await client.post('/dns/cluster/sync')
      // Refresh status after sync
      await clusterFetchStatus()
      return data
    } finally {
      clusterSyncing.value = false
    }
  }

  return {
    zones, records, currentZone, loading,
    cfStatus, cfLoading,
    dnssecStatus, dnssecLoading,
    clusterNodes, clusterStatus, clusterLoading, clusterSyncing,
    fetchZones, fetchZone, createZone, updateZone, removeZone,
    fetchRecords, createRecord, updateRecord, removeRecord,
    cfFetchStatus, cfEnable, cfDisable, cfSync, cfImport, cfToggleProxy,
    dnssecFetchStatus, dnssecEnable, dnssecDisable, dnssecFetchDsRecord,
    clusterFetchNodes, clusterFetchStatus, clusterAddNode, clusterRemoveNode, clusterSync
  }
})
