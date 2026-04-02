<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <h1 class="text-2xl font-semibold text-[var(--text-primary)]">Backups</h1>
      <button
        class="btn-primary inline-flex items-center gap-2"
        :disabled="creating"
        @click="handleCreate"
      >
        <span v-if="creating" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
        <span v-else class="text-lg leading-none">+</span>
        {{ creating ? 'Creating Backup...' : 'Create Backup' }}
      </button>
    </div>

    <!-- Auto-backup Schedule Card -->
    <div class="glass rounded-2xl p-6">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-4">
          <div class="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary text-lg">
            &#128339;
          </div>
          <div>
            <h3 class="text-sm font-semibold text-[var(--text-primary)]">Automatic Backups</h3>
            <p class="text-xs text-[var(--text-muted)] mt-0.5">
              {{ schedule.enabled ? `Runs ${schedule.frequency} at ${schedule.time}` : 'Automatic backups are disabled' }}
            </p>
          </div>
        </div>
        <div class="flex items-center gap-4">
          <div class="text-right text-xs text-[var(--text-muted)]">
            <div>Retention: <span class="text-[var(--text-primary)] font-medium">{{ schedule.retention }} backups</span></div>
            <div>Next run: <span class="text-[var(--text-primary)] font-medium">{{ schedule.nextRun || 'N/A' }}</span></div>
          </div>
          <button
            class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
            :class="schedule.enabled ? 'bg-primary' : 'bg-[var(--border)]'"
            @click="toggleSchedule"
          >
            <span
              class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
              :class="schedule.enabled ? 'translate-x-6' : 'translate-x-1'"
            />
          </button>
        </div>
      </div>
    </div>

    <!-- Backups Table -->
    <div class="glass rounded-2xl p-0 overflow-hidden">
      <DataTable
        :columns="columns"
        :rows="backups"
        :loading="loading"
        empty-text="No backups yet. Create your first backup to get started."
      >
        <template #cell-created_at="{ value }">
          <div>
            <div class="text-sm text-[var(--text-primary)]">{{ formatDate(value) }}</div>
            <div class="text-xs text-[var(--text-muted)]">{{ formatTimeAgo(value) }}</div>
          </div>
        </template>

        <template #cell-size="{ value }">
          <span class="text-sm font-mono text-[var(--text-primary)]">{{ formatSize(value) }}</span>
        </template>

        <template #cell-type="{ value }">
          <span
            class="badge"
            :class="value === 'full' ? 'badge-info' : 'badge-warning'"
          >
            {{ value === 'full' ? 'Full' : 'Partial' }}
          </span>
        </template>

        <template #cell-status="{ value }">
          <StatusBadge
            :status="value"
            :label="statusLabel(value)"
          />
        </template>

        <template #actions="{ row }">
          <div class="flex items-center justify-end gap-2">
            <button
              class="btn-ghost text-xs px-2 py-1"
              title="Download"
              :disabled="row.status !== 'completed'"
              @click="handleDownload(row)"
            >
              Download
            </button>
            <button
              class="btn-ghost text-xs px-2 py-1"
              title="Restore"
              :disabled="row.status !== 'completed'"
              @click="openRestore(row)"
            >
              Restore
            </button>
            <button
              class="btn-ghost text-xs px-2 py-1 text-error hover:text-error"
              title="Delete"
              @click="confirmDeleteBackup(row)"
            >
              Delete
            </button>
          </div>
        </template>
      </DataTable>
    </div>

    <!-- Restore Confirmation Modal (double confirm with typed input) -->
    <Modal v-model="showRestoreModal" title="Restore Backup" size="md">
      <div class="space-y-4">
        <div class="p-4 rounded-lg bg-error/10 border border-error/20">
          <div class="flex items-start gap-3">
            <span class="text-error text-lg">&#9888;</span>
            <div>
              <p class="text-sm font-medium text-error">Warning: Destructive Action</p>
              <p class="text-xs text-[var(--text-muted)] mt-1">
                This will overwrite all current data with the backup from
                <strong class="text-[var(--text-primary)]">{{ restoreTarget?.created_at ? formatDate(restoreTarget.created_at) : '' }}</strong>.
                This action cannot be undone.
              </p>
            </div>
          </div>
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
            Type <span class="font-mono font-bold text-error">RESTORE</span> to confirm
          </label>
          <input
            v-model="restoreConfirmText"
            type="text"
            placeholder="RESTORE"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-error/50 transition-colors"
          />
        </div>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showRestoreModal = false">Cancel</button>
        <button
          class="btn-danger"
          :disabled="restoreConfirmText !== 'RESTORE' || restoring"
          @click="handleRestore"
        >
          <span v-if="restoring" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          {{ restoring ? 'Restoring...' : 'Restore Backup' }}
        </button>
      </template>
    </Modal>

    <!-- Delete Confirm Dialog -->
    <ConfirmDialog
      v-model="showDeleteDialog"
      title="Delete Backup"
      :message="`Are you sure you want to delete the backup from ${deleteTarget?.created_at ? formatDate(deleteTarget.created_at) : ''}? This cannot be undone.`"
      confirm-text="Delete Backup"
      :destructive="true"
      @confirm="handleDelete"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'
