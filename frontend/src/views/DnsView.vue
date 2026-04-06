<template>
  <div>
    <!-- Header -->
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold text-text-primary">DNS Zones</h1>
        <p class="text-sm text-text-muted mt-1">Manage your DNS zones and records</p>
      </div>
      <div class="flex items-center gap-3">
        <button class="btn-secondary" @click="showImport = true">
          &#8681; Import Zone
        </button>
        <button class="btn-secondary" @click="exportAllZones">
          &#8682; Export All
        </button>
        <button class="btn-primary" @click="showAddZone = true">
          &#43; Add Zone
        </button>
      </div>
    </div>

    <!-- Zones Table -->
    <DataTable
      :columns="columns"
      :rows="dns.zones"
      :loading="dns.loading"
      empty-text="No DNS zones found. Add your first zone to get started."
    >
      <template #cell-name="{ row }">
        <button
          class="text-primary font-medium hover:underline text-left"
          @click="goToZone(row)"
        >
          {{ row.name }}
        </button>
      </template>
      <template #cell-records_count="{ value }">
        <span class="badge badge-info">{{ value }} records</span>
      </template>
      <template #cell-status="{ row }">
        <StatusBadge :status="row.status" :label="row.status" />
      </template>
      <template #actions="{ row }">
        <div class="flex items-center justify-end gap-1 flex-wrap">
          <button class="btn-ghost text-xs px-2 py-1.5 min-h-[36px]" @click="exportZone(row)">
            Export
          </button>
          <button class="btn-ghost text-xs px-2 py-1.5 min-h-[36px]" @click="goToZone(row)">
            Manage
          </button>
          <button
            class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] text-error hover:text-error"
            @click="confirmDelete(row)"
          >
            Delete
          </button>
        </div>
      </template>
    </DataTable>

    <!-- Add Zone Modal -->
    <Modal v-model="showAddZone" title="Add DNS Zone" size="md">
      <form @submit.prevent="addZone" class="space-y-4">
        <div>
          <label class="input-label">Domain Name</label>
          <input
            v-model="newZone.name"
            type="text"
            class="w-full"
            placeholder="example.com"
            required
          />
        </div>
        <div>
          <label class="input-label">Primary IP Address</label>
          <input
            v-model="newZone.primary_ip"
            type="text"
            class="w-full"
            placeholder="192.168.1.1"
            required
          />
        </div>
      </form>
      <template #actions>
        <button class="btn-secondary" @click="showAddZone = false">Cancel</button>
        <button class="btn-primary" :disabled="addingZone" @click="addZone">
          <span v-if="addingZone" class="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full"></span>
          {{ addingZone ? 'Creating...' : 'Create Zone' }}
        </button>
      </template>
    </Modal>

    <!-- Import Zone Modal -->
    <Modal v-model="showImport" title="Import DNS Zone" size="md">
      <div class="space-y-4">
        <div>
          <label class="input-label">Zone File Contents</label>
          <textarea
            v-model="importData"
            class="w-full font-mono text-xs"
            rows="10"
            placeholder="Paste your BIND zone file contents here..."
          ></textarea>
        </div>
        <p class="text-xs text-text-muted">
          Supports standard BIND zone file format. Records will be parsed and added to a new zone.
        </p>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showImport = false">Cancel</button>
        <button class="btn-primary" :disabled="importing" @click="importZone">
          {{ importing ? 'Importing...' : 'Import Zone' }}
        </button>
      </template>
    </Modal>

    <!-- Delete Confirm -->
    <ConfirmDialog
      v-model="showDeleteConfirm"
      title="Delete DNS Zone"
      :message="`Are you sure you want to delete zone '${zoneToDelete?.name}'? All records in this zone will be permanently removed.`"
      confirm-text="Delete Zone"
      :destructive="true"
      @confirm="deleteZone"
    />

    <!-- DNS Cluster Section (Admin Only) -->
    <template v-if="auth.isAdmin">
      <div class="mt-10">
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-xl font-semibold text-text-primary">DNS Cluster</h2>
            <p class="text-sm text-text-muted mt-1">
              Manage cluster nodes for multi-server DNS zone transfers
            </p>
          </div>
          <div class="flex items-center gap-3">
            <button
              class="btn-secondary"
              :disabled="dns.clusterSyncing"
              @click="triggerClusterSync"
            >
              <span v-if="dns.clusterSyncing" class="animate-spin inline-block w-4 h-4 border-2 border-current border-t-transparent rounded-full mr-2"></span>
              {{ dns.clusterSyncing ? 'Syncing...' : 'Sync All Zones' }}
            </button>
            <button class="btn-primary" @click="showAddNode = true">
              &#43; Add Node
            </button>
          </div>
        </div>

        <!-- Cluster Status Summary -->
        <div v-if="dns.clusterStatus" class="grid grid-cols-3 gap-4 mb-4">
          <div class="card p-4">
            <div class="text-sm text-text-muted">Active Nodes</div>
            <div class="text-2xl font-bold text-text-primary mt-1">
              {{ dns.clusterNodes.filter(n => n.is_active).length }}
            </div>
          </div>
          <div class="card p-4">
            <div class="text-sm text-text-muted">Total Zones</div>
            <div class="text-2xl font-bold text-text-primary mt-1">
              {{ dns.clusterStatus.total_zones || 0 }}
            </div>
          </div>
          <div class="card p-4">
            <div class="text-sm text-text-muted">Last Full Sync</div>
            <div class="text-lg font-medium text-text-primary mt-1">
              {{ dns.clusterStatus.last_full_sync ? new Date(dns.clusterStatus.last_full_sync).toLocaleString() : 'Never' }}
            </div>
          </div>
        </div>

        <!-- Cluster Nodes Table -->
        <div class="card overflow-hidden">
          <div v-if="dns.clusterLoading" class="flex items-center justify-center py-8">
            <span class="animate-spin inline-block w-6 h-6 border-2 border-primary border-t-transparent rounded-full"></span>
            <span class="ml-2 text-text-muted">Loading cluster nodes...</span>
          </div>
          <table v-else-if="dns.clusterNodes.length" class="w-full text-sm">
            <thead>
              <tr class="border-b border-border bg-surface-secondary">
                <th class="text-left p-3 font-medium text-text-muted">Hostname</th>
                <th class="text-left p-3 font-medium text-text-muted">IP Address</th>
                <th class="text-left p-3 font-medium text-text-muted">Port</th>
                <th class="text-left p-3 font-medium text-text-muted">Role</th>
                <th class="text-left p-3 font-medium text-text-muted">Status</th>
                <th class="text-left p-3 font-medium text-text-muted">Last Sync</th>
                <th class="text-right p-3 font-medium text-text-muted">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="node in dns.clusterNodes"
                :key="node.id"
                class="border-b border-border last:border-0 hover:bg-surface-secondary/50"
              >
                <td class="p-3 font-medium text-text-primary">{{ node.hostname }}</td>
                <td class="p-3 text-text-secondary font-mono text-xs">{{ node.ip_address }}</td>
                <td class="p-3 text-text-secondary">{{ node.port }}</td>
                <td class="p-3">
                  <span
                    class="badge text-xs"
                    :class="node.role === 'master' ? 'badge-primary' : 'badge-info'"
                  >
                    {{ node.role }}
                  </span>
                </td>
                <td class="p-3">
                  <span
                    class="inline-flex items-center gap-1.5"
                  >
                    <span
                      class="w-2 h-2 rounded-full"
                      :class="node.is_active ? 'bg-green-500' : 'bg-red-500'"
                    ></span>
                    <span :class="node.is_active ? 'text-green-600' : 'text-red-500'">
                      {{ node.is_active ? 'Active' : 'Inactive' }}
                    </span>
                  </span>
                </td>
                <td class="p-3 text-text-muted text-xs">
                  {{ node.last_sync_at ? new Date(node.last_sync_at).toLocaleString() : 'Never' }}
                </td>
                <td class="p-3 text-right">
                  <button
                    class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] text-error hover:text-error"
                    @click="confirmDeleteNode(node)"
                  >
                    Remove
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else class="py-8 text-center text-text-muted">
            No cluster nodes configured. Add a node to enable DNS clustering.
          </div>
        </div>
      </div>
    </template>

    <!-- Add Node Modal -->
    <Modal v-model="showAddNode" title="Add Cluster Node" size="md">
      <form @submit.prevent="addClusterNode" class="space-y-4">
        <div>
          <label class="input-label">Hostname</label>
          <input
            v-model="newNode.hostname"
            type="text"
            class="w-full"
            placeholder="ns2.example.com"
            required
          />
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="input-label">IP Address</label>
            <input
              v-model="newNode.ip_address"
              type="text"
              class="w-full"
              placeholder="10.0.0.2"
              required
            />
          </div>
          <div>
            <label class="input-label">Port</label>
            <input
              v-model.number="newNode.port"
              type="number"
              class="w-full"
              min="1"
              max="65535"
            />
          </div>
        </div>
        <div>
          <label class="input-label">API URL</label>
          <input
            v-model="newNode.api_url"
            type="url"
            class="w-full"
            placeholder="https://ns2.example.com:8443/api/v1"
            required
          />
        </div>
        <div>
          <label class="input-label">API Key</label>
          <input
            v-model="newNode.api_key"
            type="password"
            class="w-full"
            placeholder="Shared secret for authentication"
            required
          />
        </div>
        <div>
          <label class="input-label">Role</label>
          <select v-model="newNode.role" class="w-full">
            <option value="slave">Slave</option>
            <option value="master">Master</option>
          </select>
        </div>
      </form>
      <template #actions>
        <button class="btn-secondary" @click="showAddNode = false">Cancel</button>
        <button class="btn-primary" :disabled="addingNode" @click="addClusterNode">
          <span v-if="addingNode" class="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full"></span>
          {{ addingNode ? 'Adding...' : 'Add Node' }}
        </button>
      </template>
    </Modal>

    <!-- Delete Node Confirm -->
    <ConfirmDialog
      v-model="showDeleteNodeConfirm"
      title="Remove Cluster Node"
      :message="`Are you sure you want to remove node '${nodeToDelete?.hostname}'? Zone transfers to this node will stop.`"
      confirm-text="Remove Node"
      :destructive="true"
      @confirm="deleteClusterNode"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useDnsStore } from '@/stores/dns'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'
