<template>
  <div class="space-y-6">
    <!-- Page Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">IP Manager</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">Manage server IP addresses, blacklist, and whitelist</p>
      </div>
      <button class="btn-secondary text-sm self-start sm:self-auto min-h-[44px] inline-flex items-center gap-1.5" @click="refreshAll">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="23 4 23 10 17 10"/>
          <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
        </svg>
        Refresh
      </button>
    </div>

    <!-- Summary Cards -->
    <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
      <div class="card flex items-center gap-4 py-4 px-5">
        <div
          class="w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0"
          :style="{ background: 'rgba(var(--primary-rgb), 0.12)', color: 'var(--primary)' }"
        >
          <span class="text-lg">&#127760;</span>
        </div>
        <div>
          <p class="text-xs" :style="{ color: 'var(--text-muted)' }">Total IPs</p>
          <p class="text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">
            {{ store.loading ? '...' : store.addresses.length }}
          </p>
        </div>
      </div>
      <div class="card flex items-center gap-4 py-4 px-5">
        <div
          class="w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0"
          style="background: rgba(239, 68, 68, 0.12); color: #ef4444;"
        >
          <span class="text-lg">&#128683;</span>
        </div>
        <div>
          <p class="text-xs" :style="{ color: 'var(--text-muted)' }">Blacklisted</p>
          <p class="text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">
            {{ store.blacklistLoading ? '...' : store.blacklist.length }}
          </p>
        </div>
      </div>
      <div class="card flex items-center gap-4 py-4 px-5">
        <div
          class="w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0"
          style="background: rgba(34, 197, 94, 0.12); color: #22c55e;"
        >
          <span class="text-lg">&#9989;</span>
        </div>
        <div>
          <p class="text-xs" :style="{ color: 'var(--text-muted)' }">Whitelisted</p>
          <p class="text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">
            {{ store.whitelistLoading ? '...' : store.whitelist.length }}
          </p>
        </div>
      </div>
    </div>

    <!-- Search + Filters -->
    <div class="glass rounded-2xl p-4 sm:p-6">
      <div class="flex flex-col sm:flex-row gap-3 items-stretch sm:items-center">
        <!-- Search -->
        <div class="relative flex-1">
          <span class="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]">&#128269;</span>
          <input
            v-model="search"
            type="text"
            placeholder="Search IP addresses..."
            class="w-full pl-10 pr-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
          />
        </div>
        <!-- IPv4/IPv6 Toggle -->
        <div class="flex items-center gap-1 p-1 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.3)' }">
          <button
            class="px-3 py-1.5 rounded-md text-xs font-medium transition-all min-h-[36px]"
            :class="ipFilter === 'all' ? 'bg-[var(--primary)] text-white shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'"
            @click="ipFilter = 'all'"
          >
            All
          </button>
          <button
            class="px-3 py-1.5 rounded-md text-xs font-medium transition-all min-h-[36px]"
            :class="ipFilter === 'ipv4' ? 'bg-[var(--primary)] text-white shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'"
            @click="ipFilter = 'ipv4'"
          >
            IPv4
          </button>
          <button
            class="px-3 py-1.5 rounded-md text-xs font-medium transition-all min-h-[36px]"
            :class="ipFilter === 'ipv6' ? 'bg-[var(--primary)] text-white shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'"
            @click="ipFilter = 'ipv6'"
          >
            IPv6
          </button>
        </div>
      </div>
    </div>

    <!-- Tabs -->
    <div class="flex items-center gap-1 p-1 rounded-xl" :style="{ background: 'rgba(var(--border-rgb), 0.2)' }">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="flex-1 sm:flex-none px-4 py-2.5 rounded-lg text-sm font-medium transition-all min-h-[44px]"
        :class="activeTab === tab.id
          ? 'bg-[var(--primary)] text-white shadow-sm'
          : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[rgba(var(--surface-rgb),0.5)]'"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
        <span
          class="ml-1.5 px-1.5 py-0.5 rounded-full text-[10px] font-semibold"
          :class="activeTab === tab.id
            ? 'bg-white/20 text-white'
            : 'bg-[rgba(var(--border-rgb),0.4)] text-[var(--text-muted)]'"
        >
          {{ tab.count }}
        </span>
      </button>
    </div>

    <!-- Server IPs Tab -->
    <div v-if="activeTab === 'ips'">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-medium" :style="{ color: 'var(--text-primary)' }">Server IP Addresses</h2>
        <button class="btn-primary inline-flex items-center gap-2 text-sm" @click="showAddIP = true">
          <span class="text-lg leading-none">+</span>
          Add IP
        </button>
      </div>

      <div class="glass rounded-2xl p-0 overflow-hidden">
        <DataTable
          :columns="ipColumns"
          :rows="filteredAddresses"
          :loading="store.loading"
          empty-text="No IP addresses found."
        >
          <template #cell-address="{ row }">
            <span class="font-mono text-sm font-medium" :style="{ color: 'var(--text-primary)' }">
              {{ row.address }}
            </span>
          </template>
          <template #cell-prefix_len="{ row }">
            <span class="font-mono text-sm" :style="{ color: 'var(--text-muted)' }">/{{ row.prefix_len }}</span>
          </template>
          <template #cell-interface="{ row }">
            <span class="badge badge-info">{{ row.interface }}</span>
          </template>
          <template #cell-label="{ row }">
            <span class="text-sm" :style="{ color: 'var(--text-muted)' }">{{ row.label || '-' }}</span>
          </template>
          <template #cell-family="{ row }">
            <span
              class="badge"
              :class="row.family === 'inet6' ? 'badge-warning' : 'badge-success'"
            >
              {{ row.family === 'inet6' ? 'IPv6' : 'IPv4' }}
            </span>
          </template>
          <template #cell-scope="{ row }">
            <span class="text-xs" :style="{ color: 'var(--text-muted)' }">{{ row.scope || '-' }}</span>
          </template>
          <template #actions="{ row }">
            <button
              class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] text-error hover:text-error"
              :disabled="actionLoading"
              @click="confirmRemoveIP(row)"
            >
              Remove
            </button>
          </template>
        </DataTable>
      </div>
    </div>

    <!-- Blacklist Tab -->
    <div v-if="activeTab === 'blacklist'">
      <div class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-4">
        <h2 class="text-lg font-medium" :style="{ color: 'var(--text-primary)' }">Blocked IP Addresses</h2>
        <div class="flex items-center gap-2">
          <button class="btn-secondary inline-flex items-center gap-2 text-sm" @click="showBulkBlacklist = true">
            &#8682; Bulk Import
          </button>
          <button class="btn-primary inline-flex items-center gap-2 text-sm" @click="showAddBlacklist = true">
            <span class="text-lg leading-none">+</span>
            Block IP
          </button>
        </div>
      </div>

      <div class="glass rounded-2xl p-0 overflow-hidden">
        <DataTable
          :columns="blacklistColumns"
          :rows="filteredBlacklist"
          :loading="store.blacklistLoading"
          empty-text="No blocked IPs found."
        >
          <template #cell-ip="{ row }">
            <span class="font-mono text-sm font-medium" :style="{ color: 'var(--text-primary)' }">
              {{ row.ip }}
            </span>
          </template>
          <template #cell-target="{ row }">
            <span class="text-sm" :style="{ color: 'var(--text-muted)' }">{{ row.target || 'Anywhere' }}</span>
          </template>
          <template #cell-direction="{ row }">
            <span class="badge badge-error">{{ (row.direction || 'in').toUpperCase() }}</span>
          </template>
          <template #cell-source="{ row }">
            <span
              class="badge"
              :class="row.source === 'iptables' ? 'badge-warning' : 'badge-info'"
            >
              {{ row.source || 'ufw' }}
            </span>
          </template>
          <template #actions="{ row }">
            <button
              class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] text-success hover:text-success"
              :disabled="actionLoading"
              @click="confirmUnblock(row)"
            >
              Unblock
            </button>
          </template>
        </DataTable>
      </div>
    </div>

    <!-- Whitelist Tab -->
    <div v-if="activeTab === 'whitelist'">
      <div class="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-4">
        <h2 class="text-lg font-medium" :style="{ color: 'var(--text-primary)' }">Whitelisted IP Addresses</h2>
        <div class="flex items-center gap-2">
          <button class="btn-secondary inline-flex items-center gap-2 text-sm" @click="showBulkWhitelist = true">
            &#8682; Bulk Import
          </button>
          <button class="btn-primary inline-flex items-center gap-2 text-sm" @click="showAddWhitelist = true">
            <span class="text-lg leading-none">+</span>
            Whitelist IP
          </button>
        </div>
      </div>

      <div class="glass rounded-2xl p-0 overflow-hidden">
        <DataTable
          :columns="whitelistColumns"
          :rows="filteredWhitelist"
          :loading="store.whitelistLoading"
          empty-text="No whitelisted IPs found."
        >
          <template #cell-ip="{ row }">
            <span class="font-mono text-sm font-medium" :style="{ color: 'var(--text-primary)' }">
              {{ row.ip }}
            </span>
          </template>
          <template #cell-target="{ row }">
            <span class="text-sm" :style="{ color: 'var(--text-muted)' }">{{ row.target || 'Anywhere' }}</span>
          </template>
          <template #cell-direction="{ row }">
            <span class="badge badge-success">{{ (row.direction || 'in').toUpperCase() }}</span>
          </template>
          <template #actions="{ row }">
            <button
              class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] text-error hover:text-error"
              :disabled="actionLoading"
              @click="confirmRemoveWhitelist(row)"
            >
              Remove
            </button>
          </template>
        </DataTable>
      </div>
    </div>

    <!-- Add IP Modal -->
    <Modal v-model="showAddIP" title="Add IP Address" size="md">
      <form class="space-y-4" @submit.prevent="handleAddIP">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">IP Address</label>
          <input
            v-model="addIpForm.ip"
            type="text"
            placeholder="192.168.1.100/24"
            required
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
          <p class="mt-1 text-xs text-[var(--text-muted)]">Include CIDR notation (e.g. /24 for IPv4, /64 for IPv6)</p>
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Interface</label>
          <select
            v-model="addIpForm.interface"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          >
            <option v-for="iface in availableInterfaces" :key="iface" :value="iface">{{ iface }}</option>
          </select>
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Label (optional)</label>
          <input
            v-model="addIpForm.label"
            type="text"
            placeholder="web-server, mail, etc."
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
      </form>
      <template #actions>
        <button class="btn-secondary" @click="showAddIP = false">Cancel</button>
        <button class="btn-primary" :disabled="actionLoading || !addIpForm.ip" @click="handleAddIP">
          {{ actionLoading ? 'Adding...' : 'Add IP Address' }}
        </button>
      </template>
    </Modal>

    <!-- Block IP Modal -->
    <Modal v-model="showAddBlacklist" title="Block IP Address" size="md">
      <form class="space-y-4" @submit.prevent="handleBlockIP">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">IP Address</label>
          <input
            v-model="blockForm.ip"
            type="text"
            placeholder="203.0.113.50"
            required
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Reason (optional)</label>
          <input
            v-model="blockForm.comment"
            type="text"
            placeholder="Suspicious activity, brute force, etc."
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
      </form>
      <template #actions>
        <button class="btn-secondary" @click="showAddBlacklist = false">Cancel</button>
        <button class="btn-danger" :disabled="actionLoading || !blockForm.ip" @click="handleBlockIP">
          {{ actionLoading ? 'Blocking...' : 'Block IP' }}
        </button>
      </template>
    </Modal>

    <!-- Whitelist IP Modal -->
    <Modal v-model="showAddWhitelist" title="Whitelist IP Address" size="md">
      <form class="space-y-4" @submit.prevent="handleWhitelistIP">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">IP Address</label>
          <input
            v-model="whitelistForm.ip"
            type="text"
            placeholder="203.0.113.50"
            required
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Reason (optional)</label>
          <input
            v-model="whitelistForm.comment"
            type="text"
            placeholder="Trusted partner, monitoring service, etc."
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
      </form>
      <template #actions>
        <button class="btn-secondary" @click="showAddWhitelist = false">Cancel</button>
        <button class="btn-primary" :disabled="actionLoading || !whitelistForm.ip" @click="handleWhitelistIP">
          {{ actionLoading ? 'Whitelisting...' : 'Whitelist IP' }}
        </button>
      </template>
    </Modal>

    <!-- Bulk Blacklist Import Modal -->
    <Modal v-model="showBulkBlacklist" title="Bulk Import - Blacklist" size="lg">
      <div class="space-y-4">
        <p class="text-sm" :style="{ color: 'var(--text-muted)' }">
          Enter one IP address per line. Optionally add a comment after a comma.
        </p>
        <textarea
          v-model="bulkBlacklistText"
          rows="10"
          placeholder="203.0.113.50, Brute force&#10;198.51.100.0/24, Spam network&#10;192.0.2.1"
          class="w-full px-4 py-3 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 font-mono"
        />
        <p class="text-xs" :style="{ color: 'var(--text-muted)' }">
          {{ parseBulkLines(bulkBlacklistText).length }} IP(s) detected
        </p>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showBulkBlacklist = false">Cancel</button>
        <button
          class="btn-danger"
          :disabled="actionLoading || parseBulkLines(bulkBlacklistText).length === 0"
          @click="handleBulkBlacklist"
        >
          {{ actionLoading ? 'Importing...' : 'Block All' }}
        </button>
      </template>
    </Modal>

    <!-- Bulk Whitelist Import Modal -->
    <Modal v-model="showBulkWhitelist" title="Bulk Import - Whitelist" size="lg">
      <div class="space-y-4">
        <p class="text-sm" :style="{ color: 'var(--text-muted)' }">
          Enter one IP address per line. Optionally add a comment after a comma.
        </p>
        <textarea
          v-model="bulkWhitelistText"
          rows="10"
          placeholder="203.0.113.50, Monitoring service&#10;198.51.100.0/24, Office network&#10;192.0.2.1"
          class="w-full px-4 py-3 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 font-mono"
        />
        <p class="text-xs" :style="{ color: 'var(--text-muted)' }">
          {{ parseBulkLines(bulkWhitelistText).length }} IP(s) detected
        </p>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showBulkWhitelist = false">Cancel</button>
        <button
          class="btn-primary"
          :disabled="actionLoading || parseBulkLines(bulkWhitelistText).length === 0"
          @click="handleBulkWhitelist"
        >
          {{ actionLoading ? 'Importing...' : 'Whitelist All' }}
        </button>
      </template>
    </Modal>

    <!-- Confirm Remove IP Modal -->
    <Modal v-model="showConfirmRemove" title="Confirm Removal" size="sm">
      <p class="text-sm" :style="{ color: 'var(--text-primary)' }">
        Are you sure you want to remove <strong class="font-mono">{{ pendingAction?.ip }}</strong>
        from <strong>{{ pendingAction?.iface || 'the server' }}</strong>?
      </p>
      <p class="text-xs mt-2" :style="{ color: 'var(--text-muted)' }">
        This action will take effect immediately. Non-persistent changes may be restored on reboot.
      </p>
      <template #actions>
        <button class="btn-secondary" @click="showConfirmRemove = false">Cancel</button>
        <button class="btn-danger" :disabled="actionLoading" @click="executePendingAction">
          {{ actionLoading ? 'Removing...' : 'Remove' }}
        </button>
      </template>
    </Modal>

    <!-- Error Toast -->
    <Transition name="slide-down">
      <div
        v-if="errorMessage"
        class="fixed top-4 right-4 z-[100] max-w-sm p-4 rounded-xl shadow-lg"
        style="background: rgba(239, 68, 68, 0.95); color: white;"
      >
        <div class="flex items-start gap-3">
          <span class="text-lg flex-shrink-0">&#9888;</span>
          <div class="flex-1">
            <p class="text-sm font-medium">Error</p>
            <p class="text-xs mt-0.5 opacity-90">{{ errorMessage }}</p>
          </div>
          <button class="text-white/70 hover:text-white" @click="errorMessage = ''">&#10005;</button>
        </div>
      </div>
    </Transition>

    <!-- Success Toast -->
    <Transition name="slide-down">
      <div
        v-if="successMessage"
        class="fixed top-4 right-4 z-[100] max-w-sm p-4 rounded-xl shadow-lg"
        style="background: rgba(34, 197, 94, 0.95); color: white;"
      >
        <div class="flex items-start gap-3">
          <span class="text-lg flex-shrink-0">&#9989;</span>
          <div class="flex-1">
            <p class="text-sm font-medium">Success</p>
            <p class="text-xs mt-0.5 opacity-90">{{ successMessage }}</p>
          </div>
          <button class="text-white/70 hover:text-white" @click="successMessage = ''">&#10005;</button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useIpManagerStore } from '@/stores/ipManager'
