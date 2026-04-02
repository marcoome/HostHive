<template>
  <div class="space-y-6">
    <!-- Page Header -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">API Keys</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">
          Manage API keys for programmatic access to HostHive
        </p>
      </div>
      <button class="btn-primary" @click="showCreateModal = true">
        + Generate New Key
      </button>
    </div>

    <!-- Keys Table -->
    <DataTable
      :columns="columns"
      :rows="store.keys"
      :loading="store.loading"
      :skeleton-rows="5"
      empty-text="No API keys yet. Generate one to get started."
    >
      <template #cell-key_prefix="{ value, row }">
        <code class="text-xs px-2 py-1 rounded font-mono" :style="{ background: 'var(--surface-elevated)' }">
          {{ value || (row.key_prefix ? row.key_prefix : 'hh_') }}...
        </code>
      </template>

      <template #cell-scope="{ value }">
        <span class="badge" :class="scopeBadgeClass(value)">
          {{ value }}
        </span>
      </template>

      <template #cell-created_at="{ value }">
        <span class="text-sm">{{ formatDate(value) }}</span>
      </template>

      <template #cell-last_used="{ value }">
        <span class="text-sm" :class="{ 'text-text-muted': !value }">
          {{ value ? formatDate(value) : 'Never' }}
        </span>
      </template>

      <template #cell-expires_at="{ value }">
        <span class="text-sm" :class="isExpiringSoon(value) ? 'text-warning' : ''">
          {{ value ? formatDate(value) : 'Never' }}
        </span>
      </template>

      <template #actions="{ row }">
        <button class="btn-danger text-xs px-3 py-1" @click="confirmRevoke(row)">
          Revoke
        </button>
      </template>
    </DataTable>

    <!-- Create Key Modal -->
    <Modal v-model="showCreateModal" title="Generate New API Key" size="md">
      <div class="space-y-4">
        <div>
          <label class="input-label">Key Name</label>
          <input
            type="text"
            v-model="createForm.name"
            class="w-full"
            placeholder="e.g. CI/CD Pipeline, Monitoring Script"
          />
        </div>

        <div>
          <label class="input-label">Scope</label>
          <div class="space-y-2 mt-2">
            <label class="flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-colors" :style="{ background: createForm.scope === 'read' ? 'rgba(var(--primary-rgb), 0.1)' : 'transparent' }">
              <input type="radio" v-model="createForm.scope" value="read" class="accent-[var(--primary)]" />
              <div>
                <div class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">Read Only</div>
                <div class="text-xs" :style="{ color: 'var(--text-muted)' }">Can only read data, no modifications</div>
              </div>
            </label>
            <label class="flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-colors" :style="{ background: createForm.scope === 'full' ? 'rgba(var(--primary-rgb), 0.1)' : 'transparent' }">
              <input type="radio" v-model="createForm.scope" value="full" class="accent-[var(--primary)]" />
              <div>
                <div class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">Full Access</div>
                <div class="text-xs" :style="{ color: 'var(--text-muted)' }">Read and write access to all resources</div>
              </div>
            </label>
            <label class="flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-colors" :style="{ background: createForm.scope === 'custom' ? 'rgba(var(--primary-rgb), 0.1)' : 'transparent' }">
              <input type="radio" v-model="createForm.scope" value="custom" class="accent-[var(--primary)]" />
              <div>
                <div class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">Custom</div>
                <div class="text-xs" :style="{ color: 'var(--text-muted)' }">Select specific permissions</div>
              </div>
            </label>
          </div>
        </div>

        <!-- Custom Permissions -->
        <div v-if="createForm.scope === 'custom'" class="p-4 rounded-lg" :style="{ background: 'var(--surface-elevated)' }">
          <label class="input-label mb-3">Permissions</label>
          <div class="grid grid-cols-2 gap-2">
            <label
              v-for="perm in allPermissions"
              :key="perm"
              class="flex items-center gap-2 text-sm cursor-pointer"
            >
              <input type="checkbox" v-model="createForm.permissions" :value="perm" class="accent-[var(--primary)]" />
              <span class="capitalize">{{ perm }}</span>
            </label>
          </div>
        </div>

        <div>
          <label class="input-label">Expiration</label>
          <select v-model="createForm.expires_in" class="w-full">
            <option value="30">30 days</option>
            <option value="90">90 days</option>
            <option value="365">1 year</option>
            <option value="never">Never</option>
          </select>
        </div>
      </div>

      <template #actions>
        <button class="btn-secondary" @click="showCreateModal = false">Cancel</button>
        <button class="btn-primary" :disabled="!createForm.name || creating" @click="handleCreate">
          <span v-if="creating" class="inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin mr-1"></span>
          Generate Key
        </button>
      </template>
    </Modal>

    <!-- Key Reveal Modal -->
    <Modal v-model="showRevealModal" title="Your New API Key" size="md">
      <div class="space-y-4">
        <div class="p-4 rounded-lg border-2 border-warning/30" :style="{ background: 'rgba(245, 158, 11, 0.06)' }">
          <div class="flex items-center gap-2 mb-3">
            <span class="text-warning text-lg">&#9888;</span>
            <span class="font-semibold text-sm text-warning">This key will not be shown again. Copy it now.</span>
          </div>
          <div class="relative">
            <code
              class="block w-full p-3 rounded text-sm font-mono break-all select-all"
              :style="{ background: 'var(--bg)', color: 'var(--text-primary)' }"
            >{{ revealedKey }}</code>
            <button
              class="absolute top-2 right-2 btn-ghost text-xs px-2 py-1"
              @click="copyKey"
            >
              {{ copied ? 'Copied!' : 'Copy' }}
            </button>
          </div>
        </div>
        <p class="text-xs" :style="{ color: 'var(--text-muted)' }">
          Store this key in a secure location such as a password manager or encrypted secrets file.
          You will not be able to view it again after closing this dialog.
        </p>
      </div>

      <template #actions>
        <button class="btn-primary" @click="showRevealModal = false">
          I've Copied My Key
        </button>
      </template>
    </Modal>

    <!-- Revoke Confirm -->
    <ConfirmDialog
      v-model="showRevokeConfirm"
      title="Revoke API Key"
      :message="`Are you sure you want to revoke '${revokeTarget?.name || 'this key'}'? Any applications using this key will lose access immediately.`"
      confirm-text="Revoke Key"
      :destructive="true"
      @confirm="handleRevoke"
    />
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useApiKeysStore } from '@/stores/apiKeys'
import DataTable from '@/components/DataTable.vue'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const store = useApiKeysStore()

