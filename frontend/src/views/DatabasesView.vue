<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <h1 class="text-2xl font-semibold text-[var(--text-primary)]">Databases</h1>
      <div class="flex items-center gap-3">
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
            <div class="flex items-center justify-end gap-1 flex-wrap">
              <button
                v-if="row.type === 'mysql'"
                class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] text-primary hover:text-primary whitespace-nowrap"
                :disabled="ssoLoading === row.id"
                @click="openPhpMyAdmin(row)"
              >
                <span v-if="ssoLoading === row.id" class="inline-block w-3 h-3 border-2 border-primary/30 border-t-primary rounded-full animate-spin mr-1"></span>
                phpMyAdmin
              </button>
              <button
                v-if="row.type === 'postgresql'"
                class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] text-primary hover:text-primary whitespace-nowrap"
                :disabled="ssoLoading === row.id"
                @click="openPhpPgAdmin(row)"
              >
                <span v-if="ssoLoading === row.id" class="inline-block w-3 h-3 border-2 border-primary/30 border-t-primary rounded-full animate-spin mr-1"></span>
                phpPgAdmin
              </button>
              <button
                class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] whitespace-nowrap"
                @click="openRemoteAccessModal(row)"
              >
                <span :class="row.remote_access ? 'text-green-500' : 'text-[var(--text-muted)]'">&#9679;</span>
                Remote
              </button>
              <button
                class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] whitespace-nowrap"
                @click="openUsersModal(row)"
              >
                Users
              </button>
              <button
                class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] text-primary hover:text-primary whitespace-nowrap"
                :disabled="backupLoading === row.id"
                @click="handleBackup(row)"
              >
                <span v-if="backupLoading === row.id" class="inline-block w-3 h-3 border-2 border-primary/30 border-t-primary rounded-full animate-spin mr-1"></span>
                Backup
              </button>
              <button
                class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] whitespace-nowrap"
                @click="openRestoreModal(row)"
              >
                Restore
              </button>
              <button class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] whitespace-nowrap" @click="confirmResetPassword(row)">
                Reset Password
              </button>
              <button class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] text-error hover:text-error whitespace-nowrap" @click="confirmDeleteDb(row)">
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

    <!-- Restore / Backups Modal -->
    <Modal v-model="showRestoreModal" :title="`Backups - ${restoreDb?.name || ''}`" size="lg">
      <div class="space-y-4">
        <!-- Backup list -->
        <div v-if="backupsLoading" class="flex items-center justify-center py-8">
          <span class="inline-block w-5 h-5 border-2 border-primary/30 border-t-primary rounded-full animate-spin"></span>
          <span class="ml-2 text-sm text-[var(--text-muted)]">Loading backups...</span>
        </div>
        <div v-else-if="backupsList.length === 0" class="text-center py-8">
          <p class="text-sm text-[var(--text-muted)]">No backups found for this database.</p>
        </div>
        <div v-else class="max-h-64 overflow-y-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-[var(--border)]">
                <th class="text-left py-2 px-2 text-[var(--text-muted)] font-medium">Filename</th>
                <th class="text-left py-2 px-2 text-[var(--text-muted)] font-medium">Size</th>
                <th class="text-left py-2 px-2 text-[var(--text-muted)] font-medium">Date</th>
                <th class="text-right py-2 px-2 text-[var(--text-muted)] font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="b in backupsList" :key="b.filename" class="border-b border-[var(--border)] last:border-0">
                <td class="py-2 px-2 font-mono text-xs text-[var(--text-primary)] truncate max-w-[200px]" :title="b.filename">{{ b.filename }}</td>
                <td class="py-2 px-2 text-[var(--text-muted)]">{{ formatBytes(b.size) }}</td>
                <td class="py-2 px-2 text-[var(--text-muted)]">{{ formatDate(b.created_at) }}</td>
                <td class="py-2 px-2 text-right">
                  <div class="flex items-center justify-end gap-1">
                    <button
                      class="btn-ghost text-xs px-2 py-1 text-primary hover:text-primary"
                      :disabled="restoreLoading === b.filename"
                      @click="handleRestore(b)"
                    >
                      <span v-if="restoreLoading === b.filename" class="inline-block w-3 h-3 border-2 border-primary/30 border-t-primary rounded-full animate-spin mr-1"></span>
                      Restore
                    </button>
                    <button
                      class="btn-ghost text-xs px-2 py-1"
                      @click="handleDownloadBackup(b)"
                    >
                      Download
                    </button>
                    <button
                      class="btn-ghost text-xs px-2 py-1 text-error hover:text-error"
                      @click="handleDeleteBackup(b)"
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showRestoreModal = false">Close</button>
      </template>
    </Modal>

    <!-- Restore Confirm Dialog -->
    <ConfirmDialog
      v-model="showRestoreConfirm"
      title="Restore Database"
      :message="`Restore '${restoreDb?.name}' from backup '${backupToRestore?.filename}'? This will overwrite the current database contents.`"
      confirm-text="Restore"
      :destructive="true"
      @confirm="confirmRestore"
    />

    <!-- Delete Backup Confirm Dialog -->
    <ConfirmDialog
      v-model="showDeleteBackupDialog"
      title="Delete Backup"
      :message="`Permanently delete backup '${backupToDelete?.filename}'?`"
      confirm-text="Delete Backup"
      :destructive="true"
      @confirm="confirmDeleteBackup"
    />

    <!-- Remote Access Modal -->
    <Modal v-model="showRemoteModal" title="Remote Database Access" size="md">
      <form @submit.prevent="handleRemoteAccess" class="space-y-4">
        <div class="flex items-center gap-3">
          <label class="text-sm font-medium text-[var(--text-primary)]">Enable Remote Access</label>
          <button type="button" class="relative w-11 h-6 rounded-full transition-colors" :class="remoteForm.enabled ? 'bg-primary' : 'bg-[var(--border)]'" @click="remoteForm.enabled = !remoteForm.enabled">
            <span class="absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform" :class="remoteForm.enabled ? 'translate-x-5' : ''"></span>
          </button>
        </div>
        <div v-if="remoteForm.enabled">
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Allowed Hosts</label>
          <input v-model="remoteForm.allowed_hosts" type="text" placeholder="localhost, 192.168.1.%, %" class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50" />
          <p class="text-xs text-[var(--text-muted)] mt-1">Comma-separated. Use % as wildcard. Example: 192.168.1.%, 10.0.0.5</p>
        </div>
        <div class="flex justify-end gap-3 pt-2">
          <button type="button" class="btn-ghost" @click="showRemoteModal = false">Cancel</button>
          <button type="submit" class="btn-primary" :disabled="remoteSubmitting">
            {{ remoteSubmitting ? 'Saving...' : 'Save' }}
          </button>
        </div>
      </form>
    </Modal>

    <!-- Database Users Modal -->
    <Modal v-model="showUsersModal" :title="`Database Users — ${usersRow?.db_name || ''}`" size="lg">
      <div class="space-y-4">
        <div v-if="usersLoading" class="text-center py-4 text-[var(--text-muted)]">Loading users...</div>
        <div v-else>
          <div class="mb-3 text-sm text-[var(--text-muted)]">
            <strong class="text-[var(--text-primary)]">Primary user:</strong> <span class="font-mono">{{ usersRow?.db_user }}</span> (ALL PRIVILEGES)
          </div>
          <div v-if="dbUsers.length" class="space-y-2">
            <div v-for="u in dbUsers" :key="u.id" class="flex items-center justify-between p-3 bg-[var(--surface)] rounded-lg border border-[var(--border)]">
              <div>
                <span class="font-mono text-sm text-[var(--text-primary)]">{{ u.username }}</span>
                <span class="ml-2 text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary">{{ u.permissions }}</span>
              </div>
              <button class="btn-ghost text-xs text-error" @click="handleDeleteUser(u.id)">Remove</button>
            </div>
          </div>
          <div v-else class="text-sm text-[var(--text-muted)] py-2">No additional users.</div>

          <div v-if="!showAddUserForm" class="pt-3">
            <button class="btn-primary text-sm" @click="showAddUserForm = true">+ Add User</button>
          </div>
          <div v-else class="pt-3 p-4 bg-[var(--surface)] rounded-lg border border-[var(--border)] space-y-3">
            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Username</label>
              <input v-model="newUserForm.username" type="text" placeholder="db_reader" class="w-full px-3 py-2 bg-[var(--background)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50" />
            </div>
            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Password</label>
              <input v-model="newUserForm.password" type="text" placeholder="min 8 chars" class="w-full px-3 py-2 bg-[var(--background)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] font-mono focus:outline-none focus:ring-2 focus:ring-primary/50" />
            </div>
            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Permissions</label>
              <select v-model="newUserForm.permissions" class="w-full px-3 py-2 bg-[var(--background)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50">
                <option value="ALL">ALL PRIVILEGES</option>
                <option value="SELECT">SELECT (read-only)</option>
                <option value="SELECT,INSERT">SELECT, INSERT</option>
                <option value="SELECT,INSERT,UPDATE">SELECT, INSERT, UPDATE</option>
                <option value="SELECT,INSERT,UPDATE,DELETE">SELECT, INSERT, UPDATE, DELETE</option>
              </select>
            </div>
            <div class="flex gap-2">
              <button class="btn-primary text-sm" :disabled="addUserSubmitting" @click="handleAddUser">
                {{ addUserSubmitting ? 'Creating...' : 'Create User' }}
              </button>
              <button class="btn-ghost text-sm" @click="showAddUserForm = false">Cancel</button>
            </div>
          </div>
        </div>
      </div>
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
import client from '@/api/client'

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
const showRestoreModal = ref(false)
const showRestoreConfirm = ref(false)
const showDeleteBackupDialog = ref(false)
const newPassword = ref('')
const dbToDelete = ref(null)
const dbToReset = ref(null)
const submitting = ref(false)
const ssoLoading = ref(null)
const backupLoading = ref(null)
const backupsLoading = ref(false)
const restoreLoading = ref(null)
const restoreDb = ref(null)
const backupsList = ref([])
const backupToRestore = ref(null)
const backupToDelete = ref(null)

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

