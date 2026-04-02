<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <h1 class="text-2xl font-semibold text-[var(--text-primary)]">Users</h1>
      <button class="btn-primary inline-flex items-center gap-2" @click="showCreateModal = true">
        <span class="text-lg leading-none">+</span>
        Create User
      </button>
    </div>

    <!-- Search -->
    <div class="glass rounded-2xl p-6">
      <div class="relative">
        <span class="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]">&#128269;</span>
        <input
          v-model="search"
          type="text"
          placeholder="Search users..."
          class="w-full pl-10 pr-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
        />
      </div>
    </div>

    <!-- Users Table -->
    <div class="glass rounded-2xl p-0 overflow-hidden">
      <DataTable
        :columns="columns"
        :rows="filteredUsers"
        :loading="loading"
        empty-text="No users found."
      >
        <template #cell-username="{ row }">
          <router-link
            :to="{ name: 'user-detail', params: { id: row.id } }"
            class="text-primary hover:underline font-medium transition-colors"
          >
            {{ row.username }}
          </router-link>
        </template>

        <template #cell-package_name="{ value }">
          <span class="badge badge-info">{{ value || 'None' }}</span>
        </template>

        <template #cell-disk_used="{ row }">
          <div class="flex items-center gap-2">
            <div class="flex-1 h-2 bg-[var(--border)] rounded-full overflow-hidden max-w-[100px]">
              <div
                class="h-full rounded-full transition-all"
                :class="diskBarClass(row)"
                :style="{ width: diskPercent(row) + '%' }"
              ></div>
            </div>
            <span class="text-xs text-[var(--text-muted)] font-mono whitespace-nowrap">
              {{ formatSize(row.disk_used) }} / {{ formatSize(row.disk_limit) }}
            </span>
          </div>
        </template>

        <template #cell-status="{ value }">
          <StatusBadge
            :status="value === 'active' ? 'active' : value === 'suspended' ? 'stopped' : 'inactive'"
            :label="value"
          />
        </template>

        <template #cell-created_at="{ value }">
          <span class="text-xs text-[var(--text-muted)]">{{ formatDate(value) }}</span>
        </template>

        <template #actions="{ row }">
          <div class="flex items-center justify-end gap-2">
            <router-link
              :to="{ name: 'user-detail', params: { id: row.id } }"
              class="btn-ghost text-xs px-2 py-1"
            >
              View
            </router-link>
            <button
              v-if="row.status === 'active'"
              class="btn-ghost text-xs px-2 py-1 text-warning"
              @click="suspendUser(row)"
            >
              Suspend
            </button>
            <button
              v-else-if="row.status === 'suspended'"
              class="btn-ghost text-xs px-2 py-1 text-success"
              @click="unsuspendUser(row)"
            >
              Unsuspend
            </button>
            <button
              class="btn-ghost text-xs px-2 py-1 text-error hover:text-error"
              @click="confirmDeleteUser(row)"
            >
              Delete
            </button>
          </div>
        </template>
      </DataTable>
    </div>

    <!-- Create User Modal -->
    <Modal v-model="showCreateModal" title="Create User" size="md">
      <form class="space-y-4" @submit.prevent="handleCreate">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Username</label>
          <input
            v-model="form.username"
            type="text"
            placeholder="johndoe"
            required
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
            :class="{ 'border-error': formErrors.username }"
          />
          <p v-if="formErrors.username" class="mt-1 text-xs text-error">{{ formErrors.username }}</p>
        </div>

        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Email</label>
          <input
            v-model="form.email"
            type="email"
            placeholder="user@example.com"
            required
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
            :class="{ 'border-error': formErrors.email }"
          />
          <p v-if="formErrors.email" class="mt-1 text-xs text-error">{{ formErrors.email }}</p>
        </div>

        <div>
          <div class="flex items-center justify-between mb-1">
            <label class="text-sm font-medium text-[var(--text-primary)]">Password</label>
            <button type="button" class="text-xs text-primary hover:underline" @click="generatePassword">
              Auto-generate
            </button>
          </div>
          <div class="relative">
            <input
              v-model="form.password"
              :type="showPassword ? 'text' : 'password'"
              placeholder="Minimum 8 characters"
              required
              class="w-full px-4 py-2 pr-10 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 font-mono"
            />
            <button
              type="button"
              class="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-primary)] text-sm"
              @click="showPassword = !showPassword"
            >
              {{ showPassword ? '&#128065;' : '&#128064;' }}
            </button>
          </div>
        </div>

        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Package</label>
            <select
              v-model="form.package_id"
              class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
            >
              <option :value="null">No Package</option>
              <option v-for="pkg in availablePackages" :key="pkg.id" :value="pkg.id">
                {{ pkg.name }}
              </option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Role</label>
            <select
              v-model="form.role"
              class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
            >
              <option value="user">User</option>
              <option value="reseller">Reseller</option>
              <option value="admin">Admin</option>
            </select>
          </div>
        </div>
      </form>

      <template #actions>
        <button class="btn-secondary" @click="showCreateModal = false">Cancel</button>
        <button class="btn-primary" :disabled="submitting" @click="handleCreate">
          <span v-if="submitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          {{ submitting ? 'Creating...' : 'Create User' }}
        </button>
      </template>
    </Modal>

    <!-- Delete Confirm -->
    <ConfirmDialog
      v-model="showDeleteDialog"
      title="Delete User"
      :message="`Are you sure you want to delete user '${userToDelete?.username}'? All associated data (domains, databases, emails) will be permanently removed.`"
      confirm-text="Delete User"
      :destructive="true"
      @confirm="handleDelete"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'
