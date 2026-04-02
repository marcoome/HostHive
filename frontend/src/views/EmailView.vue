<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <h1 class="text-2xl font-semibold text-[var(--text-primary)]">Email</h1>
      <button
        class="btn-primary inline-flex items-center gap-2"
        @click="activeTab === 'aliases' ? openAddAlias() : openAddMailbox()"
      >
        <span class="text-lg leading-none">+</span>
        {{ activeTab === 'aliases' ? 'Add Alias' : 'Add Mailbox' }}
      </button>
    </div>

    <!-- Tabs -->
    <div class="flex border-b border-[var(--border)] overflow-x-auto">
      <button
        v-for="tab in visibleTabs"
        :key="tab.key"
        class="px-4 py-3 text-sm font-medium border-b-2 transition-colors whitespace-nowrap"
        :class="activeTab === tab.key
          ? 'border-primary text-primary'
          : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:border-[var(--border)]'"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Search (mailboxes / aliases) -->
    <div v-if="activeTab !== 'queue'" class="glass rounded-2xl p-6">
      <div class="relative">
        <span class="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]">&#128269;</span>
        <input
          v-model="search"
          type="text"
          :placeholder="activeTab === 'mailboxes' ? 'Search mailboxes...' : 'Search aliases...'"
          class="w-full pl-10 pr-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
        />
      </div>
    </div>

    <!-- Mailboxes Tab -->
    <Transition name="fade" mode="out-in">
      <div v-if="activeTab === 'mailboxes'" key="mailboxes" class="glass rounded-2xl p-0 overflow-hidden">
        <DataTable
          :columns="mailboxColumns"
          :rows="filteredMailboxes"
          :loading="emailStore.loading"
          empty-text="No mailboxes yet. Create your first email account."
        >
          <template #cell-address="{ row }">
            <span class="font-medium text-[var(--text-primary)]">{{ row.address }}</span>
          </template>

          <template #cell-domain="{ value }">
            <span class="text-sm text-[var(--text-muted)]">{{ value }}</span>
          </template>

          <template #cell-quota="{ row }">
            <div class="flex items-center gap-3 min-w-[180px]">
              <div class="flex-1 bg-[var(--background)] rounded-full h-2 overflow-hidden">
                <div
                  class="h-full rounded-full transition-all duration-500"
                  :class="quotaPercent(row) > 90 ? 'bg-error' : quotaPercent(row) > 70 ? 'bg-warning' : 'bg-primary'"
                  :style="{ width: quotaPercent(row) + '%' }"
                />
              </div>
              <span class="text-xs text-[var(--text-muted)] whitespace-nowrap">
                {{ formatMB(row.quota_used) }} / {{ formatMB(row.quota_total) }}
              </span>
            </div>
          </template>

          <template #cell-status="{ row }">
            <StatusBadge
              :status="row.status || 'active'"
              :label="row.status || 'active'"
            />
          </template>

          <template #actions="{ row }">
            <div class="flex items-center justify-end gap-2">
              <button class="btn-ghost text-xs px-2 py-1" @click="editMailbox(row)">
                Edit
              </button>
              <button class="btn-ghost text-xs px-2 py-1 text-error hover:text-error" @click="confirmDeleteMailbox(row)">
                Delete
              </button>
            </div>
          </template>
        </DataTable>
      </div>

      <!-- Aliases Tab -->
      <div v-else-if="activeTab === 'aliases'" key="aliases" class="glass rounded-2xl p-0 overflow-hidden">
        <DataTable
          :columns="aliasColumns"
          :rows="filteredAliases"
          :loading="emailStore.loading"
          empty-text="No email aliases yet."
        >
          <template #cell-from_address="{ value }">
            <span class="font-mono text-sm text-[var(--text-primary)]">{{ value }}</span>
          </template>

          <template #cell-to_address="{ value }">
            <span class="font-mono text-sm text-[var(--text-muted)]">{{ value }}</span>
          </template>

          <template #actions="{ row }">
            <div class="flex items-center justify-end gap-2">
              <button class="btn-ghost text-xs px-2 py-1" @click="editAlias(row)">
                Edit
              </button>
              <button class="btn-ghost text-xs px-2 py-1 text-error hover:text-error" @click="confirmDeleteAlias(row)">
                Delete
              </button>
            </div>
          </template>
        </DataTable>
      </div>

      <!-- Queue Tab (admin only) -->
      <div v-else-if="activeTab === 'queue'" key="queue" class="space-y-4">
        <div class="flex justify-end">
          <button class="btn-danger inline-flex items-center gap-2" @click="showFlushDialog = true">
            Flush Queue
          </button>
        </div>
        <div class="glass rounded-2xl p-0 overflow-hidden">
          <DataTable
            :columns="queueColumns"
            :rows="queueItems"
            :loading="queueLoading"
            empty-text="Mail queue is empty."
          >
            <template #cell-message_id="{ value }">
              <span class="font-mono text-xs text-[var(--text-muted)]">{{ value }}</span>
            </template>

            <template #cell-from="{ value }">
              <span class="text-sm text-[var(--text-primary)]">{{ value }}</span>
            </template>

            <template #cell-to="{ value }">
              <span class="text-sm text-[var(--text-primary)]">{{ value }}</span>
            </template>

            <template #cell-subject="{ value }">
              <span class="text-sm text-[var(--text-muted)] truncate block max-w-[200px]">{{ value || '(no subject)' }}</span>
            </template>

            <template #cell-queued_at="{ value }">
              <span class="text-sm text-[var(--text-muted)]">{{ formatTimeAgo(value) }}</span>
            </template>

            <template #actions="{ row }">
              <button class="btn-ghost text-xs px-2 py-1 text-error hover:text-error" @click="confirmDeleteQueueItem(row)">
                Remove
              </button>
            </template>
          </DataTable>
        </div>
      </div>
    </Transition>

    <!-- Add/Edit Mailbox Modal -->
    <Modal v-model="showMailboxModal" :title="editingMailbox ? 'Edit Mailbox' : 'Add Mailbox'" size="md">
      <form @submit.prevent="handleSaveMailbox" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Email Address</label>
          <div class="flex gap-0">
            <input
              v-model="mailboxForm.prefix"
              type="text"
              placeholder="user"
              required
              :disabled="!!editingMailbox"
              class="flex-1 px-4 py-2 bg-[var(--surface)] border border-r-0 border-[var(--border)] rounded-l-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors disabled:bg-[var(--background)] disabled:cursor-not-allowed"
            />
            <span class="inline-flex items-center px-3 bg-[var(--background)] border-y border-[var(--border)] text-sm text-[var(--text-muted)]">@</span>
            <select
              v-model="mailboxForm.domain"
              :disabled="!!editingMailbox"
              class="px-4 py-2 bg-[var(--surface)] border border-l-0 border-[var(--border)] rounded-r-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors disabled:bg-[var(--background)] disabled:cursor-not-allowed"
            >
              <option v-for="d in availableDomains" :key="d" :value="d">{{ d }}</option>
            </select>
          </div>
        </div>

        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Password</label>
          <input
            v-model="mailboxForm.password"
            type="password"
            :placeholder="editingMailbox ? 'Leave blank to keep current' : 'Password'"
            :required="!editingMailbox"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
            Quota: {{ mailboxForm.quota }} MB
          </label>
          <input
            v-model.number="mailboxForm.quota"
            type="range"
            min="50"
            max="10240"
            step="50"
            class="w-full accent-primary"
          />
          <div class="flex justify-between text-xs text-[var(--text-muted)] mt-1">
            <span>50 MB</span>
            <span>10 GB</span>
          </div>
        </div>
      </form>

      <template #actions>
        <button class="btn-secondary" @click="showMailboxModal = false">Cancel</button>
        <button class="btn-primary" :disabled="mailboxSubmitting" @click="handleSaveMailbox">
          <span v-if="mailboxSubmitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          {{ editingMailbox ? 'Save Changes' : 'Create Mailbox' }}
        </button>
      </template>
    </Modal>

    <!-- Add/Edit Alias Modal -->
    <Modal v-model="showAliasModal" :title="editingAlias ? 'Edit Alias' : 'Add Alias'" size="md">
      <form @submit.prevent="handleSaveAlias" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">From Address</label>
          <input
            v-model="aliasForm.from_address"
            type="email"
            placeholder="alias@example.com"
            required
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">To Address</label>
          <input
            v-model="aliasForm.to_address"
            type="email"
            placeholder="destination@example.com"
            required
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
          />
        </div>
      </form>

      <template #actions>
        <button class="btn-secondary" @click="showAliasModal = false">Cancel</button>
        <button class="btn-primary" :disabled="aliasSubmitting" @click="handleSaveAlias">
          <span v-if="aliasSubmitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          {{ editingAlias ? 'Save Changes' : 'Create Alias' }}
        </button>
      </template>
    </Modal>

    <!-- Delete Mailbox Confirm -->
    <ConfirmDialog
      v-model="showDeleteMailboxDialog"
      title="Delete Mailbox"
      :message="`Permanently delete '${itemToDelete?.address}'? All emails in this mailbox will be lost.`"
      confirm-text="Delete Mailbox"
      :destructive="true"
      @confirm="handleDeleteMailbox"
    />

    <!-- Delete Alias Confirm -->
    <ConfirmDialog
      v-model="showDeleteAliasDialog"
      title="Delete Alias"
      :message="`Remove alias '${itemToDelete?.from_address}'?`"
      confirm-text="Delete Alias"
      :destructive="true"
      @confirm="handleDeleteAlias"
    />

    <!-- Flush Queue Confirm -->
    <ConfirmDialog
      v-model="showFlushDialog"
      title="Flush Mail Queue"
      message="This will attempt to deliver all queued messages immediately. Continue?"
      confirm-text="Flush Queue"
      :destructive="false"
      @confirm="handleFlushQueue"
    />

    <!-- Delete Queue Item Confirm -->
    <ConfirmDialog
      v-model="showDeleteQueueDialog"
      title="Remove from Queue"
      :message="`Remove message '${queueItemToDelete?.message_id}' from the mail queue?`"
      confirm-text="Remove"
      :destructive="true"
      @confirm="handleDeleteQueueItem"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useEmailStore } from '@/stores/email'