import DataTable from '@/components/DataTable.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const router = useRouter()
const dns = useDnsStore()
const auth = useAuthStore()
const notifications = useNotificationsStore()

const columns = [
  { key: 'name', label: 'Zone Name' },
  { key: 'records_count', label: 'Records' },
  { key: 'status', label: 'Status' }
]

const showAddZone = ref(false)
const showImport = ref(false)
const showDeleteConfirm = ref(false)
const addingZone = ref(false)
const importing = ref(false)
const zoneToDelete = ref(null)
const importData = ref('')
const newZone = ref({ name: '', primary_ip: '' })

// Cluster state
const showAddNode = ref(false)
const showDeleteNodeConfirm = ref(false)
const addingNode = ref(false)
const nodeToDelete = ref(null)
const newNode = ref({
  hostname: '',
  ip_address: '',
  port: 53,
  api_url: '',
  api_key: '',
  role: 'slave'
})

onMounted(() => {
  dns.fetchZones()
  if (auth.isAdmin) {
    dns.clusterFetchStatus()
  }
})

function goToZone(zone) {
  router.push({ name: 'dns-zone-detail', params: { id: zone.id } })
}

async function addZone() {
  if (!newZone.value.name || !newZone.value.primary_ip) return
  addingZone.value = true
  try {
    await dns.createZone(newZone.value)
    notifications.success(`Zone "${newZone.value.name}" created successfully`)
    showAddZone.value = false
    newZone.value = { name: '', primary_ip: '' }
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to create zone')
  } finally {
    addingZone.value = false
  }
}

