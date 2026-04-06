<template>
  <div class="space-y-6">
    <!-- Page Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
      <div>
        <h1 class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">Logs Viewer</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">
          Browse, search, and monitor server log files in real-time
        </p>
      </div>
      <div class="flex items-center gap-2 self-start sm:self-auto">
        <button class="btn-secondary text-sm min-h-[44px]" @click="handleRotateLogs" :disabled="rotating">
          &#8635; Rotate Logs
        </button>
        <button class="btn-primary text-sm min-h-[44px]" @click="handleDownload">
          &#8615; Download
        </button>
      </div>
    </div>

    <!-- Controls Bar -->
    <div class="glass rounded-2xl p-6">
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <!-- Service Selector -->
        <div>
          <label class="input-label">Service</label>
          <select v-model="selectedService" class="w-full" @change="handleServiceChange">
            <option value="">Select a log source...</option>
            <optgroup label="Web Server">
              <option v-for="svc in servicesByGroup.web" :key="svc.name" :value="svc.name" :disabled="!svc.exists">
                {{ svc.description }}{{ !svc.exists ? ' (unavailable)' : '' }}
              </option>
            </optgroup>
            <optgroup label="Mail">
              <option v-for="svc in servicesByGroup.mail" :key="svc.name" :value="svc.name" :disabled="!svc.exists">
                {{ svc.description }}{{ !svc.exists ? ' (unavailable)' : '' }}
              </option>
            </optgroup>
            <optgroup label="Security">
              <option v-for="svc in servicesByGroup.security" :key="svc.name" :value="svc.name" :disabled="!svc.exists">
                {{ svc.description }}{{ !svc.exists ? ' (unavailable)' : '' }}
              </option>
            </optgroup>
            <optgroup label="System">
              <option v-for="svc in servicesByGroup.system" :key="svc.name" :value="svc.name" :disabled="!svc.exists">
                {{ svc.description }}{{ !svc.exists ? ' (unavailable)' : '' }}
              </option>
            </optgroup>
            <optgroup label="Panel">
              <option v-for="svc in servicesByGroup.panel" :key="svc.name" :value="svc.name" :disabled="!svc.exists">
                {{ svc.description }}{{ !svc.exists ? ' (unavailable)' : '' }}
              </option>
            </optgroup>
            <optgroup label="Other">
              <option v-for="svc in servicesByGroup.other" :key="svc.name" :value="svc.name" :disabled="!svc.exists">
                {{ svc.description }}{{ !svc.exists ? ' (unavailable)' : '' }}
              </option>
            </optgroup>
          </select>
        </div>

        <!-- Lines Count -->
        <div>
          <label class="input-label">Lines</label>
          <select v-model="lineCount" class="w-full" @change="handleRefresh">
            <option :value="100">100 lines</option>
            <option :value="200">200 lines</option>
            <option :value="500">500 lines</option>
            <option :value="1000">1000 lines</option>
            <option :value="2000">2000 lines</option>
          </select>
        </div>

        <!-- Auto-Refresh -->
        <div>
          <label class="input-label">Auto-Refresh</label>
          <select v-model="autoRefreshSeconds" class="w-full" @change="handleAutoRefreshChange">
            <option :value="0">Off</option>
            <option :value="5">Every 5 seconds</option>
            <option :value="10">Every 10 seconds</option>
            <option :value="30">Every 30 seconds</option>
            <option :value="60">Every 60 seconds</option>
          </select>
        </div>

        <!-- Search / Filter -->
        <div>
          <label class="input-label">
            Search
            <span class="text-xs font-normal" :style="{ color: 'var(--text-muted)' }">(Ctrl+K)</span>
          </label>
          <div class="relative">
            <input
              ref="searchInput"
              type="text"
              v-model="filterText"
              class="w-full pr-8"
              placeholder="Filter logs... (regex supported)"
              @keydown.enter="handleSearch"
            />
            <button
              v-if="filterText"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-xs px-1.5 py-0.5 rounded"
              :style="{ color: 'var(--text-muted)' }"
              @click="handleClearFilter"
              title="Clear filter"
            >
              &#10005;
            </button>
          </div>
        </div>
      </div>

      <!-- Second row: domain filter + info -->
      <div class="mt-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div class="flex items-center gap-3 flex-wrap">
          <!-- Domain filter for nginx logs -->
          <div v-if="isNginxLog" class="flex items-center gap-2">
            <label class="text-xs font-medium" :style="{ color: 'var(--text-muted)' }">Domain:</label>
            <input
              type="text"
              v-model="domainFilter"
              class="text-sm py-1 px-2"
              style="width: 200px;"
              placeholder="e.g. example.com"
              @keydown.enter="handleSearch"
            />
          </div>

          <!-- Active filter indicator -->
          <span v-if="store.searchQuery" class="badge badge-info text-xs">
            Filtered: "{{ store.searchQuery }}"
            <button class="ml-1" @click="handleClearFilter">&#10005;</button>
          </span>

          <!-- Streaming indicator -->
          <span v-if="store.isStreaming" class="flex items-center gap-1.5 text-xs" :style="{ color: 'var(--success)' }">
            <span class="logs-pulse-dot"></span>
            Live ({{ autoRefreshSeconds }}s)
          </span>
        </div>

        <div class="flex items-center gap-3">
          <!-- Scroll controls -->
          <label class="flex items-center gap-1.5 text-xs cursor-pointer" :style="{ color: 'var(--text-muted)' }">
            <input type="checkbox" v-model="autoScroll" class="rounded" />
            Auto-scroll
          </label>

          <span class="text-xs" :style="{ color: 'var(--text-muted)' }">
            {{ displayedLines.length }} lines
            <template v-if="store.totalLines"> / {{ store.totalLines }} total</template>
          </span>

          <button class="btn-ghost text-xs px-2 py-1 min-h-[36px]" @click="handleRefresh" :disabled="store.loading">
            &#8635; Refresh
          </button>
        </div>
      </div>
    </div>

    <!-- Log Display Area -->
    <div class="glass rounded-2xl overflow-hidden logs-container">
      <!-- Loading State -->
      <div v-if="store.loading && !displayedLines.length" class="p-8 text-center">
        <div class="flex flex-col items-center gap-3">
          <div class="logs-spinner"></div>
          <span class="text-sm" :style="{ color: 'var(--text-muted)' }">Loading logs...</span>
        </div>
      </div>

      <!-- Empty State -->
      <div v-else-if="!selectedService" class="p-12 text-center">
        <div class="flex flex-col items-center gap-3">
          <span class="text-4xl opacity-30">&#128196;</span>
          <span class="text-sm" :style="{ color: 'var(--text-muted)' }">
            Select a log source from the dropdown above
          </span>
        </div>
      </div>

      <div v-else-if="displayedLines.length === 0 && !store.loading" class="p-12 text-center">
        <div class="flex flex-col items-center gap-3">
          <span class="text-4xl opacity-30">&#128196;</span>
          <span class="text-sm" :style="{ color: 'var(--text-muted)' }">
            No log entries found{{ filterText ? ' matching your filter' : '' }}
          </span>
        </div>
      </div>

      <!-- Log Lines -->
      <div
        v-else
        ref="logContainer"
        class="logs-output overflow-x-auto overflow-y-auto"
        style="max-height: 70vh; min-height: 300px;"
        @scroll="handleScroll"
      >
        <table class="w-full">
          <tbody>
            <tr
              v-for="(line, idx) in displayedLines"
              :key="idx"
              class="logs-line"
              :class="logLevelClass(line)"
            >
              <td class="logs-line-number select-none" :style="{ color: 'var(--text-muted)' }">
                {{ idx + 1 }}
              </td>
              <td class="logs-line-content">
                <span v-html="highlightLine(line)"></span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Loading overlay when refreshing -->
      <div
        v-if="store.loading && displayedLines.length > 0"
        class="absolute top-2 right-2"
      >
        <span class="text-xs px-2 py-1 rounded-full" :style="{ background: 'rgba(var(--primary-rgb), 0.15)', color: 'var(--primary)' }">
          Refreshing...
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useLogsStore } from '@/stores/logs'
import { useNotificationsStore } from '@/stores/notifications'