import DataTable from '@/components/DataTable.vue'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import StatusBadge from '@/components/StatusBadge.vue'

const notifications = useNotificationsStore()

const backups = ref([])
const loading = ref(false)
const creating = ref(false)
const restoring = ref(false)

const showRestoreModal = ref(false)
const restoreTarget = ref(null)
const restoreConfirmText = ref('')

const showDeleteDialog = ref(false)
const deleteTarget = ref(null)

const schedule = ref({
  enabled: true,
  frequency: 'daily',
  time: '03:00 UTC',
  retention: 7,
  nextRun: 'Tomorrow at 03:00 UTC'
})

const columns = [
  { key: 'created_at', label: 'Date' },
  { key: 'size', label: 'Size' },
  { key: 'type', label: 'Type' },
  { key: 'status', label: 'Status' }
]

function formatDate(dateStr) {
  if (!dateStr) return '--'
  const d = new Date(dateStr)
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function formatTimeAgo(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const now = new Date()
  const diffMs = now - d
  const diffHrs = Math.floor(diffMs / 3600000)
  if (diffHrs < 1) return 'Just now'
  if (diffHrs < 24) return `${diffHrs}h ago`
  const diffDays = Math.floor(diffHrs / 24)
  if (diffDays === 1) return 'Yesterday'
  return `${diffDays} days ago`
}

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return '--'
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

function statusLabel(status) {
  const map = {
    completed: 'Completed',
    running: 'In Progress',
    pending: 'Pending',
    error: 'Failed'
  }
  return map[status] || status
}

async function fetchBackups() {
  loading.value = true
  try {
    const { data } = await client.get('/backups')
    backups.value = data
  } catch (err) {
    notifications.error('Failed to load backups.')
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  creating.value = true
  try {
    const { data } = await client.post('/backups', { type: 'full' })
    backups.value.unshift(data)
    notifications.success('Backup creation started.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to create backup.')
  } finally {
    creating.value = false
  }
}

function handleDownload(backup) {
  if (!backup?.id) return
  const link = document.createElement('a')
  link.href = `/api/v1/backups/${backup.id}/download`
  link.download = `backup-${backup.id}.tar.gz`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  notifications.info('Download started.')
}

function openRestore(backup) {
  restoreTarget.value = backup
  restoreConfirmText.value = ''
  showRestoreModal.value = true
}

async function handleRestore() {
  if (restoreConfirmText.value !== 'RESTORE' || !restoreTarget.value?.id) return
  restoring.value = true
  try {
    await client.post(`/backups/${restoreTarget.value.id}/restore`)
    notifications.success('Backup restore started. This may take a few minutes.')
    showRestoreModal.value = false
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to restore backup.')
  } finally {
    restoring.value = false
  }
}

function confirmDeleteBackup(backup) {
  deleteTarget.value = backup
  showDeleteDialog.value = true
}

async function handleDelete() {
  if (!deleteTarget.value?.id) return
  try {
    await client.delete(`/backups/${deleteTarget.value.id}`)
    backups.value = backups.value.filter(b => b.id !== deleteTarget.value.id)
    notifications.success('Backup deleted.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete backup.')
  } finally {
    deleteTarget.value = null
  }
}

async function toggleSchedule() {
  try {
    schedule.value.enabled = !schedule.value.enabled
    await client.put('/backups/schedule', { enabled: schedule.value.enabled })
    notifications.success(schedule.value.enabled ? 'Auto-backups enabled.' : 'Auto-backups disabled.')
  } catch (err) {
    schedule.value.enabled = !schedule.value.enabled
    notifications.error('Failed to update backup schedule.')
  }
}

onMounted(() => {
  fetchBackups()
})
</script>
