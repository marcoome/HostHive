<template>
  <div class="space-y-6">
    <!-- Back Button + Header -->
    <div class="flex items-center gap-4">
      <button
        class="btn-ghost p-2 rounded-lg"
        @click="$router.push({ name: 'domains' })"
        title="Back to domains"
      >
        &#8592;
      </button>
      <div class="flex-1">
        <h1 class="text-2xl font-semibold text-[var(--text-primary)]">
          {{ domain?.name || 'Domain Details' }}
        </h1>
        <p v-if="domain" class="text-sm text-[var(--text-muted)] mt-1">
          Created {{ formatDate(domain.created_at) }}
        </p>
      </div>
      <StatusBadge
        v-if="domain"
        :status="domain.ssl_enabled ? 'enabled' : 'disabled'"
        :label="domain.ssl_enabled ? 'SSL Active' : 'No SSL'"
      />
    </div>

    <!-- Loading skeleton -->
    <div v-if="store.loading && !domain" class="space-y-4">
      <div class="glass rounded-2xl p-6">
        <LoadingSkeleton class="h-6 w-48 mb-4" />
        <LoadingSkeleton class="h-4 w-full mb-2" />
        <LoadingSkeleton class="h-4 w-3/4 mb-2" />
        <LoadingSkeleton class="h-4 w-1/2" />
      </div>
    </div>

    <!-- Tabs -->
    <div v-else-if="domain">
      <div class="flex border-b border-[var(--border)] mb-6 overflow-x-auto">
        <button
          v-for="tab in tabs"
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

      <!-- Overview Tab -->
      <Transition name="fade" mode="out-in">
        <div v-if="activeTab === 'overview'" key="overview" class="space-y-6">
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- Domain Info -->
            <div class="glass rounded-2xl p-6">
              <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Domain Information</h3>
              <dl class="space-y-3">
                <div class="flex justify-between">
                  <dt class="text-sm text-[var(--text-muted)]">Domain Name</dt>
                  <dd class="text-sm text-[var(--text-primary)] font-medium">{{ domain.name }}</dd>
                </div>
                <div class="flex justify-between">
                  <dt class="text-sm text-[var(--text-muted)]">Document Root</dt>
                  <dd class="text-sm text-[var(--text-primary)] font-mono text-right break-all">{{ domain.document_root || `/home/${auth.user?.username}/web/${domain.name}/public_html` }}</dd>
                </div>
                <div class="flex justify-between">
                  <dt class="text-sm text-[var(--text-muted)]">PHP Version</dt>
                  <dd>
                    <span class="inline-flex items-center px-2.5 py-0.5 rounded-badge text-xs font-medium bg-primary/10 text-primary">
                      PHP {{ domain.php_version }}
                    </span>
                  </dd>
                </div>
                <div class="flex justify-between">
                  <dt class="text-sm text-[var(--text-muted)]">Disk Usage</dt>
                  <dd class="text-sm text-[var(--text-primary)]">{{ formatBytes(domain.disk_usage) }}</dd>
                </div>
                <div class="flex justify-between">
                  <dt class="text-sm text-[var(--text-muted)]">Created</dt>
                  <dd class="text-sm text-[var(--text-primary)]">{{ formatDate(domain.created_at) }}</dd>
                </div>
              </dl>
            </div>

            <!-- Quick Actions -->
            <div class="glass rounded-2xl p-6">
              <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Quick Actions</h3>
              <div class="space-y-3">
                <button class="w-full btn-secondary text-left px-4 py-3 rounded-lg flex items-center justify-between" @click="showEditPhp = true">
                  <span class="text-sm">Change PHP Version</span>
                  <span class="text-xs text-[var(--text-muted)]">Currently PHP {{ domain.php_version }}</span>
                </button>
                <button class="w-full btn-secondary text-left px-4 py-3 rounded-lg flex items-center justify-between" @click="activeTab = 'ssl'">
                  <span class="text-sm">Manage SSL</span>
                  <span class="text-xs text-[var(--text-muted)]">{{ domain.ssl_enabled ? 'Active' : 'Not configured' }}</span>
                </button>
                <button class="w-full btn-secondary text-left px-4 py-3 rounded-lg flex items-center justify-between" @click="activeTab = 'logs'">
                  <span class="text-sm">View Logs</span>
                  <span class="text-xs text-[var(--text-muted)]">Nginx access &amp; error</span>
                </button>
                <button class="w-full btn-secondary text-left px-4 py-3 rounded-lg flex items-center justify-between text-error" @click="showDeleteDialog = true">
                  <span class="text-sm">Delete Domain</span>
                  <span class="text-xs">Permanent action</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- SSL Tab -->
        <div v-else-if="activeTab === 'ssl'" key="ssl" class="space-y-6">
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- Current Certificate -->
            <div class="glass rounded-2xl p-6">
              <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">SSL Certificate</h3>
              <div v-if="domain.ssl_enabled" class="space-y-3">
                <dl class="space-y-3">
                  <div class="flex justify-between">
                    <dt class="text-sm text-[var(--text-muted)]">Issuer</dt>
                    <dd class="text-sm text-[var(--text-primary)]">{{ domain.ssl_issuer || "Let's Encrypt" }}</dd>
                  </div>
                  <div class="flex justify-between">
                    <dt class="text-sm text-[var(--text-muted)]">Expires</dt>
                    <dd class="text-sm text-[var(--text-primary)]">{{ formatDate(domain.ssl_expiry) }}</dd>
                  </div>
                  <div class="flex justify-between">
                    <dt class="text-sm text-[var(--text-muted)]">Days Remaining</dt>
                    <dd class="text-sm font-medium" :class="sslDaysRemaining > 14 ? 'text-success' : sslDaysRemaining > 7 ? 'text-warning' : 'text-error'">
                      {{ sslDaysRemaining }} days
                    </dd>
                  </div>
                </dl>
                <div class="flex items-center justify-between pt-3 border-t border-[var(--border)]">
                  <span class="text-sm text-[var(--text-muted)]">Auto-renew</span>
                  <button
                    class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
                    :class="autoRenew ? 'bg-primary' : 'bg-[var(--border)]'"
                    @click="toggleAutoRenew"
                  >
                    <span
                      class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
                      :class="autoRenew ? 'translate-x-6' : 'translate-x-1'"
                    />
                  </button>
                </div>
              </div>
              <div v-else class="text-center py-6">
                <p class="text-[var(--text-muted)] text-sm mb-2">No SSL certificate installed</p>
                <p class="text-[var(--text-muted)] text-xs">Issue a free certificate or upload your own.</p>
              </div>
            </div>

            <!-- SSL Actions -->
            <div class="glass rounded-2xl p-6">
              <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Actions</h3>
              <div class="space-y-3">
                <button class="w-full btn-primary py-3" :disabled="issuingSSL" @click="issueSSL">
                  <span v-if="issuingSSL" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
                  {{ issuingSSL ? 'Issuing...' : "Issue Let's Encrypt SSL" }}
                </button>
                <button class="w-full btn-secondary py-3" @click="showUploadCert = true">
                  Upload Custom Certificate
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Logs Tab -->
        <div v-else-if="activeTab === 'logs'" key="logs" class="space-y-6">
          <div class="glass rounded-2xl p-6">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-lg font-semibold text-[var(--text-primary)]">Nginx Logs</h3>
              <div class="flex gap-2">
                <button
                  class="text-xs px-3 py-1.5 rounded-lg transition-colors"
                  :class="logType === 'access' ? 'bg-primary text-white' : 'btn-ghost'"
                  @click="logType = 'access'"
                >
                  Access Log
                </button>
                <button
                  class="text-xs px-3 py-1.5 rounded-lg transition-colors"
                  :class="logType === 'error' ? 'bg-primary text-white' : 'btn-ghost'"
                  @click="logType = 'error'"
                >
                  Error Log
                </button>
              </div>
            </div>
            <div
              ref="logContainer"
              class="bg-[var(--background)] rounded-lg p-4 h-96 overflow-y-auto font-mono text-xs text-[var(--text-primary)] leading-relaxed border border-[var(--border)]"
            >
              <div v-if="logsLoading" class="space-y-1">
                <LoadingSkeleton v-for="i in 10" :key="i" class="h-3 w-full" />
              </div>
              <div v-else-if="logLines.length === 0" class="text-center text-[var(--text-muted)] py-8">
                No log entries found.
              </div>
              <div v-else>
                <div v-for="(line, i) in logLines" :key="i" class="hover:bg-[var(--surface)] px-1 rounded">
                  {{ line }}
                </div>
              </div>
            </div>
            <div class="flex justify-end mt-3">
              <button class="btn-ghost text-xs" @click="fetchLogs">Refresh</button>
            </div>
          </div>
        </div>

        <!-- Stats Tab -->
        <div v-else-if="activeTab === 'stats'" key="stats" class="space-y-6">
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- Bandwidth Chart -->
            <div class="glass rounded-2xl p-6">
              <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Bandwidth (Last 7 Days)</h3>
              <div v-if="statsLoading" class="space-y-3">
                <LoadingSkeleton v-for="i in 7" :key="i" class="h-8 w-full" />
              </div>
              <div v-else class="space-y-2">
                <div v-for="day in bandwidthData" :key="day.date" class="flex items-center gap-3">
                  <span class="text-xs text-[var(--text-muted)] w-16 shrink-0">{{ formatShortDate(day.date) }}</span>
                  <div class="flex-1 bg-[var(--background)] rounded-full h-6 overflow-hidden">
                    <div
                      class="h-full bg-primary/70 rounded-full transition-all duration-500"
                      :style="{ width: bandwidthPercent(day.bytes) + '%' }"
                    />
                  </div>
                  <span class="text-xs text-[var(--text-muted)] w-20 text-right shrink-0">{{ formatBytes(day.bytes) }}</span>
                </div>
              </div>
            </div>

            <!-- Requests Chart -->
            <div class="glass rounded-2xl p-6">
              <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Requests per Day (Last 7 Days)</h3>
              <div v-if="statsLoading" class="space-y-3">
                <LoadingSkeleton v-for="i in 7" :key="i" class="h-8 w-full" />
              </div>
              <div v-else class="space-y-2">
                <div v-for="day in requestsData" :key="day.date" class="flex items-center gap-3">
                  <span class="text-xs text-[var(--text-muted)] w-16 shrink-0">{{ formatShortDate(day.date) }}</span>
                  <div class="flex-1 bg-[var(--background)] rounded-full h-6 overflow-hidden">
                    <div
                      class="h-full bg-success/70 rounded-full transition-all duration-500"
                      :style="{ width: requestsPercent(day.count) + '%' }"
                    />
                  </div>
                  <span class="text-xs text-[var(--text-muted)] w-16 text-right shrink-0">{{ day.count.toLocaleString() }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </div>

    <!-- Edit PHP Modal -->
    <Modal v-model="showEditPhp" title="Change PHP Version" size="sm">
      <div>
        <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">PHP Version</label>
        <select
          v-model="editPhpVersion"
          class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
        >
          <option v-for="v in phpVersions" :key="v" :value="v">PHP {{ v }}</option>
        </select>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showEditPhp = false">Cancel</button>
        <button class="btn-primary" @click="updatePhp">Save</button>
      </template>
    </Modal>

    <!-- Upload Cert Modal -->
    <Modal v-model="showUploadCert" title="Upload Custom Certificate" size="md">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Certificate (PEM)</label>
          <textarea
            v-model="certForm.certificate"
            rows="4"
            placeholder="-----BEGIN CERTIFICATE-----"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] font-mono placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Private Key (PEM)</label>
          <textarea
            v-model="certForm.private_key"
            rows="4"
            placeholder="-----BEGIN PRIVATE KEY-----"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] font-mono placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showUploadCert = false">Cancel</button>
        <button class="btn-primary" @click="uploadCert">Upload</button>
      </template>
    </Modal>

    <!-- Delete Confirm -->
    <ConfirmDialog
      v-model="showDeleteDialog"
      title="Delete Domain"
      :message="`Permanently delete '${domain?.name}' and all associated data?`"
      confirm-text="Delete"
      :destructive="true"
      @confirm="handleDelete"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDomainsStore } from '@/stores/domains'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import client from '@/api/client'