import DataTable from '@/components/DataTable.vue'
import Modal from '@/components/Modal.vue'

const store = useIpManagerStore()

// --- State ---
const activeTab = ref('ips')
const search = ref('')
const ipFilter = ref('all')
const actionLoading = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

// Modals
const showAddIP = ref(false)
const showAddBlacklist = ref(false)
const showAddWhitelist = ref(false)
const showBulkBlacklist = ref(false)
const showBulkWhitelist = ref(false)
const showConfirmRemove = ref(false)

// Forms
const addIpForm = ref({ ip: '', interface: 'eth0', label: '' })
const blockForm = ref({ ip: '', comment: '' })
const whitelistForm = ref({ ip: '', comment: '' })
const bulkBlacklistText = ref('')
const bulkWhitelistText = ref('')

// Pending action for confirm modal
const pendingAction = ref(null)

// --- Tabs ---
const tabs = computed(() => [
  { id: 'ips', label: 'Server IPs', count: store.addresses.length },
  { id: 'blacklist', label: 'Blacklist', count: store.blacklist.length },
  { id: 'whitelist', label: 'Whitelist', count: store.whitelist.length }
])

// --- Table Columns ---
const ipColumns = [
  { key: 'address', label: 'IP Address' },
  { key: 'prefix_len', label: 'CIDR' },
  { key: 'interface', label: 'Interface' },
  { key: 'label', label: 'Label' },
  { key: 'family', label: 'Type' },
  { key: 'scope', label: 'Scope' }
]

