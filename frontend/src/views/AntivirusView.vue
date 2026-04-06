<template>
  <div>
    <!-- Page Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
      <div>
        <h1 class="text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">Antivirus</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">ClamAV virus scanning and quarantine management</p>
      </div>
      <button class="btn-secondary text-sm self-start sm:self-auto min-h-[44px] inline-flex items-center gap-1.5" @click="refreshAll">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="23 4 23 10 17 10"/>
          <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
        </svg>
        Refresh
      </button>
    </div>

    <!-- Status Card -->
    <div class="glass rounded-2xl p-5 mb-6">
      <template v-if="av.statusLoading && !av.status">
        <div class="flex items-center gap-4">
          <div class="skeleton w-10 h-10 rounded-xl"></div>
          <div class="flex-1">
            <div class="skeleton h-5 w-40 mb-2"></div>
            <div class="skeleton h-4 w-64"></div>
          </div>
        </div>
      </template>
      <template v-else-if="av.status">
        <div class="flex flex-col sm:flex-row sm:items-center gap-4">
          <!-- Status icon -->
          <div
            class="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0 text-xl"
            :style="{
              background: av.status.daemon_running
                ? 'rgba(34, 197, 94, 0.15)'
                : 'rgba(239, 68, 68, 0.15)',
              color: av.status.daemon_running ? 'var(--success)' : 'var(--error)'
            }"
          >
            &#9737;
          </div>

          <!-- Status details -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1 flex-wrap">
              <h3 class="font-semibold" :style="{ color: 'var(--text-primary)' }">ClamAV</h3>
              <span
                class="badge"
                :class="av.status.daemon_running ? 'badge-success' : 'badge-error'"
              >
                <span
                  class="w-1.5 h-1.5 rounded-full"
                  :style="{ background: av.status.daemon_running ? 'var(--success)' : 'var(--error)' }"
                ></span>
                {{ av.status.daemon_running ? 'Active' : 'Inactive' }}
              </span>
              <span
                v-if="!av.status.installed"
                class="badge badge-warning"
              >Not Installed</span>
            </div>
            <div class="flex flex-wrap gap-x-6 gap-y-1 text-sm" :style="{ color: 'var(--text-muted)' }">
              <span v-if="av.status.database_version">
                DB: <span :style="{ color: 'var(--text-primary)' }">{{ av.status.database_version }}</span>
              </span>
              <span v-if="av.status.database_last_update">
                Updated: <span :style="{ color: 'var(--text-primary)' }">{{ formatDate(av.status.database_last_update) }}</span>
              </span>
              <span>
                Quarantine: <span :style="{ color: 'var(--text-primary)' }">{{ av.status.quarantine_count }} files</span>
              </span>
              <span>
                Freshclam: <span :style="{ color: av.status.freshclam_running ? 'var(--success)' : 'var(--error)' }">
                  {{ av.status.freshclam_running ? 'Running' : 'Stopped' }}
                </span>
              </span>
            </div>
          </div>

          <!-- Action buttons -->
          <div class="flex gap-2 flex-wrap flex-shrink-0">
            <button
              class="btn-primary text-sm min-h-[40px] inline-flex items-center gap-1.5"
              :disabled="scanRunning"
              @click="startFullScan"
            >
              <span v-if="scanRunning" class="spinner"></span>
              <span v-else>&#9881;</span>
              Full Scan
            </button>
            <button
              class="btn-secondary text-sm min-h-[40px] inline-flex items-center gap-1.5"
              :disabled="scanRunning"
              @click="showPathModal = true"
            >
              <span>&#128269;</span>
              Scan Path
            </button>
            <button
              class="btn-secondary text-sm min-h-[40px] inline-flex items-center gap-1.5"
              :disabled="updatingDb"
              @click="updateDb"
            >
              <span v-if="updatingDb" class="spinner"></span>
              <span v-else>&#8635;</span>
              Update DB
            </button>
          </div>
        </div>
      </template>
      <template v-else>
        <div class="flex items-center gap-4 p-4">
          <span class="text-3xl">&#9888;</span>
          <div>
            <h3 class="font-semibold" :style="{ color: 'var(--warning)' }">Unable to fetch ClamAV status</h3>
            <p class="text-sm" :style="{ color: 'var(--text-muted)' }">ClamAV may not be installed or the server may be unreachable.</p>
          </div>
        </div>
      </template>
    </div>

    <!-- Running Scan Progress -->
    <div v-if="runningScan" class="glass rounded-2xl p-5 mb-6">
      <div class="flex items-center gap-3 mb-3">
        <span class="spinner"></span>
        <div class="flex-1">
          <h3 class="font-semibold text-sm" :style="{ color: 'var(--text-primary)' }">Scan in progress</h3>
          <p class="text-xs" :style="{ color: 'var(--text-muted)' }">
            Scanning {{ runningScan.scan_path }} &middot; {{ runningScan.files_scanned }} files scanned
            <span v-if="runningScan.infected_count > 0" :style="{ color: 'var(--error)' }">
              &middot; {{ runningScan.infected_count }} infected
            </span>
          </p>
        </div>
        <span
          class="badge badge-warning"
        >
          <span class="w-1.5 h-1.5 rounded-full animate-pulse" style="background: var(--warning)"></span>
          {{ runningScan.status }}
        </span>
      </div>
      <div class="w-full h-1.5 rounded-full overflow-hidden" :style="{ background: 'rgba(var(--border-rgb), 0.3)' }">
        <div
          class="h-full rounded-full transition-all duration-1000 animate-pulse"
          style="width: 100%; background: var(--primary);"
        ></div>
      </div>
    </div>

    <!-- Tabs -->
    <div class="flex gap-1 mb-6" :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
      <button
        v-for="t in ['Scan History', 'Quarantine']"
        :key="t"
        class="px-4 py-2.5 text-sm font-medium transition-colors border-b-2"
        :style="{
          color: activeTab === t ? 'var(--primary)' : 'var(--text-muted)',
          borderColor: activeTab === t ? 'var(--primary)' : 'transparent'
        }"
        @click="activeTab = t; if (t === 'Quarantine') loadQuarantine()"
      >
        {{ t }}
      </button>
    </div>

    <!-- Scan History Tab -->
    <div v-if="activeTab === 'Scan History'">
      <!-- Loading Skeleton -->
      <div v-if="av.loading" class="glass rounded-2xl overflow-hidden">
        <div v-for="i in 5" :key="i" class="flex items-center gap-4 p-4" :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.15)' }">
          <div class="skeleton h-4 w-32"></div>
          <div class="skeleton h-4 w-40 flex-1"></div>
          <div class="skeleton h-6 w-20"></div>
          <div class="skeleton h-4 w-16"></div>
          <div class="skeleton h-4 w-12"></div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-else-if="av.scans.length === 0" class="glass rounded-2xl p-12 text-center">
        <div class="text-5xl mb-4">&#128270;</div>
        <h3 class="text-lg font-semibold mb-2" :style="{ color: 'var(--text-primary)' }">No Scans Yet</h3>
        <p class="text-sm mb-4" :style="{ color: 'var(--text-muted)' }">Run your first antivirus scan to check for threats.</p>
        <button class="btn-primary" @click="startFullScan">Run Full Scan</button>
      </div>

      <!-- Scans Table -->
      <div v-else class="glass rounded-2xl overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full">
            <thead>
              <tr :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
                <th class="text-left text-xs font-semibold uppercase tracking-wider px-4 py-3" :style="{ color: 'var(--text-muted)' }">Date</th>
                <th class="text-left text-xs font-semibold uppercase tracking-wider px-4 py-3" :style="{ color: 'var(--text-muted)' }">Path</th>
                <th class="text-left text-xs font-semibold uppercase tracking-wider px-4 py-3" :style="{ color: 'var(--text-muted)' }">Status</th>
                <th class="text-right text-xs font-semibold uppercase tracking-wider px-4 py-3" :style="{ color: 'var(--text-muted)' }">Files</th>
                <th class="text-right text-xs font-semibold uppercase tracking-wider px-4 py-3" :style="{ color: 'var(--text-muted)' }">Infected</th>
                <th class="text-right text-xs font-semibold uppercase tracking-wider px-4 py-3" :style="{ color: 'var(--text-muted)' }">Duration</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="scan in av.scans" :key="scan.id">
                <tr
                  class="transition-colors cursor-pointer"
                  :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.15)' }"
                  :class="{ 'hover:bg-[rgba(var(--primary-rgb),0.04)]': true }"
                  @click="toggleScanDetail(scan)"
                >
                  <td class="px-4 py-3 text-sm whitespace-nowrap" :style="{ color: 'var(--text-primary)' }">
                    {{ formatDate(scan.created_at) }}
                  </td>
                  <td class="px-4 py-3 text-sm font-mono" :style="{ color: 'var(--text-muted)' }">
                    {{ scan.scan_path }}
                  </td>
                  <td class="px-4 py-3">
                    <span
                      class="badge"
                      :class="statusBadgeClass(scan.status)"
                    >
                      <span v-if="scan.status === 'running' || scan.status === 'pending'" class="spinner-sm"></span>
                      <span
                        v-else
                        class="w-1.5 h-1.5 rounded-full"
                        :style="{ background: statusColor(scan.status) }"
                      ></span>
                      {{ scan.status }}
                    </span>
                  </td>
                  <td class="px-4 py-3 text-sm text-right" :style="{ color: 'var(--text-primary)' }">
                    {{ scan.files_scanned.toLocaleString() }}
                  </td>
                  <td class="px-4 py-3 text-sm text-right">
                    <span :style="{ color: scan.infected_count > 0 ? 'var(--error)' : 'var(--success)', fontWeight: scan.infected_count > 0 ? '600' : '400' }">
                      {{ scan.infected_count }}
                    </span>
                  </td>
                  <td class="px-4 py-3 text-sm text-right" :style="{ color: 'var(--text-muted)' }">
                    {{ scanDuration(scan) }}
                  </td>
                </tr>
                <!-- Expanded detail row -->
                <tr v-if="expandedScanId === scan.id">
                  <td colspan="6" class="px-4 py-4" :style="{ background: 'rgba(var(--surface-rgb), 0.3)', borderBottom: '1px solid rgba(var(--border-rgb), 0.15)' }">
                    <div v-if="scanDetailLoading" class="flex items-center gap-2 py-2">
                      <span class="spinner-sm"></span>
                      <span class="text-sm" :style="{ color: 'var(--text-muted)' }">Loading scan details...</span>
                    </div>
                    <div v-else-if="scanDetail">
                      <!-- Error message if failed -->
                      <div v-if="scanDetail.scan.error_message" class="mb-3 p-3 rounded-lg" :style="{ background: 'rgba(239, 68, 68, 0.1)' }">
                        <p class="text-sm font-medium" :style="{ color: 'var(--error)' }">Error</p>
                        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">{{ scanDetail.scan.error_message }}</p>
                      </div>

                      <!-- Infected files list -->
                      <div v-if="scanDetail.quarantine_entries && scanDetail.quarantine_entries.length > 0">
                        <p class="text-xs font-semibold uppercase tracking-wider mb-2" :style="{ color: 'var(--text-muted)' }">
                          Infected Files ({{ scanDetail.quarantine_entries.length }})
                        </p>
                        <div class="space-y-1">
                          <div
                            v-for="entry in scanDetail.quarantine_entries"
                            :key="entry.id"
                            class="flex items-center gap-3 p-2.5 rounded-lg"
                            :style="{ background: 'rgba(var(--border-rgb), 0.1)' }"
                          >
                            <span class="text-sm" :style="{ color: 'var(--error)' }">&#9888;</span>
                            <div class="flex-1 min-w-0">
                              <p class="text-sm font-mono truncate" :style="{ color: 'var(--text-primary)' }">
                                {{ entry.original_path }}
                              </p>
                              <p class="text-xs" :style="{ color: 'var(--text-muted)' }">
                                Threat: <span :style="{ color: 'var(--error)' }">{{ entry.threat_name }}</span>
                                <span v-if="entry.file_size"> &middot; {{ formatBytes(entry.file_size) }}</span>
                              </p>
                            </div>
                            <span v-if="entry.restored" class="badge badge-success text-xs">Restored</span>
                            <span v-else-if="entry.deleted" class="badge badge-error text-xs">Deleted</span>
                            <span v-else class="badge badge-warning text-xs">Quarantined</span>
                          </div>
                        </div>
                      </div>
                      <div v-else class="text-sm py-2" :style="{ color: 'var(--text-muted)' }">
                        <span v-if="scanDetail.scan.status === 'completed'">No infected files found. System is clean.</span>
                        <span v-else-if="scanDetail.scan.status === 'running' || scanDetail.scan.status === 'pending'">Scan is still in progress...</span>
                        <span v-else>No quarantine entries for this scan.</span>
                      </div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Quarantine Tab -->
    <div v-if="activeTab === 'Quarantine'">
      <!-- Loading -->
      <div v-if="quarantineLoading" class="glass rounded-2xl overflow-hidden">
        <div v-for="i in 4" :key="i" class="flex items-center gap-4 p-4" :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.15)' }">
          <div class="skeleton h-4 w-40"></div>
          <div class="skeleton h-4 w-56 flex-1"></div>
          <div class="skeleton h-4 w-32"></div>
          <div class="skeleton h-6 w-20"></div>
        </div>
      </div>

      <!-- Empty -->
      <div v-else-if="allQuarantineEntries.length === 0" class="glass rounded-2xl p-12 text-center">
        <div class="text-5xl mb-4">&#9989;</div>
        <h3 class="text-lg font-semibold mb-2" :style="{ color: 'var(--text-primary)' }">Quarantine Empty</h3>
        <p class="text-sm" :style="{ color: 'var(--text-muted)' }">No files are currently quarantined. Your server is clean.</p>
      </div>

      <!-- Quarantine Table -->
      <div v-else class="glass rounded-2xl overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full">
            <thead>
              <tr :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
                <th class="text-left text-xs font-semibold uppercase tracking-wider px-4 py-3" :style="{ color: 'var(--text-muted)' }">File</th>
                <th class="text-left text-xs font-semibold uppercase tracking-wider px-4 py-3" :style="{ color: 'var(--text-muted)' }">Original Path</th>
                <th class="text-left text-xs font-semibold uppercase tracking-wider px-4 py-3" :style="{ color: 'var(--text-muted)' }">Threat</th>
                <th class="text-left text-xs font-semibold uppercase tracking-wider px-4 py-3" :style="{ color: 'var(--text-muted)' }">Date</th>
                <th class="text-right text-xs font-semibold uppercase tracking-wider px-4 py-3" :style="{ color: 'var(--text-muted)' }">Size</th>
                <th class="text-left text-xs font-semibold uppercase tracking-wider px-4 py-3" :style="{ color: 'var(--text-muted)' }">Status</th>
                <th class="text-right text-xs font-semibold uppercase tracking-wider px-4 py-3" :style="{ color: 'var(--text-muted)' }">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="entry in allQuarantineEntries"
                :key="entry.id"
                :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.15)' }"
              >
                <td class="px-4 py-3 text-sm font-medium" :style="{ color: 'var(--text-primary)' }">
                  {{ fileName(entry.original_path) }}
                </td>
                <td class="px-4 py-3 text-sm font-mono max-w-[200px] truncate" :style="{ color: 'var(--text-muted)' }">
                  {{ entry.original_path }}
                </td>
                <td class="px-4 py-3 text-sm" :style="{ color: 'var(--error)' }">
                  {{ entry.threat_name }}
                </td>
                <td class="px-4 py-3 text-sm whitespace-nowrap" :style="{ color: 'var(--text-muted)' }">
                  {{ formatDate(entry.created_at) }}
                </td>
                <td class="px-4 py-3 text-sm text-right" :style="{ color: 'var(--text-muted)' }">
                  {{ entry.file_size ? formatBytes(entry.file_size) : '-' }}
                </td>
                <td class="px-4 py-3">
                  <span v-if="entry.restored" class="badge badge-success">Restored</span>
                  <span v-else-if="entry.deleted" class="badge badge-error">Deleted</span>
                  <span v-else class="badge badge-warning">Quarantined</span>
                </td>
                <td class="px-4 py-3 text-right">
                  <div v-if="!entry.restored && !entry.deleted" class="flex gap-1.5 justify-end">
                    <button
                      class="btn-ghost text-xs px-2.5 py-1.5"
                      @click="confirmAction = { type: 'restore', entry }"
                    >
                      &#8634; Restore
                    </button>
                    <button
                      class="btn-ghost text-xs px-2.5 py-1.5"
                      :style="{ color: 'var(--error)' }"
                      @click="confirmAction = { type: 'delete', entry }"
                    >
                      &#10005; Delete
                    </button>
                  </div>
                  <span v-else class="text-xs" :style="{ color: 'var(--text-muted)' }">--</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Scan Path Modal -->
    <Modal v-model="showPathModal" title="Scan Specific Path" size="md">
      <div class="space-y-4">
        <div>
          <label class="input-label">Path to scan</label>
          <input
            v-model="pathToScan"
            class="w-full"
            placeholder="/home/user/public_html"
            @keydown.enter="startPathScan"
          />
          <p class="text-xs mt-1.5" :style="{ color: 'var(--text-muted)' }">Enter the absolute path of the directory or file to scan.</p>
        </div>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showPathModal = false">Cancel</button>
        <button class="btn-primary" :disabled="!pathToScan.trim()" @click="startPathScan">
          Start Scan
        </button>
      </template>
    </Modal>

    <!-- Confirmation Modal -->
    <Modal v-model="showConfirmModal" :title="confirmTitle" size="sm">
      <p class="text-sm" :style="{ color: 'var(--text-muted)' }">{{ confirmMessage }}</p>
      <div v-if="confirmAction" class="mt-3 p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
        <p class="text-sm font-mono truncate" :style="{ color: 'var(--text-primary)' }">{{ confirmAction.entry.original_path }}</p>
        <p class="text-xs mt-1" :style="{ color: 'var(--text-muted)' }">Threat: {{ confirmAction.entry.threat_name }}</p>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="confirmAction = null">Cancel</button>
        <button
          :class="confirmAction?.type === 'delete' ? 'btn-danger' : 'btn-primary'"
          :disabled="confirmBusy"
          @click="executeConfirm"
        >
          <span v-if="confirmBusy" class="spinner-sm mr-1"></span>
          {{ confirmAction?.type === 'delete' ? 'Delete Permanently' : 'Restore File' }}
        </button>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useAntivirusStore } from '@/stores/antivirus'
