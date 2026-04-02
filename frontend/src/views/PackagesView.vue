<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <h1 class="text-2xl font-semibold text-[var(--text-primary)]">Packages</h1>
      <button class="btn-primary inline-flex items-center gap-2" @click="openCreateModal">
        <span class="text-lg leading-none">+</span>
        Create Package
      </button>
    </div>

    <!-- Loading Skeleton -->
    <div v-if="loading" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
      <div v-for="i in 6" :key="i" class="glass rounded-2xl p-6 space-y-4">
        <div class="skeleton h-6 w-32 rounded"></div>
        <div class="skeleton h-4 w-full rounded"></div>
        <div class="skeleton h-4 w-3/4 rounded"></div>
        <div class="skeleton h-4 w-1/2 rounded"></div>
      </div>
    </div>

    <!-- Package Cards Grid -->
    <div v-else-if="packages.length > 0" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
      <div
        v-for="pkg in packages"
        :key="pkg.id"
        class="glass rounded-2xl p-6 flex flex-col"
      >
        <!-- Header -->
        <div class="flex items-start justify-between mb-4">
          <div>
            <h3 class="text-lg font-semibold text-[var(--text-primary)]">{{ pkg.name }}</h3>
            <div class="flex items-center gap-2 mt-1">
              <span class="text-2xl font-bold text-primary">
                ${{ pkg.price_monthly || 0 }}
              </span>
              <span class="text-xs text-[var(--text-muted)]">/month</span>
            </div>
          </div>
          <div class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-primary/10 text-primary text-xs font-medium">
            {{ pkg.user_count || 0 }} users
          </div>
        </div>

        <!-- Resource Limits -->
        <div class="space-y-3 flex-1">
          <div class="flex items-center justify-between text-sm">
            <span class="text-[var(--text-muted)]">Disk Space</span>
            <span class="text-[var(--text-primary)] font-medium font-mono">{{ pkg.disk_limit === 0 ? 'Unlimited' : formatSize(pkg.disk_limit) }}</span>
          </div>
          <div class="flex items-center justify-between text-sm">
            <span class="text-[var(--text-muted)]">Bandwidth</span>
            <span class="text-[var(--text-primary)] font-medium font-mono">{{ pkg.bandwidth_limit === 0 ? 'Unlimited' : formatSize(pkg.bandwidth_limit) }}</span>
          </div>
          <div class="flex items-center justify-between text-sm">
            <span class="text-[var(--text-muted)]">Domains</span>
            <span class="text-[var(--text-primary)] font-medium font-mono">{{ pkg.domain_limit === 0 ? 'Unlimited' : pkg.domain_limit }}</span>
          </div>
          <div class="flex items-center justify-between text-sm">
            <span class="text-[var(--text-muted)]">Databases</span>
            <span class="text-[var(--text-primary)] font-medium font-mono">{{ pkg.db_limit === 0 ? 'Unlimited' : pkg.db_limit }}</span>
          </div>
          <div class="flex items-center justify-between text-sm">
            <span class="text-[var(--text-muted)]">Email Accounts</span>
            <span class="text-[var(--text-primary)] font-medium font-mono">{{ pkg.email_limit === 0 ? 'Unlimited' : pkg.email_limit }}</span>
          </div>
        </div>

        <!-- Actions -->
        <div class="flex items-center gap-2 mt-5 pt-4 border-t border-[var(--border)]">
          <button class="btn-ghost text-xs px-3 py-1.5 flex-1" @click="openEditModal(pkg)">
            Edit
          </button>
          <button
            class="btn-ghost text-xs px-3 py-1.5 flex-1 text-error hover:text-error"
            :disabled="pkg.user_count > 0"
            :title="pkg.user_count > 0 ? 'Cannot delete: users assigned' : 'Delete package'"
            @click="confirmDeletePackage(pkg)"
          >
            Delete
          </button>
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-else class="glass rounded-2xl p-12 text-center">
      <div class="text-4xl mb-3">&#128230;</div>
      <p class="text-[var(--text-muted)] text-sm">No packages yet. Create your first hosting package.</p>
    </div>

    <!-- Create/Edit Package Modal -->
    <Modal v-model="showModal" :title="editingPackage ? 'Edit Package' : 'Create Package'" size="lg">
      <form class="space-y-5" @submit.prevent="handleSave">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Package Name</label>
          <input
            v-model="form.name"
            type="text"
            placeholder="Basic, Pro, Enterprise..."
            required
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Price ($/month)</label>
          <input
            v-model.number="form.price_monthly"
            type="number"
            step="0.01"
            min="0"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <!-- Disk Space -->
          <div>
            <div class="flex items-center justify-between mb-1">
              <label class="text-sm font-medium text-[var(--text-primary)]">Disk Space (MB)</label>
              <span class="text-xs text-[var(--text-muted)] font-mono">{{ form.disk_limit === 0 ? 'Unlimited' : form.disk_limit + ' MB' }}</span>
            </div>
            <input
              v-model.number="form.disk_limit"
              type="range"
              min="0"
              max="102400"
              step="1024"
              class="w-full accent-primary"
            />
            <div class="flex justify-between text-xs text-[var(--text-muted)] mt-0.5">
              <span>Unlimited</span>
              <span>100 GB</span>
            </div>
          </div>

          <!-- Bandwidth -->
          <div>
            <div class="flex items-center justify-between mb-1">
              <label class="text-sm font-medium text-[var(--text-primary)]">Bandwidth (MB)</label>
              <span class="text-xs text-[var(--text-muted)] font-mono">{{ form.bandwidth_limit === 0 ? 'Unlimited' : form.bandwidth_limit + ' MB' }}</span>
            </div>
            <input
              v-model.number="form.bandwidth_limit"
              type="range"
              min="0"
              max="1048576"
              step="10240"
              class="w-full accent-primary"
            />
            <div class="flex justify-between text-xs text-[var(--text-muted)] mt-0.5">
              <span>Unlimited</span>
              <span>1 TB</span>
            </div>
          </div>

          <!-- Domains -->
          <div>
            <div class="flex items-center justify-between mb-1">
              <label class="text-sm font-medium text-[var(--text-primary)]">Domains</label>
              <span class="text-xs text-[var(--text-muted)] font-mono">{{ form.domain_limit === 0 ? 'Unlimited' : form.domain_limit }}</span>
            </div>
            <input
              v-model.number="form.domain_limit"
              type="range"
              min="0"
              max="100"
              step="1"
              class="w-full accent-primary"
            />
            <div class="flex justify-between text-xs text-[var(--text-muted)] mt-0.5">
              <span>Unlimited</span>
              <span>100</span>
            </div>
          </div>

          <!-- Databases -->
          <div>
            <div class="flex items-center justify-between mb-1">
              <label class="text-sm font-medium text-[var(--text-primary)]">Databases</label>
              <span class="text-xs text-[var(--text-muted)] font-mono">{{ form.db_limit === 0 ? 'Unlimited' : form.db_limit }}</span>
            </div>
            <input
              v-model.number="form.db_limit"
              type="range"
              min="0"
              max="100"
              step="1"
              class="w-full accent-primary"
            />
            <div class="flex justify-between text-xs text-[var(--text-muted)] mt-0.5">
              <span>Unlimited</span>
              <span>100</span>
            </div>
          </div>

          <!-- Email Accounts -->
          <div class="sm:col-span-2">
            <div class="flex items-center justify-between mb-1">
              <label class="text-sm font-medium text-[var(--text-primary)]">Email Accounts</label>
              <span class="text-xs text-[var(--text-muted)] font-mono">{{ form.email_limit === 0 ? 'Unlimited' : form.email_limit }}</span>
            </div>
            <input
              v-model.number="form.email_limit"
              type="range"
              min="0"
              max="500"
              step="5"
              class="w-full accent-primary"
            />
            <div class="flex justify-between text-xs text-[var(--text-muted)] mt-0.5">
              <span>Unlimited</span>
              <span>500</span>
            </div>
          </div>
        </div>
      </form>

      <template #actions>
        <button class="btn-secondary" @click="showModal = false">Cancel</button>
        <button class="btn-primary" :disabled="submitting || !form.name.trim()" @click="handleSave">
          <span v-if="submitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          {{ submitting ? 'Saving...' : (editingPackage ? 'Save Changes' : 'Create Package') }}
        </button>
      </template>
    </Modal>

    <!-- Delete Confirm -->
    <ConfirmDialog
      v-model="showDeleteDialog"
      title="Delete Package"
      :message="`Are you sure you want to delete the package '${packageToDelete?.name}'?`"
      confirm-text="Delete Package"
      :destructive="true"
      @confirm="handleDelete"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const notifications = useNotificationsStore()