const showCreateModal = ref(false)
const showRevealModal = ref(false)
const showRevokeConfirm = ref(false)
const revealedKey = ref('')
const copied = ref(false)
const creating = ref(false)
const revokeTarget = ref(null)

const allPermissions = ['domains', 'databases', 'email', 'dns', 'ftp', 'cron', 'ssl', 'backups', 'files']

const createForm = reactive({
  name: '',
  scope: 'read',
  permissions: [],
  expires_in: '90'
})

const columns = [
  { key: 'name', label: 'Name' },
  { key: 'key_prefix', label: 'Key' },
  { key: 'scope', label: 'Scope' },
  { key: 'created_at', label: 'Created' },
  { key: 'last_used', label: 'Last Used' },
  { key: 'expires_at', label: 'Expires' }
]

function scopeBadgeClass(scope) {
  if (scope === 'full') return 'badge-error'
  if (scope === 'read') return 'badge-info'
  return 'badge-warning'
}

function formatDate(dateStr) {
  if (!dateStr) return '--'
  return new Date(dateStr).toLocaleDateString()
}

function isExpiringSoon(dateStr) {
  if (!dateStr) return false
  const diff = new Date(dateStr).getTime() - Date.now()
  return diff > 0 && diff < 7 * 24 * 60 * 60 * 1000
}

async function handleCreate() {
  creating.value = true
  try {
    const payload = {
      name: createForm.name,
      scope: createForm.scope,
      permissions: createForm.scope === 'custom' ? createForm.permissions : undefined,
      expires_in: createForm.expires_in === 'never' ? null : parseInt(createForm.expires_in)
    }
    const result = await store.createKey(payload)
    revealedKey.value = result.full_key || result.key || ''
    showCreateModal.value = false
    showRevealModal.value = true
    // Reset form
    createForm.name = ''
    createForm.scope = 'read'
    createForm.permissions = []
    createForm.expires_in = '90'
  } finally {
    creating.value = false
  }
}

function copyKey() {
  navigator.clipboard.writeText(revealedKey.value)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

function confirmRevoke(row) {
  revokeTarget.value = row
  showRevokeConfirm.value = true
}

async function handleRevoke() {
  if (revokeTarget.value) {
    await store.revokeKey(revokeTarget.value.id)
    revokeTarget.value = null
  }
}

onMounted(() => {
  store.fetchKeys()
})
</script>