import { useDomainsStore } from '@/stores/domains'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'
import DataTable from '@/components/DataTable.vue'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import client from '@/api/client'

const emailStore = useEmailStore()
const domainsStore = useDomainsStore()
const auth = useAuthStore()
const notifications = useNotificationsStore()

const allTabs = [
  { key: 'mailboxes', label: 'Mailboxes' },
  { key: 'aliases', label: 'Aliases' },
  { key: 'queue', label: 'Queue' }
]

const visibleTabs = computed(() => {
  if (auth.isAdmin) return allTabs
  return allTabs.filter(t => t.key !== 'queue')
})

const mailboxColumns = [
  { key: 'address', label: 'Email' },
  { key: 'domain', label: 'Domain' },
  { key: 'quota', label: 'Quota' },
  { key: 'status', label: 'Status' }
]

const aliasColumns = [
  { key: 'from_address', label: 'From' },
  { key: 'to_address', label: 'To' }
]

const queueColumns = [
  { key: 'message_id', label: 'Message ID' },
  { key: 'from', label: 'From' },
  { key: 'to', label: 'To' },
  { key: 'subject', label: 'Subject' },
  { key: 'queued_at', label: 'Time in Queue' }
]

const activeTab = ref('mailboxes')
const search = ref('')

// Mailbox state
const showMailboxModal = ref(false)
const editingMailbox = ref(null)
const mailboxSubmitting = ref(false)
const mailboxForm = ref({ prefix: '', domain: '', password: '', quota: 500 })