const blacklistColumns = [
  { key: 'ip', label: 'IP Address' },
  { key: 'target', label: 'Target' },
  { key: 'direction', label: 'Direction' },
  { key: 'source', label: 'Source' }
]

const whitelistColumns = [
  { key: 'ip', label: 'IP Address' },
  { key: 'target', label: 'Target' },
  { key: 'direction', label: 'Direction' }
]

// --- Computed: available interfaces ---
const availableInterfaces = computed(() => {
  const ifaces = new Set(store.addresses.map(a => a.interface).filter(Boolean))
  if (ifaces.size === 0) ifaces.add('eth0')
  return [...ifaces]
})

// --- Filtering ---
function isIPv6(ip) {
  return ip && ip.includes(':')
}

function matchesSearch(ip) {
  if (!search.value) return true
  const q = search.value.toLowerCase()
  return ip.toLowerCase().includes(q)
}

function matchesIpFilter(ip) {
  if (ipFilter.value === 'all') return true
  const v6 = isIPv6(ip)
  return ipFilter.value === 'ipv6' ? v6 : !v6
}

const filteredAddresses = computed(() => {
  return store.addresses.filter(a => {
    const ipStr = a.address || ''
    if (!matchesSearch(ipStr) && !matchesSearch(a.label || '') && !matchesSearch(a.interface || '')) return false
    if (!matchesIpFilter(ipStr)) return false
    return true
  })
})

