<template>
  <div>
    <!-- Back button + Header -->
    <div class="mb-6">
      <button class="btn-ghost text-sm mb-4" @click="$router.push({ name: 'dns' })">
        &#8592; Back to DNS Zones
      </button>

      <!-- Zone header skeleton -->
      <div v-if="dns.loading && !dns.currentZone" class="glass rounded-2xl p-6">
        <LoadingSkeleton class="h-7 w-64 mb-2" />
        <LoadingSkeleton class="h-4 w-96" />
      </div>

      <!-- Zone header -->
      <div v-else-if="dns.currentZone" class="glass rounded-2xl p-6">
        <div class="flex items-center justify-between">
          <div>
            <h1 class="text-2xl font-semibold text-text-primary">{{ dns.currentZone.name }}</h1>
            <div class="flex items-center gap-4 mt-2 text-sm text-text-muted">
              <span>SOA: {{ dns.currentZone.soa_email || 'admin@' + dns.currentZone.name }}</span>
              <span>Serial: {{ dns.currentZone.serial || 'N/A' }}</span>
              <span>Refresh: {{ dns.currentZone.refresh || 3600 }}s</span>
              <span>TTL: {{ dns.currentZone.default_ttl || 3600 }}s</span>
            </div>
          </div>
          <div class="flex items-center gap-3">
            <button class="btn-secondary text-sm" @click="exportZone">
              &#8682; Export
            </button>
            <button class="btn-secondary text-sm" @click="showImport = true">
              &#8681; Import
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Add Record Form -->
    <div class="glass rounded-2xl p-6 mb-6">
      <h2 class="text-sm font-semibold text-text-primary uppercase tracking-wider mb-4">Add Record</h2>
      <form @submit.prevent="addRecord" class="flex items-end gap-3 flex-wrap">
        <div class="w-32">
          <label class="input-label">Type</label>
          <select v-model="newRecord.type" class="w-full">
            <option v-for="t in recordTypes" :key="t" :value="t">{{ t }}</option>
          </select>
        </div>
        <div class="flex-1 min-w-[140px]">
          <label class="input-label">Name</label>
          <input v-model="newRecord.name" type="text" class="w-full" placeholder="@" />
        </div>
        <div class="flex-1 min-w-[200px]">
          <label class="input-label">Value</label>
          <input v-model="newRecord.value" type="text" class="w-full" placeholder="IP address or hostname" required />
        </div>
        <div class="w-24">
          <label class="input-label">TTL</label>
          <input v-model.number="newRecord.ttl" type="number" class="w-full" min="60" />
        </div>
        <div v-if="showPriority(newRecord.type)" class="w-24">
          <label class="input-label">Priority</label>
          <input v-model.number="newRecord.priority" type="number" class="w-full" min="0" />
        </div>
        <button type="submit" class="btn-primary" :disabled="addingRecord">
          {{ addingRecord ? 'Adding...' : '+ Add' }}
        </button>
      </form>
    </div>

    <!-- Records Table -->
    <div class="card-static p-0 overflow-hidden rounded-2xl">
      <div class="px-6 py-4 border-b border-border flex items-center justify-between">
        <h2 class="text-sm font-semibold text-text-primary uppercase tracking-wider">
          DNS Records
          <span class="text-text-muted font-normal normal-case ml-2">
            ({{ dns.records.length }} total)
          </span>
        </h2>
        <div class="flex items-center gap-2">
          <input
            v-model="searchQuery"
            type="text"
            class="text-sm py-1.5 px-3"
            placeholder="Filter records..."
          />
        </div>
      </div>

      <!-- Table -->
      <div class="overflow-x-auto">
        <table class="w-full">
          <thead>
            <tr class="border-b border-border">
              <th class="px-6 py-3 text-left text-xs font-semibold text-text-muted uppercase tracking-wider w-28">Type</th>
              <th class="px-6 py-3 text-left text-xs font-semibold text-text-muted uppercase tracking-wider">Name</th>
              <th class="px-6 py-3 text-left text-xs font-semibold text-text-muted uppercase tracking-wider">Value</th>
              <th class="px-6 py-3 text-left text-xs font-semibold text-text-muted uppercase tracking-wider w-24">TTL</th>
              <th class="px-6 py-3 text-left text-xs font-semibold text-text-muted uppercase tracking-wider w-24">Priority</th>
              <th class="px-6 py-3 text-right text-xs font-semibold text-text-muted uppercase tracking-wider w-40">Actions</th>
            </tr>
          </thead>

          <!-- Loading skeleton -->
          <tbody v-if="dns.loading && dns.records.length === 0">
            <tr v-for="i in 5" :key="i" class="border-b border-border">
              <td class="px-6 py-4"><LoadingSkeleton class="h-4 w-14" /></td>
              <td class="px-6 py-4"><LoadingSkeleton class="h-4 w-24" /></td>
              <td class="px-6 py-4"><LoadingSkeleton class="h-4 w-48" /></td>
              <td class="px-6 py-4"><LoadingSkeleton class="h-4 w-12" /></td>
              <td class="px-6 py-4"><LoadingSkeleton class="h-4 w-10" /></td>
              <td class="px-6 py-4"><LoadingSkeleton class="h-4 w-20 ml-auto" /></td>
            </tr>
          </tbody>

          <!-- Empty state -->
          <tbody v-else-if="filteredRecords.length === 0">
            <tr>
              <td colspan="6" class="px-6 py-12 text-center">
                <div class="text-text-muted">
                  <div class="text-3xl mb-2">&#9744;</div>
                  <p class="text-sm">{{ searchQuery ? 'No matching records found.' : 'No records yet. Add your first record above.' }}</p>
                </div>
              </td>
            </tr>
          </tbody>

          <!-- Records -->
          <tbody v-else>
            <tr
              v-for="record in filteredRecords"
              :key="record.id"
              class="border-b border-border last:border-0 hover:bg-background/50 transition-colors group"
            >
              <!-- Type -->
              <td class="px-6 py-3 text-sm" @click="startEdit(record, 'type')">
                <select
                  v-if="editing?.id === record.id && editing.field === 'type'"
                  v-model="editing.value"
                  class="w-full text-sm py-1"
                  @blur="saveEdit(record)"
                  @change="saveEdit(record)"
                  ref="editInput"
                >
                  <option v-for="t in recordTypes" :key="t" :value="t">{{ t }}</option>
                </select>
                <span v-else class="badge badge-info cursor-pointer">{{ record.type }}</span>
              </td>

              <!-- Name -->
              <td class="px-6 py-3 text-sm" @click="startEdit(record, 'name')">
                <input
                  v-if="editing?.id === record.id && editing.field === 'name'"
                  v-model="editing.value"
                  type="text"
                  class="w-full text-sm py-1"
                  @blur="saveEdit(record)"
                  @keydown.enter="saveEdit(record)"
                  @keydown.escape="cancelEdit"
                />
                <span v-else class="font-mono text-sm cursor-pointer hover:text-primary transition-colors">
                  {{ record.name }}
                </span>
              </td>

              <!-- Value -->
              <td class="px-6 py-3 text-sm" @click="startEdit(record, 'value')">
                <input
                  v-if="editing?.id === record.id && editing.field === 'value'"
                  v-model="editing.value"
                  type="text"
                  class="w-full text-sm py-1"
                  @blur="saveEdit(record)"
                  @keydown.enter="saveEdit(record)"
                  @keydown.escape="cancelEdit"
                />
                <span v-else class="font-mono text-sm cursor-pointer hover:text-primary transition-colors break-all">
                  {{ record.value }}
                </span>
              </td>

              <!-- TTL -->
              <td class="px-6 py-3 text-sm" @click="startEdit(record, 'ttl')">
                <input
                  v-if="editing?.id === record.id && editing.field === 'ttl'"
                  v-model.number="editing.value"
                  type="number"
                  min="60"
                  class="w-full text-sm py-1"
                  @blur="saveEdit(record)"
                  @keydown.enter="saveEdit(record)"
                  @keydown.escape="cancelEdit"
                />
                <span v-else class="text-text-muted cursor-pointer hover:text-primary transition-colors">
                  {{ record.ttl }}s
                </span>
              </td>

              <!-- Priority -->
              <td class="px-6 py-3 text-sm">
                <template v-if="showPriority(record.type)">
                  <span
                    @click="startEdit(record, 'priority')"
                    class="cursor-pointer hover:text-primary transition-colors"
                  >
                    <input
                      v-if="editing?.id === record.id && editing.field === 'priority'"
                      v-model.number="editing.value"
                      type="number"
                      min="0"
                      class="w-full text-sm py-1"
                      @blur="saveEdit(record)"
                      @keydown.enter="saveEdit(record)"
                      @keydown.escape="cancelEdit"
                    />
                    <span v-else>{{ record.priority }}</span>
                  </span>
                </template>
                <span v-else class="text-text-muted">-</span>
              </td>

              <!-- Actions -->
              <td class="px-6 py-3 text-right">
                <div class="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    class="btn-ghost text-xs px-2 py-1"
                    @click="saveRecordRow(record)"
                    title="Save"
                  >
                    &#10003; Save
                  </button>
                  <button
                    class="btn-ghost text-xs px-2 py-1 text-error hover:text-error"
                    @click="confirmDeleteRecord(record)"
                    title="Delete"
                  >
                    &#10005;
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Import Modal -->
    <Modal v-model="showImport" title="Import Zone Records" size="lg">
      <div class="space-y-4">
        <div>
          <label class="input-label">Zone File Contents</label>
          <textarea
            v-model="importContent"
            class="w-full font-mono text-xs"
            rows="12"
            placeholder="Paste your BIND zone file records here..."
          ></textarea>
        </div>
        <p class="text-xs text-text-muted">
          Existing records will be preserved. Duplicate records will be skipped.
        </p>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showImport = false">Cancel</button>
        <button class="btn-primary" :disabled="importingRecords" @click="importRecords">
          {{ importingRecords ? 'Importing...' : 'Import Records' }}
        </button>
      </template>
    </Modal>

    <!-- Delete Record Confirm -->
    <ConfirmDialog
      v-model="showDeleteRecordConfirm"
      title="Delete DNS Record"
      :message="`Delete ${recordToDelete?.type} record '${recordToDelete?.name}'? This action cannot be undone.`"
      confirm-text="Delete Record"
      :destructive="true"
      @confirm="deleteRecord"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useDnsStore } from '@/stores/dns'
