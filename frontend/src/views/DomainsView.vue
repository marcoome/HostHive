<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <h1 class="text-2xl font-semibold text-[var(--text-primary)]">Domains</h1>
      <button class="btn-primary inline-flex items-center gap-2" @click="showAddModal = true">
        <span class="text-lg leading-none">+</span>
        Add Domain
      </button>
    </div>

    <!-- Search/Filter Bar -->
    <div class="glass rounded-2xl p-6">
      <div class="flex flex-col sm:flex-row gap-4">
        <div class="relative flex-1">
          <span class="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]">&#128269;</span>
          <input
            v-model="search"
            type="text"
            placeholder="Search domains..."
            class="w-full pl-10 pr-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
          />
        </div>
        <select
          v-model="phpFilter"
          class="px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
        >
          <option value="">All PHP versions</option>
          <option v-for="v in phpVersions" :key="v" :value="v">PHP {{ v }}</option>
        </select>
      </div>
    </div>

    <!-- Domains Table -->
    <div class="glass rounded-2xl p-0 overflow-hidden">
      <DataTable
        :columns="columns"
        :rows="filteredDomains"
        :loading="store.loading"
        empty-text="No domains yet. Add your first domain to get started."
      >
        <template #cell-name="{ row }">
          <router-link
            :to="{ name: 'domain-detail', params: { id: row.id } }"
            class="text-primary hover:underline font-medium transition-colors"
          >
            {{ row.name }}
          </router-link>
        </template>

        <template #cell-php_version="{ value }">
          <span class="inline-flex items-center px-2.5 py-0.5 rounded-badge text-xs font-medium bg-primary/10 text-primary">
            PHP {{ value }}
          </span>
        </template>

        <template #cell-ssl_enabled="{ row }">
          <StatusBadge
            :status="row.ssl_enabled ? 'enabled' : 'disabled'"
            :label="row.ssl_enabled ? 'Active' : 'None'"
          />
        </template>

        <template #cell-disk_usage="{ value }">
          <span class="text-sm text-[var(--text-muted)]">{{ formatBytes(value) }}</span>
        </template>

        <template #actions="{ row }">
          <div class="flex items-center justify-end gap-1 flex-wrap">
            <router-link
              :to="{ name: 'domain-detail', params: { id: row.id } }"
              class="btn-ghost text-xs px-3 py-1.5 min-h-[36px] inline-flex items-center"
              title="Edit"
            >
              Edit
            </router-link>
            <button
              class="btn-ghost text-xs px-3 py-1.5 min-h-[36px]"
              title="SSL"
              @click="goToSSL(row)"
            >
              SSL
            </button>
            <button
              class="btn-ghost text-xs px-3 py-1.5 min-h-[36px] text-error hover:text-error"
              title="Delete"
              @click="confirmDelete(row)"
            >
              Delete
            </button>
          </div>
        </template>
      </DataTable>
    </div>

    <!-- Add Domain Modal -->
    <Modal v-model="showAddModal" title="Add Domain" size="md">
      <form @submit.prevent="handleAdd" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Domain Name</label>
          <input
            v-model="form.name"
            type="text"
            placeholder="example.com"
            required
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
            :class="{ 'border-error': formErrors.name }"
          />
          <p v-if="formErrors.name" class="mt-1 text-xs text-error">{{ formErrors.name }}</p>
        </div>

        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Document Root</label>
          <input
            :value="documentRoot"
            type="text"
            readonly
            class="w-full px-4 py-2 bg-[var(--background)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-muted)] cursor-not-allowed"
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">PHP Version</label>
          <select
            v-model="form.php_version"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
          >
            <option v-for="v in phpVersions" :key="v" :value="v">PHP {{ v }}</option>
          </select>
        </div>

        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Web Server</label>
          <select
            v-model="form.webserver"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
          >
            <option value="nginx">Nginx</option>
            <option value="apache">Apache</option>
            <option value="nginx_apache">Nginx + Apache (reverse proxy)</option>
          </select>
          <p class="mt-1 text-xs text-[var(--text-muted)]">
            Nginx + Apache uses Nginx as reverse proxy with Apache handling PHP and .htaccess on port 8080.
          </p>
        </div>
      </form>

      <template #actions>
        <button class="btn-secondary" @click="showAddModal = false">Cancel</button>
        <button class="btn-primary" :disabled="submitting" @click="handleAdd">
          <span v-if="submitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          {{ submitting ? 'Adding...' : 'Add Domain' }}
        </button>
      </template>
    </Modal>

    <!-- Delete Confirm Dialog -->
    <ConfirmDialog
      v-model="showDeleteDialog"
      title="Delete Domain"
      :message="`Are you sure you want to delete '${domainToDelete?.name}'? All files, databases, and email accounts associated with this domain will be permanently removed.`"
      confirm-text="Delete Domain"
      :destructive="true"
      @confirm="handleDelete"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useDomainsStore } from '@/stores/domains'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'