const filteredBlacklist = computed(() => {
  return store.blacklist.filter(b => {
    const ipStr = b.ip || ''
    if (!matchesSearch(ipStr) && !matchesSearch(b.target || '') && !matchesSearch(b.raw || '')) return false
    if (!matchesIpFilter(ipStr)) return false
    return true
  })
})

const filteredWhitelist = computed(() => {
  return store.whitelist.filter(w => {
    const ipStr = w.ip || ''
    if (!matchesSearch(ipStr) && !matchesSearch(w.target || '') && !matchesSearch(w.raw || '')) return false
    if (!matchesIpFilter(ipStr)) return false
    return true
  })
})

// --- Helpers ---
function showSuccess(msg) {
  successMessage.value = msg
  setTimeout(() => { successMessage.value = '' }, 4000)
}

function showError(err) {
  const msg = err?.response?.data?.detail || err?.message || 'An unexpected error occurred.'
  errorMessage.value = msg
  setTimeout(() => { errorMessage.value = '' }, 6000)
}

function parseBulkLines(text) {
  if (!text) return []
  return text
    .split('\n')
    .map(l => l.trim())
    .filter(l => l.length > 0)
    .map(l => {
      const [ip, ...rest] = l.split(',')
      return { ip: ip.trim(), comment: rest.join(',').trim() || undefined }
    })
    .filter(e => e.ip.length >= 3)
}