const store = useLogsStore()
const notify = useNotificationsStore()

// Refs
const searchInput = ref(null)
const logContainer = ref(null)

// Controls state
const selectedService = ref('')
const lineCount = ref(200)
const autoRefreshSeconds = ref(0)
const filterText = ref('')
const domainFilter = ref('')
const autoScroll = ref(true)
const rotating = ref(false)

// Computed: is the selected log an nginx log?
const isNginxLog = computed(() =>
  selectedService.value === 'nginx-access' || selectedService.value === 'nginx-error'
)

// Computed: group services for the dropdown
const servicesByGroup = computed(() => {
  const svcs = store.availableServices
  const groups = {
    web: [],
    mail: [],
    security: [],
    system: [],
    panel: [],
    other: []
  }

  const groupMap = {
    'nginx-access': 'web',
    'nginx-error': 'web',
    'php-fpm': 'web',
    'exim4': 'mail',
    'dovecot': 'mail',
    'mail': 'mail',
    'auth': 'security',
    'fail2ban': 'security',
    'ufw': 'security',
    'syslog': 'system',
    'kern': 'system',
    'daemon': 'system',
    'dpkg': 'system',
    'apt-history': 'system',
    'hosthive-api': 'panel',
    'hosthive-worker': 'panel',
    'postgresql': 'panel',
    'mysql': 'panel',
    'proftpd': 'other',
    'clamav': 'other'
  }

  for (const svc of svcs) {
    const group = groupMap[svc.name] || 'other'
    groups[group].push(svc)
  }

  return groups
})