import DataTable from '@/components/DataTable.vue'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import StatusBadge from '@/components/StatusBadge.vue'

const router = useRouter()
const store = useDomainsStore()
const auth = useAuthStore()
const notifications = useNotificationsStore()

const phpVersions = ['8.5', '8.4', '8.3', '8.2', '8.1', '8.0', '7.4']

const columns = [
  { key: 'name', label: 'Domain' },
  { key: 'php_version', label: 'PHP' },
  { key: 'ssl_enabled', label: 'SSL' },
  { key: 'disk_usage', label: 'Disk Usage' }
]

const search = ref('')
const phpFilter = ref('')
const showAddModal = ref(false)
const showDeleteDialog = ref(false)
const domainToDelete = ref(null)
const submitting = ref(false)

const form = ref({
  name: '',
  php_version: '8.2',
  webserver: 'nginx'
})
const formErrors = ref({})

const currentUser = computed(() => auth.user?.username || 'user')

const documentRoot = computed(() => {
  const domain = form.value.name || 'example.com'
  return `/home/${currentUser.value}/web/${domain}/public_html`
})

const filteredDomains = computed(() => {
  let result = Array.isArray(store.domains) ? store.domains : []
  if (search.value) {
    const q = search.value.toLowerCase()
    result = result.filter(d => d.name.toLowerCase().includes(q))
  }
  if (phpFilter.value) {
    result = result.filter(d => d.php_version === phpFilter.value)
  }
  return result
})

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return '--'
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

function validateForm() {
  const errors = {}
  if (!form.value.name.trim()) {
    errors.name = 'Domain name is required.'
  } else if (!/^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$/.test(form.value.name.trim())) {
    errors.name = 'Enter a valid domain name (e.g. example.com).'
  }
  formErrors.value = errors
  return Object.keys(errors).length === 0
}

async function handleAdd() {
  if (!validateForm()) return
  submitting.value = true
  try {
    await store.create({
      name: form.value.name.trim(),
      document_root: documentRoot.value,
      php_version: form.value.php_version,
      webserver: form.value.webserver
    })
    notifications.success(`Domain '${form.value.name}' added successfully.`)
    showAddModal.value = false
    form.value = { name: '', php_version: '8.2', webserver: 'nginx' }
    formErrors.value = {}
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to add domain.')
  } finally {
    submitting.value = false
  }
}

function confirmDelete(domain) {
  domainToDelete.value = domain
  showDeleteDialog.value = true
}

async function handleDelete() {
  if (!domainToDelete.value) return
  try {
    await store.remove(domainToDelete.value.id)
    notifications.success(`Domain '${domainToDelete.value.name}' deleted.`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete domain.')
  } finally {
    domainToDelete.value = null
  }
}

function goToSSL(domain) {
  router.push({ name: 'domain-detail', params: { id: domain.id }, query: { tab: 'ssl' } })
}

// Reset form when modal closes
watch(showAddModal, (val) => {
  if (!val) {
    form.value = { name: '', php_version: '8.2', webserver: 'nginx' }
    formErrors.value = {}
  }
})

onMounted(() => {
  store.fetchAll()
})
</script>