import { useNotificationsStore } from '@/stores/notifications'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'

const route = useRoute()
const dns = useDnsStore()
const notifications = useNotificationsStore()
const zoneId = route.params.id

const recordTypes = ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS', 'SRV']
const searchQuery = ref('')
const showImport = ref(false)
const showDeleteRecordConfirm = ref(false)
const addingRecord = ref(false)
const importingRecords = ref(false)
const importContent = ref('')
const recordToDelete = ref(null)

const newRecord = ref({
  type: 'A',
  name: '@',
  value: '',
  ttl: 3600,
  priority: 10
})

const editing = ref(null)

const filteredRecords = computed(() => {
  if (!searchQuery.value) return dns.records
  const q = searchQuery.value.toLowerCase()
  return dns.records.filter(r =>
    r.name.toLowerCase().includes(q) ||
    r.value.toLowerCase().includes(q) ||
    r.type.toLowerCase().includes(q)
  )
})

function showPriority(type) {
  return type === 'MX' || type === 'SRV'
}

onMounted(async () => {
  await Promise.all([
    dns.fetchZone(zoneId),
    dns.fetchRecords(zoneId)
  ])
})

async function addRecord() {
  if (!newRecord.value.value) return
  addingRecord.value = true
  try {
    const payload = { ...newRecord.value }
    // Backend expects record_type, frontend uses type
    if (payload.type && !payload.record_type) {
      payload.record_type = payload.type
      delete payload.type
    }
    if (!showPriority(payload.record_type || payload.type)) delete payload.priority
    await dns.createRecord(zoneId, payload)
    notifications.success(`${newRecord.value.type} record added`)
    newRecord.value = { type: 'A', name: '@', value: '', ttl: 3600, priority: 10 }
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to add record')
  } finally {
    addingRecord.value = false
  }
}