async function openPhpMyAdmin(row) {
  ssoLoading.value = row.id
  try {
    const { data } = await client.post(`/databases/${row.id}/sso`)
    if (data.sso_url) {
      window.open(data.sso_url, '_blank', 'noopener,noreferrer')
    }
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to open phpMyAdmin. Try resetting the database password.')
  } finally {
    ssoLoading.value = null
  }
}

async function openPhpPgAdmin(row) {
  ssoLoading.value = row.id
  try {
    const { data } = await client.post(`/databases/${row.id}/sso-pgsql`)
    if (data.sso_url) {
      window.open(data.sso_url, '_blank', 'noopener,noreferrer')
    }
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to open phpPgAdmin.')
  } finally {
    ssoLoading.value = null
  }
}

// -- Remote Access --
const showRemoteModal = ref(false)
const remoteRow = ref(null)
const remoteForm = ref({ enabled: false, allowed_hosts: '' })
const remoteSubmitting = ref(false)

function openRemoteAccessModal(row) {
  remoteRow.value = row
  remoteForm.value.enabled = row.remote_access || false
  try {
    const hosts = JSON.parse(row.allowed_hosts || '["localhost"]')
    remoteForm.value.allowed_hosts = Array.isArray(hosts) ? hosts.join(', ') : 'localhost'
  } catch { remoteForm.value.allowed_hosts = 'localhost' }
  showRemoteModal.value = true
}

