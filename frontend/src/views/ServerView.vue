<template>
  <div class="space-y-6">
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <h1 class="text-2xl font-semibold text-[var(--text-primary)]">Server Management</h1>
      <div class="flex items-center gap-2">
        <button class="btn-secondary text-sm" @click="showTerminal = true">
          &#128421; Terminal
        </button>
        <button class="btn-ghost text-sm" @click="refreshAll">
          &#8635; Refresh
        </button>
      </div>
    </div>

    <!-- Services Grid -->
    <div>
      <h2 class="text-sm font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">Services</h2>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div
          v-for="svc in services"
          :key="svc.name"
          class="glass rounded-2xl p-4"
        >
          <div class="flex items-start justify-between mb-3">
            <div class="flex items-center gap-2.5">
              <span
                class="w-2.5 h-2.5 rounded-full flex-shrink-0"
                :class="svc.status === 'running' ? 'bg-success shadow-[0_0_8px_var(--success)]' : 'bg-error shadow-[0_0_8px_var(--error)]'"
              ></span>
              <div>
                <h3 class="text-sm font-semibold text-[var(--text-primary)]">{{ svc.display_name || svc.name }}</h3>
                <p class="text-xs text-[var(--text-muted)]">{{ svc.status === 'running' ? `Up ${svc.uptime || '--'}` : 'Stopped' }}</p>
              </div>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <button
              class="btn-ghost text-xs px-2 py-1 flex-1"
              :disabled="svc.restarting"
              @click="restartService(svc)"
            >
              <span v-if="svc.restarting" class="inline-block w-3 h-3 border-2 border-current/30 border-t-current rounded-full animate-spin mr-1"></span>
              {{ svc.restarting ? 'Restarting...' : 'Restart' }}
            </button>
            <button
              v-if="svc.status === 'running'"
              class="btn-ghost text-xs px-2 py-1 text-error hover:text-error"
              @click="toggleSvc(svc, 'stop')"
            >
              Stop
            </button>
            <button
              v-else
              class="btn-ghost text-xs px-2 py-1 text-success hover:text-success"
              @click="toggleSvc(svc, 'start')"
            >
              Start
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Server Stats -->
    <div>
      <h2 class="text-sm font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">Server Stats</h2>
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div class="glass rounded-2xl p-5 flex flex-col items-center">
          <GaugeChart :value="stats.cpu || 0" label="CPU" :size="110" />
          <p class="text-xs text-[var(--text-muted)] mt-2">{{ stats.cpu_cores || '--' }} cores</p>
        </div>
        <div class="glass rounded-2xl p-5 flex flex-col items-center">
          <GaugeChart :value="stats.ram || 0" label="RAM" :size="110" />
          <p class="text-xs text-[var(--text-muted)] mt-2">{{ formatBytes(stats.ram_used) }} / {{ formatBytes(stats.ram_total) }}</p>
        </div>
        <div class="glass rounded-2xl p-5 flex flex-col items-center">
          <GaugeChart :value="stats.disk || 0" label="Disk" :size="110" />
          <p class="text-xs text-[var(--text-muted)] mt-2">{{ formatBytes(stats.disk_used) }} / {{ formatBytes(stats.disk_total) }}</p>
        </div>
        <div class="glass rounded-2xl p-5">
          <h3 class="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3 text-center">Network</h3>
          <div class="space-y-3">
            <div>
              <div class="flex justify-between text-xs mb-1">
                <span class="text-[var(--text-muted)]">&#8593; Upload</span>
                <span class="text-[var(--text-primary)] font-mono">{{ stats.net_tx || '0 KB/s' }}</span>
              </div>
              <div class="h-1.5 bg-[var(--border)] rounded-full overflow-hidden">
                <div class="h-full bg-primary rounded-full transition-all duration-500" :style="{ width: Math.min((stats.net_tx_pct || 0), 100) + '%' }"></div>
              </div>
            </div>
            <div>
              <div class="flex justify-between text-xs mb-1">
                <span class="text-[var(--text-muted)]">&#8595; Download</span>
                <span class="text-[var(--text-primary)] font-mono">{{ stats.net_rx || '0 KB/s' }}</span>
              </div>
              <div class="h-1.5 bg-[var(--border)] rounded-full overflow-hidden">
                <div class="h-full bg-success rounded-full transition-all duration-500" :style="{ width: Math.min((stats.net_rx_pct || 0), 100) + '%' }"></div>
              </div>
            </div>
          </div>
          <div class="text-center mt-3">
            <p class="text-xs text-[var(--text-muted)]">Load: <span class="text-[var(--text-primary)] font-mono">{{ stats.load_avg || '--' }}</span></p>
            <p class="text-xs text-[var(--text-muted)]">Uptime: <span class="text-[var(--text-primary)]">{{ stats.uptime || '--' }}</span></p>
          </div>
        </div>
      </div>
    </div>

    <!-- Firewall Section -->
    <div>
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-sm font-semibold text-[var(--text-muted)] uppercase tracking-wider">Firewall Rules</h2>
        <button class="btn-primary text-sm" @click="showFirewallModal = true">
          <span class="text-lg leading-none mr-1">+</span> Add Rule
        </button>
      </div>
      <div class="glass rounded-2xl p-0 overflow-hidden">
        <DataTable
          :columns="firewallColumns"
          :rows="firewallRules"
          :loading="loadingFirewall"
          empty-text="No firewall rules configured."
        >
          <template #cell-action="{ value }">
            <span
              class="badge"
              :class="value === 'allow' ? 'badge-success' : 'badge-error'"
            >
              {{ value }}
            </span>
          </template>

          <template #cell-protocol="{ value }">
            <span class="text-xs font-mono text-[var(--text-muted)] uppercase">{{ value }}</span>
          </template>

          <template #actions="{ row }">
            <button
              class="btn-ghost text-xs px-2 py-1 text-error hover:text-error"
              @click="confirmDeleteRule(row)"
            >
              Delete
            </button>
          </template>
        </DataTable>
      </div>
    </div>

    <!-- Fail2ban Section -->
    <div>
      <h2 class="text-sm font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">Fail2ban Jails</h2>
      <div class="glass rounded-2xl overflow-hidden divide-y divide-[var(--border)]">
        <div v-if="loadingJails" class="p-6">
          <div v-for="i in 3" :key="i" class="flex items-center gap-3 mb-3">
            <div class="skeleton h-5 w-32 rounded"></div>
            <div class="skeleton h-5 w-16 rounded"></div>
          </div>
        </div>
        <div v-else-if="fail2banJails.length === 0" class="p-6 text-center">
          <p class="text-sm text-[var(--text-muted)]">No Fail2ban jails configured.</p>
        </div>
        <div v-for="jail in fail2banJails" :key="jail.name">
          <div
            class="flex items-center justify-between px-6 py-4 cursor-pointer hover:bg-[var(--surface-elevated)] transition-colors"
            @click="toggleJailExpand(jail)"
          >
            <div class="flex items-center gap-3">
              <span class="text-xs w-4">{{ expandedJails.includes(jail.name) ? '&#9660;' : '&#9654;' }}</span>
              <StatusBadge :status="jail.enabled ? 'active' : 'inactive'" :label="jail.enabled ? 'Active' : 'Inactive'" />
              <span class="text-sm font-medium text-[var(--text-primary)]">{{ jail.name }}</span>
            </div>
            <div class="flex items-center gap-6 text-xs text-[var(--text-muted)]">
              <span>Currently banned: <strong class="text-[var(--text-primary)]">{{ jail.current_bans || 0 }}</strong></span>
              <span>Total bans: <strong class="text-[var(--text-primary)]">{{ jail.total_bans || 0 }}</strong></span>
            </div>
          </div>
          <!-- Expanded: banned IPs -->
          <Transition name="expand">
            <div v-if="expandedJails.includes(jail.name)" class="px-6 pb-4 bg-[var(--surface-elevated)]/50">
              <div v-if="!jail.banned_ips?.length" class="text-xs text-[var(--text-muted)] py-2 pl-7">
                No IPs currently banned.
              </div>
              <div v-for="ip in jail.banned_ips" :key="ip" class="flex items-center justify-between py-1.5 pl-7">
                <span class="text-sm font-mono text-[var(--text-primary)]">{{ ip }}</span>
                <button class="btn-ghost text-xs px-2 py-0.5" @click.stop="unbanIp(jail.name, ip)">
                  Unban
                </button>
              </div>
            </div>
          </Transition>
        </div>
      </div>
    </div>

    <!-- Log Viewer -->
    <div>
      <h2 class="text-sm font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">Log Viewer</h2>
      <div class="glass rounded-2xl overflow-hidden">
        <!-- Log Controls -->
        <div class="flex items-center gap-3 px-4 py-3 border-b border-[var(--border)]">
          <select
            v-model="logService"
            class="px-3 py-1.5 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          >
            <option value="nginx">Nginx</option>
            <option value="php-fpm">PHP-FPM</option>
            <option value="postgresql">PostgreSQL</option>
            <option value="redis">Redis</option>
            <option value="exim4">Exim4</option>
            <option value="dovecot">Dovecot</option>
            <option value="fail2ban">Fail2ban</option>
            <option value="syslog">Syslog</option>
          </select>
          <div class="relative flex-1">
            <span class="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] text-xs">&#128269;</span>
            <input
              v-model="logSearch"
              type="text"
              placeholder="Search logs..."
              class="w-full pl-8 pr-4 py-1.5 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
          <button
            class="btn-ghost text-xs px-3 py-1.5"
            :class="logPaused ? 'text-warning' : ''"
            @click="logPaused = !logPaused"
          >
            {{ logPaused ? '&#9654; Resume' : '&#9646;&#9646; Pause' }}
          </button>
        </div>
        <!-- Log Content -->
        <div
          ref="logContainerRef"
          class="h-64 overflow-y-auto p-4 font-mono text-xs leading-5"
          style="background: #0d0d14; color: #a0aec0;"
        >
          <div v-if="loadingLogs" class="space-y-1">
            <div v-for="i in 10" :key="i" class="skeleton h-4 rounded" :style="{ width: (40 + Math.random() * 50) + '%', opacity: 0.3 }"></div>
          </div>
          <template v-else>
            <div
              v-for="(line, idx) in filteredLogLines"
              :key="idx"
              class="whitespace-pre-wrap break-all"
              :class="logLineClass(line)"
            >{{ line }}</div>
            <div v-if="filteredLogLines.length === 0" class="text-center py-8" style="color: #4a5568;">
              No log entries found.
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- Firewall Rule Modal -->
    <Modal v-model="showFirewallModal" title="Add Firewall Rule" size="md">
      <form class="space-y-4" @submit.prevent="addFirewallRule">
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Port</label>
            <input
              v-model="fwForm.port"
              type="text"
              placeholder="80 or 8000-8100"
              class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Protocol</label>
            <select
              v-model="fwForm.protocol"
              class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
            >
              <option value="tcp">TCP</option>
              <option value="udp">UDP</option>
              <option value="tcp/udp">TCP/UDP</option>
            </select>
          </div>
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Action</label>
          <div class="flex gap-4">
            <label class="flex items-center gap-2 text-sm text-[var(--text-primary)]">
              <input type="radio" v-model="fwForm.action" value="allow" /> Allow
            </label>
            <label class="flex items-center gap-2 text-sm text-[var(--text-primary)]">
              <input type="radio" v-model="fwForm.action" value="deny" /> Deny
            </label>
          </div>
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Description</label>
          <input
            v-model="fwForm.description"
            type="text"
            placeholder="HTTP traffic"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
      </form>
      <template #actions>
        <button class="btn-secondary" @click="showFirewallModal = false">Cancel</button>
        <button class="btn-primary" :disabled="!fwForm.port" @click="addFirewallRule">Add Rule</button>
      </template>
    </Modal>

    <!-- Delete Rule Confirm -->
    <ConfirmDialog
      v-model="showDeleteRuleDialog"
      title="Delete Firewall Rule"
      :message="`Delete firewall rule for port ${ruleToDelete?.port || ''} (${ruleToDelete?.protocol || ''})? This takes effect immediately.`"
      confirm-text="Delete Rule"
      :destructive="true"
      @confirm="deleteFirewallRule"
    />

    <!-- Web Terminal Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showTerminal"
          class="fixed inset-0 z-50 flex items-center justify-center p-4"
        >
          <div class="absolute inset-0 bg-black/70 backdrop-blur-sm" @click="closeTerminal" />
          <div class="relative w-full max-w-5xl h-[80vh] flex flex-col rounded-xl overflow-hidden shadow-2xl border border-[var(--border)]" style="background: #0d0d14;">
            <!-- Terminal Header -->
            <div class="flex items-center justify-between px-4 py-2 border-b border-[rgba(255,255,255,0.08)]" style="background: #0a0a12;">
              <div class="flex items-center gap-2">
                <span class="w-3 h-3 rounded-full bg-error"></span>
                <span class="w-3 h-3 rounded-full bg-warning"></span>
                <span class="w-3 h-3 rounded-full bg-success"></span>
                <span class="text-xs ml-2" style="color: rgba(255,255,255,0.4);">root@server ~ </span>
              </div>
              <button
                class="px-2 py-1 text-xs rounded hover:bg-[rgba(255,255,255,0.08)] transition-colors"
                style="color: rgba(255,255,255,0.5);"
                @click="closeTerminal"
              >
                &#10005;
              </button>
            </div>
            <!-- Terminal Body -->
            <div ref="terminalContainerRef" class="flex-1"></div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useServerStore } from '@/stores/server'
