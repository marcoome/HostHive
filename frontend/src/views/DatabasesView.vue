<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <h1 class="text-2xl font-semibold text-[var(--text-primary)]">Databases</h1>
      <div class="flex items-center gap-3">
        <a
          href="/phpmyadmin"
          target="_blank"
          rel="noopener"
          class="btn-secondary inline-flex items-center gap-2 text-sm"
        >
          phpMyAdmin
          <span class="text-xs">&#8599;</span>
        </a>
        <button class="btn-primary inline-flex items-center gap-2" @click="openAddModal">
          <span class="text-lg leading-none">+</span>
          Add Database
        </button>
      </div>
    </div>

    <!-- Tabs: MySQL | PostgreSQL -->
    <div class="flex border-b border-[var(--border)] overflow-x-auto">
      <button
        v-for="tab in dbTabs"
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

    <!-- Search -->
    <div class="glass rounded-2xl p-6">
      <div class="relative">
        <span class="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]">&#128269;</span>
        <input
          v-model="search"
          type="text"
          :placeholder="`Search ${activeTab === 'mysql' ? 'MySQL' : 'PostgreSQL'} databases...`"
          class="w-full pl-10 pr-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
        />
      </div>
    </div>

    <!-- Database Table -->
    <Transition name="fade" mode="out-in">
      <div :key="activeTab" class="glass rounded-2xl p-0 overflow-hidden">
        <DataTable
          :columns="columns"
          :rows="filteredDatabases"
          :loading="store.loading"
          :empty-text="`No ${activeTab === 'mysql' ? 'MySQL' : 'PostgreSQL'} databases yet.`"
        >
          <template #cell-name="{ value }">
            <span class="font-mono text-sm text-[var(--text-primary)]">{{ value }}</span>
          </template>

          <template #cell-username="{ value }">
            <span class="font-mono text-sm text-[var(--text-muted)]">{{ value }}</span>
          </template>

          <template #cell-size="{ value }">
            <span class="text-sm text-[var(--text-muted)]">{{ formatBytes(value) }}</span>
          </template>

          <template #cell-created_at="{ value }">
            <span class="text-sm text-[var(--text-muted)]">{{ formatDate(value) }}</span>
          </template>

          <template #actions="{ row }">
            <div class="flex items-center justify-end gap-2">
              <button class="btn-ghost text-xs px-2 py-1" @click="confirmResetPassword(row)">
                Reset Password
              </button>
              <button class="btn-ghost text-xs px-2 py-1 text-error hover:text-error" @click="confirmDeleteDb(row)">
                Delete
              </button>
            </div>
          </template>
        </DataTable>
      </div>
    </Transition>

    <!-- Add Database Modal -->
    <Modal v-model="showAddModal" title="Add Database" size="md">
      <form @submit.prevent="handleAdd" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Database Type</label>
          <div class="flex gap-3">
            <button
              type="button"
              class="flex-1 px-4 py-2 rounded-lg border text-sm font-medium transition-colors"
              :class="form.type === 'mysql'
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-[var(--border)] text-[var(--text-muted)] hover:border-primary/50'"
              @click="form.type = 'mysql'"
            >
              MySQL
            </button>
            <button
              type="button"
              class="flex-1 px-4 py-2 rounded-lg border text-sm font-medium transition-colors"
              :class="form.type === 'postgresql'
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-[var(--border)] text-[var(--text-muted)] hover:border-primary/50'"
              @click="form.type = 'postgresql'"
            >
              PostgreSQL
            </button>
          </div>
        </div>

        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Database Name</label>
          <div class="flex">
            <span class="inline-flex items-center px-3 bg-[var(--background)] border border-r-0 border-[var(--border)] rounded-l-lg text-sm text-[var(--text-muted)]">
              {{ usernamePrefix }}_
            </span>
            <input
              v-model="form.name"
              type="text"
              placeholder="mydb"
              required
              class="flex-1 px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-r-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
            />
          </div>
        </div>

        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Database User</label>
          <input
            :value="dbUser"
            type="text"
            readonly
            class="w-full px-4 py-2 bg-[var(--background)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-muted)] cursor-not-allowed font-mono"
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Password</label>
          <div class="flex gap-2">
            <input
              :value="form.password"
              type="text"
              readonly
              class="flex-1 px-4 py-2 bg-[var(--background)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] font-mono"
            />
            <button
              type="button"
              class="btn-ghost px-3"
              title="Copy password"
              @click="copyToClipboard(form.password)"
            >
              &#128203;
            </button>
            <button
              type="button"
              class="btn-ghost px-3"
              title="Regenerate"
              @click="generatePassword"
            >
              &#8635;
            </button>
          </div>
        </div>
      </form>

      <template #actions>
        <button class="btn-secondary" @click="showAddModal = false">Cancel</button>
        <button class="btn-primary" :disabled="submitting" @click="handleAdd">
          <span v-if="submitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          {{ submitting ? 'Creating...' : 'Create Database' }}
        </button>
      </template>
    </Modal>

    <!-- Reset Password Dialog -->
    <ConfirmDialog
      v-model="showResetDialog"
      title="Reset Database Password"
      :message="`Generate a new password for database user of '${dbToReset?.name}'? Applications using the old password will lose access.`"
      confirm-text="Reset Password"
      :destructive="true"
      @confirm="handleResetPassword"
    />

    <!-- Delete Confirm Dialog -->
    <ConfirmDialog
      v-model="showDeleteDialog"
      title="Delete Database"
      :message="`Permanently delete database '${dbToDelete?.name}'? All data will be lost and cannot be recovered.`"
      confirm-text="Delete Database"
      :destructive="true"
      @confirm="handleDelete"
    />

    <!-- New Password Display Modal -->
    <Modal v-model="showNewPasswordModal" title="New Password Generated" size="sm">
      <div class="space-y-3">
        <p class="text-sm text-[var(--text-muted)]">
          Save this password now. It will not be shown again.
        </p>
        <div class="flex gap-2">
          <input
            :value="newPassword"
            type="text"
            readonly
            class="flex-1 px-4 py-2 bg-[var(--background)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] font-mono"
          />
          <button class="btn-ghost px-3" @click="copyToClipboard(newPassword)">&#128203;</button>
        </div>
      </div>
      <template #actions>
        <button class="btn-primary" @click="showNewPasswordModal = false">Done</button>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useDatabasesStore } from '@/stores/databases'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'