async function handleRemoteAccess() {
  remoteSubmitting.value = true
  try {
    const hosts = remoteForm.value.allowed_hosts.split(',').map(h => h.trim()).filter(Boolean)
    await store.updateRemoteAccess(remoteRow.value.id, {
      enabled: remoteForm.value.enabled,
      allowed_hosts: hosts
    })
    notifications.success(`Remote access ${remoteForm.value.enabled ? 'enabled' : 'disabled'}.`)
    showRemoteModal.value = false
    await store.fetchAll()
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to update remote access.')
  } finally {
    remoteSubmitting.value = false
  }
}

// -- Database Users --
const showUsersModal = ref(false)
const usersRow = ref(null)
const dbUsers = ref([])
const usersLoading = ref(false)
const showAddUserForm = ref(false)
const newUserForm = ref({ username: '', password: '', permissions: 'ALL' })
const addUserSubmitting = ref(false)

async function openUsersModal(row) {
  usersRow.value = row
  showUsersModal.value = true
  showAddUserForm.value = false
  usersLoading.value = true
  try {
    dbUsers.value = await store.fetchUsers(row.id)
  } catch (err) {
    notifications.error('Failed to load database users.')
    dbUsers.value = []
  } finally {
    usersLoading.value = false
  }
}

async function handleAddUser() {
  addUserSubmitting.value = true
  try {
    await store.createUser(usersRow.value.id, newUserForm.value)
    notifications.success(`User '${newUserForm.value.username}' created.`)
    newUserForm.value = { username: '', password: '', permissions: 'ALL' }
    showAddUserForm.value = false
    dbUsers.value = await store.fetchUsers(usersRow.value.id)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to create user.')
  } finally {
    addUserSubmitting.value = false
  }
}