function resetAddIpForm() {
  addIpForm.value = { ip: '', interface: 'eth0', label: '' }
}

function resetBlockForm() {
  blockForm.value = { ip: '', comment: '' }
}

function resetWhitelistForm() {
  whitelistForm.value = { ip: '', comment: '' }
}

// --- Actions ---
async function refreshAll() {
  await Promise.all([
    store.fetchIPs(),
    store.fetchBlacklist(),
    store.fetchWhitelist()
  ])
}

async function handleAddIP() {
  actionLoading.value = true
  try {
    await store.addIP({
      ip: addIpForm.value.ip,
      interface: addIpForm.value.interface,
      label: addIpForm.value.label || undefined
    })
    showSuccess(`IP ${addIpForm.value.ip} added successfully.`)
    showAddIP.value = false
    resetAddIpForm()
  } catch (err) {
    showError(err)
  } finally {
    actionLoading.value = false
  }
}

async function handleBlockIP() {
  actionLoading.value = true
  try {
    await store.addToBlacklist({
      ip: blockForm.value.ip,
      comment: blockForm.value.comment || undefined
    })
    showSuccess(`IP ${blockForm.value.ip} has been blocked.`)
    showAddBlacklist.value = false
    resetBlockForm()
  } catch (err) {
    showError(err)
  } finally {
    actionLoading.value = false
  }
}