// Alias state
const showAliasModal = ref(false)
const editingAlias = ref(null)
const aliasSubmitting = ref(false)
const aliasForm = ref({ from_address: '', to_address: '' })

// Delete state
const showDeleteMailboxDialog = ref(false)
const showDeleteAliasDialog = ref(false)
const itemToDelete = ref(null)

// Queue state
const queueItems = ref([])
const queueLoading = ref(false)
const showFlushDialog = ref(false)
const showDeleteQueueDialog = ref(false)
const queueItemToDelete = ref(null)

const availableDomains = computed(() => {
  const list = Array.isArray(domainsStore.domains) ? domainsStore.domains : []
  return list.map(d => d.name)
})

const filteredMailboxes = computed(() => {
  const list = Array.isArray(emailStore.mailboxes) ? emailStore.mailboxes : []
  if (!search.value) return list
  const q = search.value.toLowerCase()
  return list.filter(m =>
    m.address?.toLowerCase().includes(q) || m.domain?.toLowerCase().includes(q)
  )
})

const filteredAliases = computed(() => {
  const list = Array.isArray(emailStore.aliases) ? emailStore.aliases : []
  if (!search.value) return list
  const q = search.value.toLowerCase()
  return list.filter(a =>
    a.from_address?.toLowerCase().includes(q) || a.to_address?.toLowerCase().includes(q)
  )
})

function quotaPercent(row) {
  if (!row.quota_total) return 0
  return Math.min(100, Math.round((row.quota_used / row.quota_total) * 100))
}

function formatMB(bytes) {
  if (!bytes && bytes !== 0) return '0 MB'
  if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + ' KB'
  return Math.round(bytes / (1024 * 1024)) + ' MB'
}