const route = useRoute()
const router = useRouter()
const store = useDomainsStore()
const auth = useAuthStore()
const notifications = useNotificationsStore()

const phpVersions = ['8.2', '8.1', '8.0', '7.4']

const tabs = [
  { key: 'overview', label: 'Overview' },
  { key: 'ssl', label: 'SSL' },
  { key: 'logs', label: 'Logs' },
  { key: 'stats', label: 'Stats' }
]

const activeTab = ref(route.query.tab || 'overview')
const domain = computed(() => store.currentDomain)

// SSL
const autoRenew = ref(true)
const issuingSSL = ref(false)
const showUploadCert = ref(false)
const certForm = ref({ certificate: '', private_key: '' })

const sslDaysRemaining = computed(() => {
  if (!domain.value?.ssl_expiry) return 0
  const diff = new Date(domain.value.ssl_expiry) - new Date()
  return Math.max(0, Math.ceil(diff / (1000 * 60 * 60 * 24)))
})

// PHP edit
const showEditPhp = ref(false)
const editPhpVersion = ref('8.2')

// Logs
const logType = ref('access')
const logLines = ref([])
const logsLoading = ref(false)
const logContainer = ref(null)

// Stats
const bandwidthData = ref([])
const requestsData = ref([])
const statsLoading = ref(false)