async function handleWhitelistIP() {
  actionLoading.value = true
  try {
    await store.addToWhitelist({
      ip: whitelistForm.value.ip,
      comment: whitelistForm.value.comment || undefined
    })
    showSuccess(`IP ${whitelistForm.value.ip} has been whitelisted.`)
    showAddWhitelist.value = false
    resetWhitelistForm()
  } catch (err) {
    showError(err)
  } finally {
    actionLoading.value = false
  }
}

async function handleBulkBlacklist() {
  const entries = parseBulkLines(bulkBlacklistText.value)
  if (entries.length === 0) return
  actionLoading.value = true
  let success = 0
  let failed = 0
  for (const entry of entries) {
    try {
      await store.addToBlacklist({ ip: entry.ip, comment: entry.comment })
      success++
    } catch {
      failed++
    }
  }
  actionLoading.value = false
  showBulkBlacklist.value = false
  bulkBlacklistText.value = ''
  showSuccess(`Blocked ${success} IP(s).` + (failed > 0 ? ` ${failed} failed.` : ''))
}

async function handleBulkWhitelist() {
  const entries = parseBulkLines(bulkWhitelistText.value)
  if (entries.length === 0) return
  actionLoading.value = true
  let success = 0
  let failed = 0
  for (const entry of entries) {
    try {
      await store.addToWhitelist({ ip: entry.ip, comment: entry.comment })
      success++
    } catch {
      failed++
    }
  }
  actionLoading.value = false
  showBulkWhitelist.value = false
  bulkWhitelistText.value = ''
  showSuccess(`Whitelisted ${success} IP(s).` + (failed > 0 ? ` ${failed} failed.` : ''))
}

function confirmRemoveIP(row) {
  pendingAction.value = {
    type: 'removeIP',
    ip: `${row.address}/${row.prefix_len}`,
    iface: row.interface
  }
  showConfirmRemove.value = true
}

function confirmUnblock(row) {
  pendingAction.value = {
    type: 'unblock',
    ip: row.ip
  }
  showConfirmRemove.value = true
}

function confirmRemoveWhitelist(row) {
  pendingAction.value = {
    type: 'removeWhitelist',
    ip: row.ip
  }
  showConfirmRemove.value = true
}

async function executePendingAction() {
  if (!pendingAction.value) return
  actionLoading.value = true
  try {
    const { type, ip, iface } = pendingAction.value
    if (type === 'removeIP') {
      await store.removeIP(ip, iface)
      showSuccess(`IP ${ip} removed from ${iface}.`)
    } else if (type === 'unblock') {
      await store.removeFromBlacklist(ip)
      showSuccess(`IP ${ip} has been unblocked.`)
    } else if (type === 'removeWhitelist') {
      await store.removeFromWhitelist(ip)
      showSuccess(`IP ${ip} removed from whitelist.`)
    }
    showConfirmRemove.value = false
    pendingAction.value = null
  } catch (err) {
    showError(err)
  } finally {
    actionLoading.value = false
  }
}

// --- Init ---
onMounted(refreshAll)
</script>

<style scoped>
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.3s ease;
}
.slide-down-enter-from {
  opacity: 0;
  transform: translateY(-12px);
}
.slide-down-leave-to {
  opacity: 0;
  transform: translateY(-12px);
}
</style>