import DataTable from '@/components/DataTable.vue'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import StatusBadge from '@/components/StatusBadge.vue'

const notifications = useNotificationsStore()

const users = ref([])
const availablePackages = ref([])
const loading = ref(false)
const submitting = ref(false)
const search = ref('')

const showCreateModal = ref(false)
const showDeleteDialog = ref(false)
const showPassword = ref(false)
const userToDelete = ref(null)
const formErrors = ref({})

const defaultForm = {
  username: '',
  email: '',
  password: '',
  package_id: null,
  role: 'user'
}
const form = ref({ ...defaultForm })

const columns = [
  { key: 'username', label: 'Username' },
  { key: 'email', label: 'Email' },
  { key: 'package_name', label: 'Package' },
  { key: 'disk_used', label: 'Disk Usage' },
  { key: 'status', label: 'Status' },
  { key: 'created_at', label: 'Created' }
]

const filteredUsers = computed(() => {
  if (!search.value) return users.value
  const q = search.value.toLowerCase()
  return users.value.filter(u =>
    u.username?.toLowerCase().includes(q) ||
    u.email?.toLowerCase().includes(q) ||
    u.package_name?.toLowerCase().includes(q)
  )
})

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return '--'
  if (bytes === 0) return '0 MB'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

function formatDate(dateStr) {
  if (!dateStr) return '--'
  return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function diskPercent(user) {
  if (!user.disk_limit || !user.disk_used) return 0
  return Math.min(Math.round((user.disk_used / user.disk_limit) * 100), 100)
}

function diskBarClass(user) {
  const pct = diskPercent(user)
  if (pct >= 90) return 'bg-error'
  if (pct >= 70) return 'bg-warning'
  return 'bg-primary'
}

function generatePassword() {
  const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*'
  let password = ''
  for (let i = 0; i < 16; i++) {
    password += chars[Math.floor(Math.random() * chars.length)]
  }
  form.value.password = password
  showPassword.value = true
}

async function fetchUsers() {
  loading.value = true
  try {
    const { data } = await client.get('/users')
    users.value = data
  } catch {
    notifications.error('Failed to load users.')
  } finally {
    loading.value = false
  }
}

async function fetchPackages() {
  try {
    const { data } = await client.get('/packages')
    availablePackages.value = data
  } catch {
    // silent
  }
}

function validateForm() {
  const errors = {}
  if (!form.value.username.trim()) errors.username = 'Username is required.'
  else if (!/^[a-z][a-z0-9_]{2,31}$/.test(form.value.username.trim())) errors.username = 'Username must be lowercase, start with a letter, 3-32 chars.'
  if (!form.value.email.trim()) errors.email = 'Email is required.'
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.value.email.trim())) errors.email = 'Enter a valid email.'
  formErrors.value = errors
  return Object.keys(errors).length === 0
}

async function handleCreate() {
  if (!validateForm()) return
  submitting.value = true
  try {
    const { data } = await client.post('/users', {
      ...form.value,
      username: form.value.username.trim(),
      email: form.value.email.trim()
    })
    users.value.push(data)
    notifications.success(`User '${form.value.username}' created.`)
    showCreateModal.value = false
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to create user.')
  } finally {
    submitting.value = false
  }
}

async function suspendUser(user) {
  try {
    await client.post(`/users/${user.id}/suspend`)
    user.status = 'suspended'
    notifications.success(`User '${user.username}' suspended.`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to suspend user.')
  }
}

async function unsuspendUser(user) {
  try {
    await client.post(`/users/${user.id}/unsuspend`)
    user.status = 'active'
    notifications.success(`User '${user.username}' unsuspended.`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to unsuspend user.')
  }
}

function confirmDeleteUser(user) {
  userToDelete.value = user
  showDeleteDialog.value = true
}

async function handleDelete() {
  if (!userToDelete.value) return
  try {
    await client.delete(`/users/${userToDelete.value.id}`)
    users.value = users.value.filter(u => u.id !== userToDelete.value.id)
    notifications.success(`User '${userToDelete.value.username}' deleted.`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete user.')
  } finally {
    userToDelete.value = null
  }
}

watch(showCreateModal, v => {
  if (!v) {
    form.value = { ...defaultForm }
    formErrors.value = {}
    showPassword.value = false
  }
})

onMounted(() => {
  fetchUsers()
  fetchPackages()
})
</script>