import { useNotificationsStore } from '@/stores/notifications'
import client from '@/api/client'
import DataTable from '@/components/DataTable.vue'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import GaugeChart from '@/components/GaugeChart.vue'

const serverStore = useServerStore()
const notifications = useNotificationsStore()

// Services
const services = ref([])
const loadingServices = ref(false)

// Stats
const stats = ref({})
let statsInterval = null

// Firewall
const firewallRules = ref([])
const loadingFirewall = ref(false)
const showFirewallModal = ref(false)
const showDeleteRuleDialog = ref(false)
const ruleToDelete = ref(null)
const fwForm = ref({ port: '', protocol: 'tcp', action: 'allow', description: '' })

const firewallColumns = [
  { key: 'port', label: 'Port' },
  { key: 'protocol', label: 'Protocol' },
  { key: 'action', label: 'Action' },
  { key: 'description', label: 'Description' }
]

// Fail2ban
const fail2banJails = ref([])
const loadingJails = ref(false)
const expandedJails = ref([])

// Logs
const logService = ref('nginx')
const logSearch = ref('')
const logPaused = ref(false)
const logLines = ref([])
const loadingLogs = ref(false)
const logContainerRef = ref(null)
let logInterval = null

// Terminal
const showTerminal = ref(false)
const terminalContainerRef = ref(null)
let term = null
let termSocket = null
let fitAddon = null