// Delete
const showDeleteDialog = ref(false)

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

function formatShortDate(dateStr) {
  if (!dateStr) return '--'
  return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function bandwidthPercent(bytes) {
  const max = Math.max(...bandwidthData.value.map(d => d.bytes), 1)
  return Math.round((bytes / max) * 100)
}

function requestsPercent(count) {
  const max = Math.max(...requestsData.value.map(d => d.count), 1)
  return Math.round((count / max) * 100)
}

async function fetchLogs() {
  logsLoading.value = true
  try {
    const { data } = await client.get(`/domains/${route.params.id}/logs`, {
      params: { type: logType.value, lines: 100 }
    })
    logLines.value = data.lines || []
    await nextTick()
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  } catch {
    logLines.value = []
  } finally {
    logsLoading.value = false
  }
}

async function fetchStats() {
  statsLoading.value = true
  try {
    const { data } = await client.get(`/domains/${route.params.id}/stats`)
    bandwidthData.value = data.bandwidth || []
    requestsData.value = data.requests || []
  } catch {
    bandwidthData.value = []
    requestsData.value = []
  } finally {
    statsLoading.value = false
  }
}

async function issueSSL() {
  issuingSSL.value = true
  try {
    await client.post(`/domains/${route.params.id}/ssl/issue`)
    notifications.success('SSL certificate issued successfully.')
    await store.fetchOne(route.params.id)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to issue SSL certificate.')
  } finally {
    issuingSSL.value = false
  }
}

async function uploadCert() {
  try {
    await client.post(`/domains/${route.params.id}/ssl/upload`, certForm.value)
    notifications.success('Certificate uploaded successfully.')
    showUploadCert.value = false
    certForm.value = { certificate: '', private_key: '' }
    await store.fetchOne(route.params.id)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to upload certificate.')
  }
}

function toggleAutoRenew() {
  autoRenew.value = !autoRenew.value
  client.put(`/domains/${route.params.id}/ssl/auto-renew`, { enabled: autoRenew.value })
    .then(() => notifications.success(`Auto-renew ${autoRenew.value ? 'enabled' : 'disabled'}.`))
    .catch(() => {
      autoRenew.value = !autoRenew.value
      notifications.error('Failed to update auto-renew setting.')
    })
}

function updatePhp() {
  store.update(route.params.id, { php_version: editPhpVersion.value })
    .then(() => {
      notifications.success(`PHP version changed to ${editPhpVersion.value}.`)
      showEditPhp.value = false
      store.fetchOne(route.params.id)
    })
    .catch(err => notifications.error(err.response?.data?.detail || 'Failed to update PHP version.'))
}

async function handleDelete() {
  try {
    await store.remove(route.params.id)
    notifications.success('Domain deleted.')
    router.push({ name: 'domains' })
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete domain.')
  }
}

// Tab watchers
watch(activeTab, (tab) => {
  if (tab === 'logs') fetchLogs()
  if (tab === 'stats') fetchStats()
})

watch(logType, () => {
  if (activeTab.value === 'logs') fetchLogs()
})

watch(() => domain.value, (d) => {
  if (d) {
    editPhpVersion.value = d.php_version
    autoRenew.value = d.ssl_auto_renew !== false
  }
})

onMounted(async () => {
  await store.fetchOne(route.params.id)
  if (activeTab.value === 'logs') fetchLogs()
  if (activeTab.value === 'stats') fetchStats()
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
