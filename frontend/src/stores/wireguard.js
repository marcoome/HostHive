import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'

export const useWireguardStore = defineStore('wireguard', () => {
  const status = ref(null)
  const peers = ref([])
  const loading = ref(false)
  const statusLoading = ref(false)

  async function fetchStatus() {
    statusLoading.value = true
    try {
      const { data } = await client.get('/wireguard/status')
      status.value = data
      return data
    } catch (err) {
      status.value = null
      throw err
    } finally {
      statusLoading.value = false
    }
  }

  async function fetchPeers() {
    loading.value = true
    try {
      const { data } = await client.get('/wireguard/peers')
      peers.value = Array.isArray(data) ? data : []
      return data
    } catch (err) {
      peers.value = []
      throw err
    } finally {
      loading.value = false
    }
  }

  async function addPeer(payload) {
    const { data } = await client.post('/wireguard/peers', payload)
    const notify = useNotificationsStore()
    notify.success(`Peer "${payload.name}" created`)
    await fetchPeers()
    return data
  }

  async function removePeer(peerId) {
    if (!peerId) { console.warn('removePeer called without id'); return }
    await client.delete(`/wireguard/peers/${peerId}`)
    const notify = useNotificationsStore()
    notify.success('Peer removed')
    await fetchPeers()
  }

  async function downloadConfig(peerId) {
    if (!peerId) return
    try {
      const { data } = await client.get(`/wireguard/peers/${peerId}/config`, {
        responseType: 'text'
      })
      return data
    } catch (err) {
      const notify = useNotificationsStore()
      notify.error('Failed to download config')
      throw err
    }
  }

  async function getQrCode(peerId) {
    if (!peerId) return
    try {
      const response = await client.get(`/wireguard/peers/${peerId}/qr`, {
        responseType: 'arraybuffer'
      })
      const blob = new Blob([response.data], { type: 'image/png' })
      return URL.createObjectURL(blob)
    } catch (err) {
      const notify = useNotificationsStore()
      notify.error('Failed to generate QR code')
      throw err
    }
  }

  async function fetchTrafficStats() {
    // Traffic stats come embedded in the peers list (transfer_rx / transfer_tx)
    await fetchPeers()
    return peers.value.map(p => ({
      id: p.id,
      name: p.name,
      transfer_rx: p.transfer_rx || 0,
      transfer_tx: p.transfer_tx || 0
    }))
  }

  return {
    status,
    peers,
    loading,
    statusLoading,
    fetchStatus,
    fetchPeers,
    addPeer,
    removePeer,
    downloadConfig,
    getQrCode,
    fetchTrafficStats
  }
})