const filteredLogLines = computed(() => {
  if (!logSearch.value) return logLines.value
  const q = logSearch.value.toLowerCase()
  return logLines.value.filter(l => l.toLowerCase().includes(q))
})

// Formatting
function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return '--'
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

function logLineClass(line) {
  const lower = line.toLowerCase()
  if (lower.includes('error') || lower.includes('fatal') || lower.includes('crit')) return 'text-error'
  if (lower.includes('warn')) return 'text-warning'
  if (lower.includes('notice') || lower.includes('info')) return ''
  return ''
}

// Services
async function fetchServices() {
  loadingServices.value = true
  try {
    await serverStore.fetchServices()
    services.value = serverStore.services.map(s => ({ ...s, restarting: false }))
  } catch {
    notifications.error('Failed to load services.')
  } finally {
    loadingServices.value = false
  }
}

async function restartService(svc) {
  svc.restarting = true
  try {
    await serverStore.restartService(svc.name)
    notifications.success(`${svc.display_name || svc.name} restarted.`)
    await fetchServices()
  } catch {
    notifications.error(`Failed to restart ${svc.name}.`)
  } finally {
    svc.restarting = false
  }
}

async function toggleSvc(svc, action) {
  try {
    await serverStore.toggleService(svc.name, action)
    notifications.success(`${svc.display_name || svc.name} ${action === 'start' ? 'started' : 'stopped'}.`)
    await fetchServices()
  } catch {
    notifications.error(`Failed to ${action} ${svc.name}.`)
  }
}

