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
        <div class="flex items-center justify-end gap-2">
          <button class="btn-ghost text-xs px-2 py-1" @click="exportZone(row)">
            Export
          </button>
          <button class="btn-ghost text-xs px-2 py-1" @click="goToZone(row)">
            Manage
          </button>
          <button
            class="btn-ghost text-xs px-2 py-1 text-error hover:text-error"
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
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useDnsStore } from '@/stores/dns'
import { useNotificationsStore } from '@/stores/notifications'
import DataTable from '@/components/DataTable.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const router = useRouter()
const dns = useDnsStore()
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

onMounted(() => {
  dns.fetchZones()
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
</script>