async function importZone() {
  if (!importData.value.trim()) return
  importing.value = true
  try {
    const { data } = await (await import('@/api/client')).default.post('/dns/zones/import', {
      zone_file: importData.value
    })
    dns.zones.push(data)
    notifications.success('Zone imported successfully')
    showImport.value = false
    importData.value = ''
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to import zone')
  } finally {
    importing.value = false
  }
}

function exportZone(zone) {
  if (!zone?.id) return
  const url = `/api/v1/dns/zones/${zone.id}/export`
  const link = document.createElement('a')
  link.href = url
  link.download = `${zone.name}.zone`
  link.click()
  notifications.info(`Exporting zone "${zone.name}"`)
}

function exportAllZones() {
  const url = '/api/v1/dns/zones/export'
  const link = document.createElement('a')
  link.href = url
  link.download = 'dns-zones.zip'
  link.click()
  notifications.info('Exporting all zones')
}

function confirmDelete(zone) {
  zoneToDelete.value = zone
  showDeleteConfirm.value = true
}

async function deleteZone() {
  if (!zoneToDelete.value) return
  try {
    await dns.removeZone(zoneToDelete.value.id)
    notifications.success(`Zone "${zoneToDelete.value.name}" deleted`)
    zoneToDelete.value = null
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to delete zone')
  }
}

// --- DNS Cluster ---

async function addClusterNode() {
  if (!newNode.value.hostname || !newNode.value.ip_address || !newNode.value.api_url || !newNode.value.api_key) return
  addingNode.value = true
  try {
    await dns.clusterAddNode(newNode.value)
    notifications.success(`Node "${newNode.value.hostname}" added to cluster`)
    showAddNode.value = false
    newNode.value = { hostname: '', ip_address: '', port: 53, api_url: '', api_key: '', role: 'slave' }
    dns.clusterFetchStatus()
  } catch (err) {
    notifications.error(err.response?.data?.detail || err.response?.data?.message || 'Failed to add node')
  } finally {
    addingNode.value = false
  }
}

function confirmDeleteNode(node) {
  nodeToDelete.value = node
  showDeleteNodeConfirm.value = true
}

async function deleteClusterNode() {
  if (!nodeToDelete.value) return
  try {
    await dns.clusterRemoveNode(nodeToDelete.value.id)
    notifications.success(`Node "${nodeToDelete.value.hostname}" removed from cluster`)
    nodeToDelete.value = null
    dns.clusterFetchStatus()
  } catch (err) {
    notifications.error(err.response?.data?.detail || err.response?.data?.message || 'Failed to remove node')
  }
}

async function triggerClusterSync() {
  try {
    const result = await dns.clusterSync()
    notifications.success(result?.detail || 'Cluster sync complete')
  } catch (err) {
    notifications.error(err.response?.data?.detail || err.response?.data?.message || 'Cluster sync failed')
  }
}
</script>