// Computed: active filter string combining text + domain
const activeFilter = computed(() => {
  let f = filterText.value.trim()
  if (domainFilter.value.trim() && isNginxLog.value) {
    const domain = domainFilter.value.trim()
    f = f ? `${domain}.*${f}|${f}.*${domain}` : domain
  }
  return f
})

// Computed: displayed lines
const displayedLines = computed(() => {
  return store.lines || []
})

// Service change handler
function handleServiceChange() {
  store.clearState()
  filterText.value = ''
  domainFilter.value = ''
  if (selectedService.value) {
    store.fetchLogs(selectedService.value, lineCount.value, activeFilter.value)
    if (autoRefreshSeconds.value > 0) {
      store.startAutoRefresh(selectedService.value, lineCount.value, activeFilter.value, autoRefreshSeconds.value * 1000)
    }
  }
}

// Refresh handler
function handleRefresh() {
  if (!selectedService.value) return
  store.fetchLogs(selectedService.value, lineCount.value, activeFilter.value)
}

// Search handler
function handleSearch() {
  if (!selectedService.value) return
  store.fetchLogs(selectedService.value, lineCount.value, activeFilter.value)
  // Restart auto-refresh with new filter
  if (autoRefreshSeconds.value > 0) {
    store.startAutoRefresh(selectedService.value, lineCount.value, activeFilter.value, autoRefreshSeconds.value * 1000)
  }
}

// Clear filter
function handleClearFilter() {
  filterText.value = ''
  domainFilter.value = ''
  if (selectedService.value) {
    store.fetchLogs(selectedService.value, lineCount.value, '')
    if (autoRefreshSeconds.value > 0) {
      store.startAutoRefresh(selectedService.value, lineCount.value, '', autoRefreshSeconds.value * 1000)
    }
  }
}

// Auto-refresh change
function handleAutoRefreshChange() {
  if (autoRefreshSeconds.value > 0 && selectedService.value) {
    store.startAutoRefresh(selectedService.value, lineCount.value, activeFilter.value, autoRefreshSeconds.value * 1000)
  } else {
    store.stopAutoRefresh()
  }
}