async function handleDeleteUser(userId) {
  try {
    await store.deleteUser(usersRow.value.id, userId)
    notifications.success('User deleted.')
    dbUsers.value = await store.fetchUsers(usersRow.value.id)
  } catch (err) {
    notifications.error('Failed to delete user.')
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

// -- Backup & Restore handlers --

async function handleBackup(row) {
  backupLoading.value = row.id
  try {
    const result = await store.createBackup(row.id)
    notifications.success(`Backup created: ${result.filename}`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to create backup.')
  } finally {
    backupLoading.value = null
  }
}

async function openRestoreModal(row) {
  restoreDb.value = row
  backupsList.value = []
  showRestoreModal.value = true
  backupsLoading.value = true
  try {
    backupsList.value = await store.listBackups(row.id)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to load backups.')
  } finally {
    backupsLoading.value = false
  }
}

function handleRestore(backup) {
  backupToRestore.value = backup
  showRestoreConfirm.value = true
}

async function confirmRestore() {
  if (!restoreDb.value || !backupToRestore.value) return
  restoreLoading.value = backupToRestore.value.filename
  try {
    await store.restoreBackup(restoreDb.value.id, backupToRestore.value.filename)
    notifications.success(`Database restored from ${backupToRestore.value.filename}.`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to restore database.')
  } finally {
    restoreLoading.value = null
    backupToRestore.value = null
  }
}

async function handleDownloadBackup(backup) {
  if (!restoreDb.value) return
  try {
    await store.downloadBackup(restoreDb.value.id, backup.filename)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to download backup.')
  }
}

function handleDeleteBackup(backup) {
  backupToDelete.value = backup
  showDeleteBackupDialog.value = true
}

async function confirmDeleteBackup() {
  if (!restoreDb.value || !backupToDelete.value) return
  try {
    await store.deleteBackup(restoreDb.value.id, backupToDelete.value.filename)
    backupsList.value = backupsList.value.filter(b => b.filename !== backupToDelete.value.filename)
    notifications.success('Backup deleted.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete backup.')
  } finally {
    backupToDelete.value = null
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