import { useNotificationsStore } from '@/stores/notifications'
import Modal from '@/components/Modal.vue'

const av = useAntivirusStore()
const notify = useNotificationsStore()

const activeTab = ref('Scan History')
const showPathModal = ref(false)
const pathToScan = ref('')
const updatingDb = ref(false)
const expandedScanId = ref(null)
const scanDetail = ref(null)
const scanDetailLoading = ref(false)
const quarantineLoading = ref(false)
const allQuarantineEntries = ref([])
const confirmAction = ref(null)
const confirmBusy = ref(false)

let pollInterval = null

// -- Computed --

const scanRunning = computed(() => {
  return av.scans.some(s => s.status === 'running' || s.status === 'pending')
})

const runningScan = computed(() => {
  return av.scans.find(s => s.status === 'running' || s.status === 'pending')
})

const showConfirmModal = computed({
  get: () => confirmAction.value !== null,
  set: (val) => { if (!val) confirmAction.value = null }
})

const confirmTitle = computed(() => {
  if (!confirmAction.value) return ''
  return confirmAction.value.type === 'delete' ? 'Delete File Permanently' : 'Restore File'
})

const confirmMessage = computed(() => {
  if (!confirmAction.value) return ''
  if (confirmAction.value.type === 'delete') {
    return 'This will permanently delete the quarantined file from the server. This action cannot be undone.'
  }
  return 'This will restore the file to its original location. Make sure the file is safe before restoring.'
})