const packages = ref([])
const loading = ref(false)
const submitting = ref(false)
const showModal = ref(false)
const showDeleteDialog = ref(false)
const editingPackage = ref(null)
const packageToDelete = ref(null)

const defaultForm = {
  name: '',
  price_monthly: 0,
  disk_limit: 10240,
  bandwidth_limit: 102400,
  domain_limit: 10,
  db_limit: 5,
  email_limit: 20
}

const form = ref({ ...defaultForm })

function formatSize(mb) {
  if (!mb && mb !== 0) return '--'
  if (mb >= 1024) return (mb / 1024).toFixed(1) + ' GB'
  return mb + ' MB'
}

async function fetchPackages() {
  loading.value = true
  try {
    const { data } = await client.get('/packages')
    packages.value = data
  } catch {
    notifications.error('Failed to load packages.')
  } finally {
    loading.value = false
  }
}

function openCreateModal() {
  editingPackage.value = null
  form.value = { ...defaultForm }
  showModal.value = true
}

function openEditModal(pkg) {
  editingPackage.value = pkg
  form.value = {
    name: pkg.name,
    price_monthly: pkg.price_monthly || 0,
    disk_limit: pkg.disk_limit || 0,
    bandwidth_limit: pkg.bandwidth_limit || 0,
    domain_limit: pkg.domain_limit || 0,
    db_limit: pkg.db_limit || 0,
    email_limit: pkg.email_limit || 0
  }
  showModal.value = true
}

async function handleSave() {
  if (!form.value.name.trim()) return
  submitting.value = true
  try {
    if (editingPackage.value) {
      const { data } = await client.put(`/packages/${editingPackage.value.id}`, form.value)
      const idx = packages.value.findIndex(p => p.id === editingPackage.value.id)
      if (idx >= 0) packages.value[idx] = data
      notifications.success('Package updated.')
    } else {
      const { data } = await client.post('/packages', form.value)
      packages.value.push(data)
      notifications.success('Package created.')
    }
    showModal.value = false
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to save package.')
  } finally {
    submitting.value = false
  }
}

function confirmDeletePackage(pkg) {
  packageToDelete.value = pkg
  showDeleteDialog.value = true
}

async function handleDelete() {
  if (!packageToDelete.value) return
  try {
    await client.delete(`/packages/${packageToDelete.value.id}`)
    packages.value = packages.value.filter(p => p.id !== packageToDelete.value.id)
    notifications.success('Package deleted.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete package.')
  } finally {
    packageToDelete.value = null
  }
}

watch(showModal, v => {
  if (!v) {
    editingPackage.value = null
    form.value = { ...defaultForm }
  }
})

onMounted(() => {
  fetchPackages()
})
</script>
