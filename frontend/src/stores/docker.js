import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'

export const useDockerStore = defineStore('docker', () => {
  const containers = ref([])
  const loading = ref(false)
  const dockerAvailable = ref(true)

  async function fetchContainers() {
    loading.value = true
    try {
      const { data } = await client.get('/docker/containers')
      containers.value = data
      dockerAvailable.value = true
      return data
    } catch (err) {
      if (err.response?.status === 503) {
        dockerAvailable.value = false
      }
      throw err
    } finally {
      loading.value = false
    }
  }

  async function deployContainer(payload) {
    const { data } = await client.post('/docker/containers', payload)
    const notify = useNotificationsStore()
    notify.success(`Container "${payload.name}" deployed`)
    await fetchContainers()
    return data
  }

  async function startContainer(id) {
    const { data } = await client.post(`/docker/containers/${id}/start`)
    const notify = useNotificationsStore()
    notify.success('Container started')
    await fetchContainers()
    return data
  }

  async function stopContainer(id) {
    const { data } = await client.post(`/docker/containers/${id}/stop`)
    const notify = useNotificationsStore()
    notify.success('Container stopped')
    await fetchContainers()
    return data
  }

  async function restartContainer(id) {
    const { data } = await client.post(`/docker/containers/${id}/restart`)
    const notify = useNotificationsStore()
    notify.success('Container restarted')
    await fetchContainers()
    return data
  }

  async function removeContainer(id) {
    const { data } = await client.delete(`/docker/containers/${id}`)
    const notify = useNotificationsStore()
    notify.success('Container removed')
    await fetchContainers()
    return data
  }

  async function getContainerLogs(id) {
    const { data } = await client.get(`/docker/containers/${id}/logs`)
    return data
  }

  async function getContainerStats(id) {
    const { data } = await client.get(`/docker/containers/${id}/stats`)
    return data
  }

  async function deployCompose(yaml) {
    const { data } = await client.post('/docker/compose', { yaml })
    const notify = useNotificationsStore()
    notify.success('Compose stack deployed')
    await fetchContainers()
    return data
  }

  return {
    containers,
    loading,
    dockerAvailable,
    fetchContainers,
    deployContainer,
    startContainer,
    stopContainer,
    restartContainer,
    removeContainer,
    getContainerLogs,
    getContainerStats,
    deployCompose
  }
})