// -- Methods --

function statusBadgeClass(status) {
  switch (status) {
    case 'completed': return 'badge-success'
    case 'failed': return 'badge-error'
    case 'running': case 'pending': return 'badge-warning'
    default: return ''
  }
}

function statusColor(status) {
  switch (status) {
    case 'completed': return 'var(--success)'
    case 'failed': return 'var(--error)'
    case 'running': case 'pending': return 'var(--warning)'
    default: return 'var(--text-muted)'
  }
}

function formatDate(dateStr) {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return parseFloat((bytes / Math.pow(1024, i)).toFixed(1)) + ' ' + sizes[i]
}

function scanDuration(scan) {
  if (!scan.started_at) return '-'
  const start = new Date(scan.started_at)
  const end = scan.completed_at ? new Date(scan.completed_at) : new Date()
  const diff = Math.floor((end - start) / 1000)
  if (diff < 60) return `${diff}s`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ${diff % 60}s`
  return `${Math.floor(diff / 3600)}h ${Math.floor((diff % 3600) / 60)}m`
}

function fileName(path) {
  if (!path) return '-'
  const parts = path.split('/')
  return parts[parts.length - 1] || path
}

async function refreshAll() {
  await Promise.all([
    av.fetchStatus(),
    av.fetchScans()
  ])
}

async function startFullScan() {
  try {
    await av.triggerScan()
    await av.fetchScans()
    startPolling()
  } catch (err) {
    notify.error('Failed to start scan: ' + (err.response?.data?.detail || err.message))
  }
}

async function startPathScan() {
  if (!pathToScan.value.trim()) return
  try {
    await av.triggerPathScan(pathToScan.value.trim())
    showPathModal.value = false
    pathToScan.value = ''
    await av.fetchScans()
    startPolling()
  } catch (err) {
    notify.error('Failed to start scan: ' + (err.response?.data?.detail || err.message))
  }
}

async function updateDb() {
  updatingDb.value = true
  try {
    await av.updateDatabase()
    await av.fetchStatus()
  } catch (err) {
    notify.error('Database update failed: ' + (err.response?.data?.detail || err.message))
  } finally {
    updatingDb.value = false
  }
}

async function toggleScanDetail(scan) {
  if (expandedScanId.value === scan.id) {
    expandedScanId.value = null
    scanDetail.value = null
    return
  }
  expandedScanId.value = scan.id
  scanDetailLoading.value = true
  try {
    scanDetail.value = await av.fetchScanDetail(scan.id)
  } catch {
    scanDetail.value = null
  } finally {
    scanDetailLoading.value = false
  }
}

async function loadQuarantine() {
  quarantineLoading.value = true
  try {
    // Load all scans and aggregate quarantine entries from details
    await av.fetchScans(0, 200)
    const entries = []
    for (const scan of av.scans) {
      if (scan.infected_count > 0) {
        try {
          const detail = await av.fetchScanDetail(scan.id)
          if (detail?.quarantine_entries) {
            entries.push(...detail.quarantine_entries)
          }
        } catch {
          // Skip failed detail fetches
        }
      }
    }
    allQuarantineEntries.value = entries.sort(
      (a, b) => new Date(b.created_at) - new Date(a.created_at)
    )
  } catch {
    allQuarantineEntries.value = []
  } finally {
    quarantineLoading.value = false
  }
}

async function executeConfirm() {
  if (!confirmAction.value) return
  confirmBusy.value = true
  try {
    if (confirmAction.value.type === 'restore') {
      await av.restoreQuarantine(confirmAction.value.entry.id)
      confirmAction.value.entry.restored = true
    } else {
      await av.deleteQuarantine(confirmAction.value.entry.id)
      confirmAction.value.entry.deleted = true
    }
    confirmAction.value = null
  } catch (err) {
    notify.error('Action failed: ' + (err.response?.data?.detail || err.message))
  } finally {
    confirmBusy.value = false
  }
}

// -- Polling for running scans --

function startPolling() {
  if (pollInterval) return
  pollInterval = setInterval(async () => {
    await av.fetchScans()
    if (!scanRunning.value) {
      stopPolling()
      await av.fetchStatus()
    }
  }, 5000)
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
}

// Watch for running scans to auto-start polling
watch(scanRunning, (val) => {
  if (val) startPolling()
  else stopPolling()
})

onMounted(async () => {
  await refreshAll()
  if (scanRunning.value) startPolling()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

.spinner-sm {
  display: inline-block;
  width: 10px;
  height: 10px;
  border: 1.5px solid rgba(var(--border-rgb), 0.4);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.btn-danger {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 1rem;
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 500;
  background: var(--error);
  color: #fff;
  transition: all 0.2s ease;
  min-height: 40px;
}

.btn-danger:hover {
  opacity: 0.9;
}

.btn-danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