// Stats polling
async function fetchStats() {
  try {
    await serverStore.fetchStats()
    stats.value = serverStore.stats || {}
  } catch {
    // silent
  }
}

// Firewall
async function fetchFirewallRules() {
  loadingFirewall.value = true
  try {
    await serverStore.fetchFirewallRules()
    firewallRules.value = serverStore.firewallRules
  } catch {
    notifications.error('Failed to load firewall rules.')
  } finally {
    loadingFirewall.value = false
  }
}

async function addFirewallRule() {
  if (!fwForm.value.port) return
  try {
    await serverStore.addFirewallRule({ ...fwForm.value })
    firewallRules.value = serverStore.firewallRules
    notifications.success('Firewall rule added.')
    showFirewallModal.value = false
    fwForm.value = { port: '', protocol: 'tcp', action: 'allow', description: '' }
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to add rule.')
  }
}

function confirmDeleteRule(rule) {
  ruleToDelete.value = rule
  showDeleteRuleDialog.value = true
}

async function deleteFirewallRule() {
  if (!ruleToDelete.value) return
  try {
    await serverStore.removeFirewallRule(ruleToDelete.value.id)
    firewallRules.value = serverStore.firewallRules
    notifications.success('Firewall rule deleted.')
  } catch {
    notifications.error('Failed to delete rule.')
  } finally {
    ruleToDelete.value = null
  }
}