function formatTimeAgo(dateStr) {
  if (!dateStr) return '--'
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

// Mailbox CRUD
function openAddMailbox() {
  editingMailbox.value = null
  mailboxForm.value = {
    prefix: '',
    domain: availableDomains.value[0] || '',
    password: '',
    quota: 500
  }
  showMailboxModal.value = true
}

function editMailbox(row) {
  editingMailbox.value = row
  const parts = row.address.split('@')
  mailboxForm.value = {
    prefix: parts[0],
    domain: parts[1] || row.domain,
    password: '',
    quota: row.quota_total ? Math.round(row.quota_total / (1024 * 1024)) : 500
  }
  showMailboxModal.value = true
}

async function handleSaveMailbox() {
  if (!mailboxForm.value.prefix.trim()) {
    notifications.error('Email address is required.')
    return
  }
  mailboxSubmitting.value = true
  try {
    const payload = {
      address: `${mailboxForm.value.prefix}@${mailboxForm.value.domain}`,
      domain: mailboxForm.value.domain,
      quota_total: mailboxForm.value.quota * 1024 * 1024
    }
    if (mailboxForm.value.password) {
      payload.password = mailboxForm.value.password
    }

    if (editingMailbox.value) {
      await emailStore.updateMailbox(editingMailbox.value.id, payload)
      notifications.success('Mailbox updated.')
    } else {
      payload.password = mailboxForm.value.password
      await emailStore.createMailbox(payload)
      notifications.success(`Mailbox '${payload.address}' created.`)
    }
    showMailboxModal.value = false
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to save mailbox.')
  } finally {
    mailboxSubmitting.value = false
  }
}

function confirmDeleteMailbox(row) {
  itemToDelete.value = row
  showDeleteMailboxDialog.value = true
}

async function handleDeleteMailbox() {
  if (!itemToDelete.value) return
  try {
    await emailStore.removeMailbox(itemToDelete.value.id)
    notifications.success(`Mailbox '${itemToDelete.value.address}' deleted.`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete mailbox.')
  } finally {
    itemToDelete.value = null
  }
}

// Alias CRUD
function openAddAlias() {
  editingAlias.value = null
  aliasForm.value = { from_address: '', to_address: '' }
  showAliasModal.value = true
}

function editAlias(row) {
  editingAlias.value = row
  aliasForm.value = {
    from_address: row.from_address,
    to_address: row.to_address
  }
  showAliasModal.value = true
}

async function handleSaveAlias() {
  if (!aliasForm.value.from_address.trim() || !aliasForm.value.to_address.trim()) {
    notifications.error('Both addresses are required.')
    return
  }
  aliasSubmitting.value = true
  try {
    if (editingAlias.value) {
      await emailStore.updateAlias(editingAlias.value.id, aliasForm.value)
      notifications.success('Alias updated.')
    } else {
      await emailStore.createAlias(aliasForm.value)
      notifications.success('Alias created.')
    }
    showAliasModal.value = false
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to save alias.')
  } finally {
    aliasSubmitting.value = false
  }
}

function confirmDeleteAlias(row) {
  itemToDelete.value = row
  showDeleteAliasDialog.value = true
}

async function handleDeleteAlias() {
  if (!itemToDelete.value) return
  try {
    await emailStore.removeAlias(itemToDelete.value.id)
    notifications.success('Alias deleted.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete alias.')
  } finally {
    itemToDelete.value = null
  }
}

// Queue
async function fetchQueue() {
  queueLoading.value = true
  try {
    const { data } = await client.get('/email/queue')
    queueItems.value = data
  } catch {
    queueItems.value = []
  } finally {
    queueLoading.value = false
  }
}

async function handleFlushQueue() {
  try {
    await client.post('/email/queue/flush')
    notifications.success('Mail queue flushed.')
    await fetchQueue()
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to flush queue.')
  }
}

function confirmDeleteQueueItem(row) {
  queueItemToDelete.value = row
  showDeleteQueueDialog.value = true
}

async function handleDeleteQueueItem() {
  if (!queueItemToDelete.value || !queueItemToDelete.value.message_id) return
  try {
    await client.delete(`/email/queue/${queueItemToDelete.value.message_id}`)
    queueItems.value = queueItems.value.filter(q => q.message_id !== queueItemToDelete.value.message_id)
    notifications.success('Message removed from queue.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to remove message.')
  } finally {
    queueItemToDelete.value = null
  }
}

watch(activeTab, (tab) => {
  search.value = ''
  if (tab === 'mailboxes') emailStore.fetchMailboxes()
  if (tab === 'aliases') emailStore.fetchAliases()
  if (tab === 'queue') fetchQueue()
})

onMounted(() => {
  emailStore.fetchMailboxes()
  emailStore.fetchAliases()
  domainsStore.fetchAll()
  if (auth.isAdmin) fetchQueue()
})
</script>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