import DataTable from '@/components/DataTable.vue'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const store = useDatabasesStore()
const auth = useAuthStore()
const notifications = useNotificationsStore()

const dbTabs = [
  { key: 'mysql', label: 'MySQL' },
  { key: 'postgresql', label: 'PostgreSQL' }
]

const columns = [
  { key: 'name', label: 'Database' },
  { key: 'username', label: 'User' },
  { key: 'size', label: 'Size' },
  { key: 'created_at', label: 'Created' }
]

const activeTab = ref('mysql')
const search = ref('')
const showAddModal = ref(false)
const showDeleteDialog = ref(false)
const showResetDialog = ref(false)
const showNewPasswordModal = ref(false)
const newPassword = ref('')
const dbToDelete = ref(null)
const dbToReset = ref(null)
const submitting = ref(false)

const usernamePrefix = computed(() => auth.user?.username || 'user')

const form = ref({
  type: 'mysql',
  name: '',
  password: ''
})

const dbUser = computed(() => {
  const name = form.value.name || 'mydb'
  return `${usernamePrefix.value}_${name}`
})

const filteredDatabases = computed(() => {
  const list = Array.isArray(store.databases) ? store.databases : []
  let result = list.filter(d => d.type === activeTab.value)
  if (search.value) {
    const q = search.value.toLowerCase()
    result = result.filter(d => d.name.toLowerCase().includes(q) || d.username?.toLowerCase().includes(q))
  }
  return result
})

function generatePassword() {
  const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*'
  let pw = ''
  for (let i = 0; i < 20; i++) {
    pw += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  form.value.password = pw
}

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return '--'
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

function formatDate(dateStr) {
  if (!dateStr) return '--'
  return new Date(dateStr).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text)
    notifications.success('Copied to clipboard.')
  } catch {
    notifications.error('Failed to copy.')
  }
}

function openAddModal() {
  form.value.type = activeTab.value
  form.value.name = ''
  generatePassword()
  showAddModal.value = true
}

async function handleAdd() {
  if (!form.value.name.trim()) {
    notifications.error('Database name is required.')
    return
  }
  submitting.value = true
  try {
    await store.create({
      type: form.value.type,
      name: `${usernamePrefix.value}_${form.value.name.trim()}`,
      username: dbUser.value,
      password: form.value.password
    })
    notifications.success(`Database '${usernamePrefix.value}_${form.value.name}' created.`)
    showAddModal.value = false
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to create database.')
  } finally {
    submitting.value = false
  }
}

function confirmResetPassword(db) {
  dbToReset.value = db
  showResetDialog.value = true
}

async function handleResetPassword() {
  if (!dbToReset.value) return
  try {
    const pw = []
    const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*'
    for (let i = 0; i < 20; i++) pw.push(chars.charAt(Math.floor(Math.random() * chars.length)))
    const password = pw.join('')

    await store.update(dbToReset.value.id, { password })
    newPassword.value = password
    showNewPasswordModal.value = true
    notifications.success('Password reset successfully.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to reset password.')
  } finally {
    dbToReset.value = null
  }
}

function confirmDeleteDb(db) {
  dbToDelete.value = db
  showDeleteDialog.value = true
}

async function handleDelete() {
  if (!dbToDelete.value) return
  try {
    await store.remove(dbToDelete.value.id)
    notifications.success(`Database '${dbToDelete.value.name}' deleted.`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete database.')
  } finally {
    dbToDelete.value = null
  }
}

watch(activeTab, () => {
  search.value = ''
})

onMounted(() => {
  store.fetchAll()
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