function startEdit(record, field) {
  editing.value = { id: record.id, field, value: record[field] }
  nextTick(() => {
    const inputs = document.querySelectorAll('input:focus, select:focus')
    if (inputs.length === 0) {
      const row = document.querySelector(`input[type], select`)
      if (row) row.focus()
    }
  })
}

function cancelEdit() {
  editing.value = null
}

async function saveEdit(record) {
  if (!editing.value) return
  const { field, value } = editing.value
  if (record[field] === value) {
    editing.value = null
    return
  }
  try {
    const payload = { [field]: value }
    await dns.updateRecord(zoneId, record.id, payload)
    notifications.success('Record updated')
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to update record')
  }
  editing.value = null
}

async function saveRecordRow(record) {
  try {
    const payload = {
      type: record.type,
      name: record.name,
      value: record.value,
      ttl: record.ttl
    }
    if (showPriority(record.type)) payload.priority = record.priority
    await dns.updateRecord(zoneId, record.id, payload)
    notifications.success('Record saved')
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to save record')
  }
}

function confirmDeleteRecord(record) {
  recordToDelete.value = record
  showDeleteRecordConfirm.value = true
}

async function deleteRecord() {
  if (!recordToDelete.value) return
  try {
    await dns.removeRecord(zoneId, recordToDelete.value.id)
    notifications.success('Record deleted')
    recordToDelete.value = null
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to delete record')
  }
}

function exportZone() {
  const url = `/api/v1/dns/zones/${zoneId}/export`
  const link = document.createElement('a')
  link.href = url
  link.download = `${dns.currentZone?.name || 'zone'}.zone`
  link.click()
  notifications.info('Exporting zone file')
}

async function importRecords() {
  if (!importContent.value.trim()) return
  importingRecords.value = true
  try {
    const client = (await import('@/api/client')).default
    await client.post(`/dns/zones/${zoneId}/import`, {
      zone_file: importContent.value
    })
    await dns.fetchRecords(zoneId)
    notifications.success('Records imported successfully')
    showImport.value = false
    importContent.value = ''
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to import records')
  } finally {
    importingRecords.value = false
  }
}
</script>