// Download handler
function handleDownload() {
  if (!displayedLines.value.length) {
    notify.error('No log data to download')
    return
  }
  const content = displayedLines.value.join('\n')
  const blob = new Blob([content], { type: 'text/plain' })
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${selectedService.value || 'logs'}-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.log`
  a.click()
  window.URL.revokeObjectURL(url)
  notify.success('Log file downloaded')
}

// Rotate logs
async function handleRotateLogs() {
  rotating.value = true
  try {
    await store.rotateLogs()
  } finally {
    rotating.value = false
  }
}

// Log level detection for color-coding
function logLevelClass(line) {
  if (!line) return ''
  const lower = line.toLowerCase()
  // Check for error patterns
  if (/\berror\b|\bfatal\b|\bcrit(ical)?\b|\bemerg(ency)?\b|\bpanic\b/.test(lower)) return 'log-error'
  if (/\bwarn(ing)?\b/.test(lower)) return 'log-warn'
  if (/\binfo\b|\bnotice\b/.test(lower)) return 'log-info'
  if (/\bdebug\b|\btrace\b/.test(lower)) return 'log-debug'
  // HTTP status codes in access logs
  if (/\s[45]\d{2}\s/.test(line)) return 'log-error'
  if (/\s3\d{2}\s/.test(line)) return 'log-warn'
  return ''
}

// Highlight search terms in log lines
function highlightLine(line) {
  if (!line) return ''
  // Escape HTML first
  let escaped = line
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // Highlight filter text if active
  if (filterText.value.trim()) {
    try {
      const regex = new RegExp(`(${filterText.value.trim()})`, 'gi')
      escaped = escaped.replace(regex, '<mark class="logs-highlight">$1</mark>')
    } catch {
      // Invalid regex, skip highlighting
    }
  }

  return escaped
}

// Scroll handling
function handleScroll() {
  if (!logContainer.value) return
  const el = logContainer.value
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50
  // If user scrolls up, disable auto-scroll
  if (!atBottom && autoScroll.value) {
    autoScroll.value = false
  }
}

function scrollToBottom() {
  if (!logContainer.value || !autoScroll.value) return
  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
}

// Watch for new lines to auto-scroll
watch(() => store.lines.length, () => {
  if (autoScroll.value) {
    scrollToBottom()
  }
})

// Keyboard shortcut: Ctrl+K to focus search
function handleKeydown(e) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault()
    searchInput.value?.focus()
  }
}

onMounted(() => {
  store.fetchAvailableServices()
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  store.stopAutoRefresh()
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped>
.logs-container {
  position: relative;
}

.logs-output {
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'SF Mono', 'Consolas', 'Monaco', monospace;
  font-size: 0.8125rem;
  line-height: 1.6;
}

.logs-output table {
  border-collapse: collapse;
  width: 100%;
}

.logs-line {
  transition: background-color 0.15s ease;
}

.logs-line:hover {
  background: rgba(var(--primary-rgb), 0.04);
}

.logs-line-number {
  padding: 0 0.75rem;
  text-align: right;
  font-size: 0.6875rem;
  opacity: 0.5;
  user-select: none;
  white-space: nowrap;
  vertical-align: top;
  border-right: 1px solid rgba(var(--border-rgb), 0.15);
  width: 1%;
}

.logs-line-content {
  padding: 0 0.75rem;
  white-space: pre;
  word-break: break-all;
  color: var(--text-primary);
}

/* Log level color-coding */
.log-error .logs-line-content {
  color: var(--error, #ef4444);
}

.log-warn .logs-line-content {
  color: var(--warning, #f59e0b);
}

.log-info .logs-line-content {
  color: var(--info, #3b82f6);
}

.log-debug .logs-line-content {
  color: var(--text-muted);
  opacity: 0.7;
}

/* Error lines get a subtle background */
.log-error {
  background: rgba(239, 68, 68, 0.05);
}

.log-warn {
  background: rgba(245, 158, 11, 0.03);
}

/* Search highlight */
:deep(.logs-highlight) {
  background: rgba(var(--primary-rgb), 0.3);
  color: var(--text-primary);
  border-radius: 2px;
  padding: 0 2px;
}

/* Pulse dot for live streaming indicator */
.logs-pulse-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success, #22c55e);
  animation: logs-pulse 1.5s ease-in-out infinite;
}

@keyframes logs-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.8); }
}

/* Spinner */
.logs-spinner {
  width: 28px;
  height: 28px;
  border: 3px solid rgba(var(--border-rgb), 0.3);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: logs-spin 0.8s linear infinite;
}

@keyframes logs-spin {
  to { transform: rotate(360deg); }
}

/* Responsive: full-width on all screens */
@media (max-width: 640px) {
  .logs-output {
    font-size: 0.75rem;
  }

  .logs-line-number {
    padding: 0 0.375rem;
    font-size: 0.625rem;
  }

  .logs-line-content {
    padding: 0 0.375rem;
  }
}
</style>
