<template>
  <div class="space-y-6">
    <!-- Back + Header -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <div class="flex items-center gap-3">
        <router-link :to="{ name: 'users' }" class="btn-ghost text-sm px-2 py-1">
          &#8592; Back
        </router-link>
        <h1 class="text-2xl font-semibold text-[var(--text-primary)]">
          {{ user?.username || 'User Details' }}
        </h1>
        <StatusBadge
          v-if="user?.status"
          :status="user.status === 'active' ? 'active' : user.status === 'suspended' ? 'stopped' : 'inactive'"
          :label="user.status"
        />
      </div>
      <div class="flex items-center gap-2">
        <button class="btn-secondary text-sm" @click="showEditModal = true">Edit</button>
        <button
          v-if="user?.status === 'active'"
          class="btn-secondary text-sm text-warning"
          @click="handleSuspend"
        >
          Suspend
        </button>
        <button
          v-else-if="user?.status === 'suspended'"
          class="btn-secondary text-sm text-success"
          @click="handleUnsuspend"
        >
          Unsuspend
        </button>
        <button
          class="btn-danger text-sm"
          @click="showDeleteDialog = true"
        >
          Delete
        </button>
      </div>
    </div>

    <!-- Loading Skeleton -->
    <div v-if="loading" class="space-y-6">
      <div class="glass rounded-2xl p-6">
        <div class="grid grid-cols-2 sm:grid-cols-3 gap-6">
          <div v-for="i in 6" :key="i">
            <div class="skeleton h-3 w-16 rounded mb-2"></div>
            <div class="skeleton h-5 w-32 rounded"></div>
          </div>
        </div>
      </div>
    </div>

    <template v-else-if="user">
      <!-- User Info Card -->
      <div class="glass rounded-2xl p-6">
        <h2 class="text-sm font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-4">Account Information</h2>
        <div class="grid grid-cols-2 sm:grid-cols-3 gap-6">
          <div>
            <p class="text-xs text-[var(--text-muted)] mb-1">Username</p>
            <p class="text-sm font-medium text-[var(--text-primary)] font-mono">{{ user.username }}</p>
          </div>
          <div>
            <p class="text-xs text-[var(--text-muted)] mb-1">Email</p>
            <p class="text-sm text-[var(--text-primary)]">{{ user.email }}</p>
          </div>
          <div>
            <p class="text-xs text-[var(--text-muted)] mb-1">Role</p>
            <span class="badge badge-info">{{ user.role }}</span>
          </div>
          <div>
            <p class="text-xs text-[var(--text-muted)] mb-1">Package</p>
            <span class="badge badge-info">{{ user.package_name || 'None' }}</span>
          </div>
          <div>
            <p class="text-xs text-[var(--text-muted)] mb-1">Created</p>
            <p class="text-sm text-[var(--text-primary)]">{{ formatDate(user.created_at) }}</p>
          </div>
          <div>
            <p class="text-xs text-[var(--text-muted)] mb-1">Last Login</p>
            <p class="text-sm text-[var(--text-primary)]">{{ user.last_login ? formatDate(user.last_login) : 'Never' }}</p>
          </div>
        </div>
      </div>

      <!-- Resource Usage -->
      <div class="glass rounded-2xl p-6">
        <h2 class="text-sm font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-4">Resource Usage</h2>
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          <ResourceBar label="Disk Space" :used="user.disk_used || 0" :limit="user.disk_limit || 0" :format-fn="formatSize" />
          <ResourceBar label="Bandwidth" :used="user.bandwidth_used || 0" :limit="user.bandwidth_limit || 0" :format-fn="formatSize" />
          <ResourceBar label="Domains" :used="user.domain_count || 0" :limit="user.domain_limit || 0" />
          <ResourceBar label="Databases" :used="user.db_count || 0" :limit="user.db_limit || 0" />
          <ResourceBar label="Email Accounts" :used="user.email_count || 0" :limit="user.email_limit || 0" />
        </div>
      </div>

      <!-- User's Domains -->
      <div class="glass rounded-2xl p-0 overflow-hidden">
        <div class="px-6 py-4 border-b border-[var(--border)]">
          <h2 class="text-sm font-semibold text-[var(--text-muted)] uppercase tracking-wider">Domains ({{ userDomains.length }})</h2>
        </div>
        <div v-if="userDomains.length === 0" class="px-6 py-8 text-center">
          <p class="text-sm text-[var(--text-muted)]">No domains.</p>
        </div>
        <div v-else class="divide-y divide-[var(--border)]">
          <div
            v-for="domain in userDomains"
            :key="domain.id"
            class="flex items-center justify-between px-6 py-3 hover:bg-[var(--surface-elevated)] transition-colors"
          >
            <div class="flex items-center gap-3">
              <span class="text-base">&#127760;</span>
              <div>
                <p class="text-sm font-medium text-[var(--text-primary)]">{{ domain.name }}</p>
                <p class="text-xs text-[var(--text-muted)]">PHP {{ domain.php_version || '--' }}</p>
              </div>
            </div>
            <StatusBadge
              :status="domain.ssl_enabled ? 'active' : 'inactive'"
              :label="domain.ssl_enabled ? 'SSL Active' : 'No SSL'"
            />
          </div>
        </div>
      </div>

      <!-- User's Databases -->
      <div class="glass rounded-2xl p-0 overflow-hidden">
        <div class="px-6 py-4 border-b border-[var(--border)]">
          <h2 class="text-sm font-semibold text-[var(--text-muted)] uppercase tracking-wider">Databases ({{ userDatabases.length }})</h2>
        </div>
        <div v-if="userDatabases.length === 0" class="px-6 py-8 text-center">
          <p class="text-sm text-[var(--text-muted)]">No databases.</p>
        </div>
        <div v-else class="divide-y divide-[var(--border)]">
          <div
            v-for="db in userDatabases"
            :key="db.id"
            class="flex items-center justify-between px-6 py-3 hover:bg-[var(--surface-elevated)] transition-colors"
          >
            <div class="flex items-center gap-3">
              <span class="text-base">&#128451;</span>
              <div>
                <p class="text-sm font-medium text-[var(--text-primary)] font-mono">{{ db.name }}</p>
                <p class="text-xs text-[var(--text-muted)]">{{ db.type || 'PostgreSQL' }} &middot; {{ formatSize(db.size) }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- Edit User Modal -->
    <Modal v-model="showEditModal" title="Edit User" size="md">
      <form class="space-y-4" @submit.prevent="handleEdit">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Email</label>
          <input
            v-model="editForm.email"
            type="email"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Package</label>
          <select
            v-model="editForm.package_id"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          >
            <option :value="null">No Package</option>
            <option v-for="pkg in availablePackages" :key="pkg.id" :value="pkg.id">{{ pkg.name }}</option>
          </select>
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Role</label>
          <select
            v-model="editForm.role"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          >
            <option value="user">User</option>
            <option value="reseller">Reseller</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">New Password (leave blank to keep current)</label>
          <input
            v-model="editForm.password"
            type="password"
            placeholder="New password"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
      </form>
      <template #actions>
        <button class="btn-secondary" @click="showEditModal = false">Cancel</button>
        <button class="btn-primary" :disabled="submitting" @click="handleEdit">
          <span v-if="submitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          {{ submitting ? 'Saving...' : 'Save Changes' }}
        </button>
      </template>
    </Modal>

    <!-- Delete Confirm -->
    <ConfirmDialog
      v-model="showDeleteDialog"
      title="Delete User"
      :message="`Are you sure you want to delete user '${user?.username}'? All associated data will be permanently removed.`"
      confirm-text="Delete User"
      :destructive="true"
      @confirm="handleDelete"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, watch, defineComponent, h, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import StatusBadge from '@/components/StatusBadge.vue'

const route = useRoute()
const router = useRouter()
const notifications = useNotificationsStore()

const user = ref(null)
const userDomains = ref([])
const userDatabases = ref([])
const availablePackages = ref([])
const loading = ref(false)
const submitting = ref(false)

const showEditModal = ref(false)
const showDeleteDialog = ref(false)

const editForm = ref({ email: '', package_id: null, role: 'user', password: '' })

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return '--'
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

function formatDate(dateStr) {
  if (!dateStr) return '--'
  return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

async function fetchUser() {
  loading.value = true
  try {
    const { data } = await client.get(`/users/${route.params.id}`)
    user.value = data
    editForm.value = {
      email: data.email || '',
      package_id: data.package_id || null,
      role: data.role || 'user',
      password: ''
    }
  } catch {
    notifications.error('Failed to load user.')
    router.push({ name: 'users' })
  } finally {
    loading.value = false
  }
}

async function fetchUserDomains() {
  try {
    const { data } = await client.get(`/users/${route.params.id}/domains`)
    userDomains.value = data
  } catch {
    userDomains.value = []
  }
}

async function fetchUserDatabases() {
  try {
    const { data } = await client.get(`/users/${route.params.id}/databases`)
    userDatabases.value = data
  } catch {
    userDatabases.value = []
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

async function handleEdit() {
  submitting.value = true
  try {
    const payload = { ...editForm.value }
    if (!payload.password) delete payload.password
    const { data } = await client.put(`/users/${route.params.id}`, payload)
    user.value = { ...user.value, ...data }
    notifications.success('User updated.')
    showEditModal.value = false
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to update user.')
  } finally {
    submitting.value = false
  }
}

async function handleSuspend() {
  try {
    await client.post(`/users/${route.params.id}/suspend`)
    user.value.status = 'suspended'
    notifications.success(`User '${user.value.username}' suspended.`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to suspend user.')
  }
}

async function handleUnsuspend() {
  try {
    await client.post(`/users/${route.params.id}/unsuspend`)
    user.value.status = 'active'
    notifications.success(`User '${user.value.username}' unsuspended.`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to unsuspend user.')
  }
}

async function handleDelete() {
  try {
    await client.delete(`/users/${route.params.id}`)
    notifications.success(`User '${user.value.username}' deleted.`)
    router.push({ name: 'users' })
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete user.')
  }
}

onMounted(() => {
  fetchUser()
  fetchUserDomains()
  fetchUserDatabases()
  fetchPackages()
})
</script>

<script>
// ResourceBar inline component
const ResourceBar = defineComponent({
  name: 'ResourceBar',
  props: {
    label: String,
    used: { type: Number, default: 0 },
    limit: { type: Number, default: 0 },
    formatFn: { type: Function, default: null }
  },
  setup(props) {
    const pct = computed(() => {
      if (!props.limit) return 0
      return Math.min(Math.round((props.used / props.limit) * 100), 100)
    })

    const barClass = computed(() => {
      if (pct.value >= 90) return 'bg-error'
      if (pct.value >= 70) return 'bg-warning'
      return 'bg-primary'
    })

    const display = (val) => {
      if (props.formatFn) return props.formatFn(val)
      return val
    }

    return () => h('div', null, [
      h('div', { class: 'flex items-center justify-between mb-1.5' }, [
        h('span', { class: 'text-sm text-[var(--text-muted)]' }, props.label),
        h('span', { class: 'text-xs text-[var(--text-primary)] font-mono' },
          props.limit === 0
            ? `${display(props.used)} / Unlimited`
            : `${display(props.used)} / ${display(props.limit)}`
        )
      ]),
      h('div', { class: 'h-2 bg-[var(--border)] rounded-full overflow-hidden' }, [
        h('div', {
          class: `h-full rounded-full transition-all duration-500 ${barClass.value}`,
          style: { width: pct.value + '%' }
        })
      ]),
      h('div', { class: 'text-right mt-0.5' }, [
        h('span', { class: 'text-xs text-[var(--text-muted)]' }, pct.value + '%')
      ])
    ])
  }
})

export { ResourceBar }
</script>