// Fail2ban
async function fetchJails() {
  loadingJails.value = true
  try {
    await serverStore.fetchFail2ban()
    fail2banJails.value = serverStore.fail2banJails
  } catch {
    notifications.error('Failed to load Fail2ban jails.')
  } finally {
    loadingJails.value = false
  }
}

function toggleJailExpand(jail) {
  const idx = expandedJails.value.indexOf(jail.name)
  if (idx >= 0) {
    expandedJails.value.splice(idx, 1)
  } else {
    expandedJails.value.push(jail.name)
  }
}

async function unbanIp(jailName, ip) {
  try {
    await client.post(`/server/fail2ban/${jailName}/unban`, { ip })
    notifications.success(`Unbanned ${ip} from ${jailName}.`)
    await fetchJails()
  } catch {
    notifications.error(`Failed to unban ${ip}.`)
  }
}

// Logs
async function fetchLogs() {
  if (logPaused.value) return
  loadingLogs.value = logLines.value.length === 0
  try {
    const { data } = await client.get('/server/logs', { params: { service: logService.value, lines: 200 } })
    logLines.value = Array.isArray(data) ? data : (data.lines || data.content?.split('\n') || [])
    nextTick(() => {
      if (logContainerRef.value && !logPaused.value) {
        logContainerRef.value.scrollTop = logContainerRef.value.scrollHeight
      }
    })
  } catch {
    // silent
  } finally {
    loadingLogs.value = false
  }
}

watch(logService, () => {
  logLines.value = []
  fetchLogs()
})

// Terminal
async function initTerminal() {
  await nextTick()
  if (!terminalContainerRef.value) return

  try {
    const { Terminal } = await import('xterm')
    const { FitAddon } = await import('xterm-addon-fit')

    // Import xterm CSS
    const style = document.createElement('style')
    style.textContent = `
      .xterm { padding: 8px; height: 100%; }
      .xterm-viewport { background-color: #0d0d14 !important; }
      .xterm-screen { height: 100%; }
    `
    document.head.appendChild(style)

    term = new Terminal({
      theme: {
        background: '#0d0d14',
        foreground: '#cdd6f4',
        cursor: '#f5e0dc',
        selectionBackground: '#45475a',
        black: '#45475a',
        red: '#f38ba8',
        green: '#a6e3a1',
        yellow: '#f9e2af',
        blue: '#89b4fa',
        magenta: '#cba6f7',
        cyan: '#94e2d5',
        white: '#bac2de',
        brightBlack: '#585b70',
        brightRed: '#f38ba8',
        brightGreen: '#a6e3a1',
        brightYellow: '#f9e2af',
        brightBlue: '#89b4fa',
        brightMagenta: '#cba6f7',
        brightCyan: '#94e2d5',
        brightWhite: '#a6adc8'
      },
      fontFamily: 'JetBrains Mono, Menlo, Consolas, monospace',
      fontSize: 13,
      cursorBlink: true,
      allowProposedApi: true
    })

    fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.open(terminalContainerRef.value)
    fitAddon.fit()

    // WebSocket connection
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const tokens = JSON.parse(localStorage.getItem('hosthive_tokens') || '{}')
    termSocket = new WebSocket(`${wsProtocol}//${window.location.host}/ws/terminal?token=${tokens.access || ''}`)

    termSocket.onopen = () => {
      term.writeln('\r\n\x1b[32mConnected to server terminal.\x1b[0m\r\n')
      const dims = { cols: term.cols, rows: term.rows }
      termSocket.send(JSON.stringify({ type: 'resize', ...dims }))
    }

    termSocket.onmessage = (evt) => {
      term.write(evt.data)
    }

    termSocket.onclose = () => {
      term.writeln('\r\n\x1b[31mConnection closed.\x1b[0m')
    }

    termSocket.onerror = () => {
      term.writeln('\r\n\x1b[31mWebSocket error. Terminal unavailable.\x1b[0m')
    }

    term.onData((data) => {
      if (termSocket?.readyState === WebSocket.OPEN) {
        termSocket.send(data)
      }
    })

    term.onResize(({ cols, rows }) => {
      if (termSocket?.readyState === WebSocket.OPEN) {
        termSocket.send(JSON.stringify({ type: 'resize', cols, rows }))
      }
    })

    // Handle window resize
    const resizeObserver = new ResizeObserver(() => {
      fitAddon?.fit()
    })
    resizeObserver.observe(terminalContainerRef.value)
  } catch (err) {
    console.error('Failed to initialize terminal:', err)
    if (terminalContainerRef.value) {
      terminalContainerRef.value.innerHTML = `
        <div style="padding: 2rem; color: #a0aec0; font-family: monospace; font-size: 13px;">
          <p style="color: #f38ba8;">Terminal initialization failed.</p>
          <p style="margin-top: 0.5rem;">Install xterm.js: npm install xterm xterm-addon-fit</p>
        </div>
      `
    }
  }
}

function closeTerminal() {
  if (termSocket) {
    termSocket.close()
    termSocket = null
  }
  if (term) {
    term.dispose()
    term = null
  }
  fitAddon = null
  showTerminal.value = false
}

watch(showTerminal, (val) => {
  if (val) {
    nextTick(() => initTerminal())
  }
})

function refreshAll() {
  fetchServices()
  fetchStats()
  fetchFirewallRules()
  fetchJails()
  fetchLogs()
}

onMounted(() => {
  fetchServices()
  fetchStats()
  fetchFirewallRules()
  fetchJails()
  fetchLogs()

  // Poll stats every 5 seconds
  statsInterval = setInterval(fetchStats, 5000)
  // Poll logs every 3 seconds
  logInterval = setInterval(fetchLogs, 3000)
})

onUnmounted(() => {
  if (statsInterval) clearInterval(statsInterval)
  if (logInterval) clearInterval(logInterval)
  closeTerminal()
})
</script>

<style scoped>
.expand-enter-active,
.expand-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}
.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
}
.expand-enter-to,
.expand-leave-from {
  max-height: 500px;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.text-error {
  color: var(--error);
}
.text-warning {
  color: var(--warning);
}
</style>
