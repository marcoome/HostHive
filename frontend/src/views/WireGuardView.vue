<template>
  <div>
    <!-- Page Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
      <div>
        <h1 class="text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">WireGuard VPN</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">Manage VPN peers and tunnel configuration</p>
      </div>
      <div class="flex gap-2 self-start sm:self-auto">
        <button class="btn-secondary text-sm min-h-[44px] inline-flex items-center gap-1.5" @click="refreshAll">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="23 4 23 10 17 10"/>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
          </svg>
          Refresh
        </button>
        <button class="btn-primary text-sm min-h-[44px] inline-flex items-center gap-1.5" @click="showAddPeer = true">
          <span>&#10010;</span> Add Peer
        </button>
      </div>
    </div>

    <!-- Interface Status Card -->
    <div class="glass rounded-2xl p-5 mb-6">
      <template v-if="wg.statusLoading">
        <div class="flex items-center gap-6 flex-wrap">
          <div class="skeleton h-5 w-40"></div>
          <div class="skeleton h-5 w-56"></div>
          <div class="skeleton h-5 w-32"></div>
        </div>
      </template>
      <template v-else-if="wg.status">
        <div class="flex flex-col sm:flex-row sm:items-center gap-4 sm:gap-8 flex-wrap">
          <!-- Status Badge -->
          <div class="flex items-center gap-3">
            <div
              class="w-10 h-10 rounded-xl flex items-center justify-center"
              :style="{ background: 'rgba(var(--primary-rgb), 0.12)', color: 'var(--primary)' }"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="2" y="2" width="20" height="8" rx="2" ry="2"/>
                <rect x="2" y="14" width="20" height="8" rx="2" ry="2"/>
                <line x1="6" y1="6" x2="6.01" y2="6"/>
                <line x1="6" y1="18" x2="6.01" y2="18"/>
              </svg>
            </div>
            <div>
              <span class="text-xs block" :style="{ color: 'var(--text-muted)' }">Interface</span>
              <span class="font-semibold text-sm" :style="{ color: 'var(--text-primary)' }">{{ wg.status.interface }}</span>
              <span class="badge badge-success ml-2 text-xs">Active</span>
            </div>
          </div>

          <!-- Listening Port -->
          <div>
            <span class="text-xs block" :style="{ color: 'var(--text-muted)' }">Listening Port</span>
            <span class="font-semibold text-sm" :style="{ color: 'var(--text-primary)' }">{{ wg.status.listening_port }}</span>
          </div>

          <!-- Public Key -->
          <div class="min-w-0 flex-1">
            <span class="text-xs block" :style="{ color: 'var(--text-muted)' }">Public Key</span>
            <div class="flex items-center gap-2">
              <span class="font-mono text-sm truncate" :style="{ color: 'var(--text-primary)' }">{{ wg.status.public_key }}</span>
              <button
                class="btn-ghost text-xs px-1.5 py-0.5 flex-shrink-0"
                @click="copyToClipboard(wg.status.public_key)"
                title="Copy public key"
              >&#9112;</button>
            </div>
          </div>

          <!-- Peer Count -->
          <div class="text-center">
            <span class="text-xs block" :style="{ color: 'var(--text-muted)' }">Peers</span>
            <span class="text-2xl font-bold" :style="{ color: 'var(--primary)' }">{{ wg.status.peer_count }}</span>
          </div>
        </div>
      </template>
      <template v-else>
        <div class="flex items-center gap-4">
          <span class="text-3xl">&#9888;</span>
          <div>
            <h3 class="font-semibold" :style="{ color: 'var(--warning)' }">WireGuard Not Available</h3>
            <p class="text-sm" :style="{ color: 'var(--text-muted)' }">Could not connect to the WireGuard interface. It may not be installed or configured.</p>
          </div>
        </div>
      </template>
    </div>

    <!-- Traffic Stats -->
    <div v-if="wg.peers.length > 0" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <div class="card py-4 px-4">
        <span class="text-xs block mb-1" :style="{ color: 'var(--text-muted)' }">Total Peers</span>
        <span class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">{{ wg.peers.length }}</span>
      </div>
      <div class="card py-4 px-4">
        <span class="text-xs block mb-1" :style="{ color: 'var(--text-muted)' }">Active Peers</span>
        <span class="text-2xl font-bold" :style="{ color: 'var(--success)' }">{{ activePeerCount }}</span>
      </div>
      <div class="card py-4 px-4">
        <span class="text-xs block mb-1" :style="{ color: 'var(--text-muted)' }">Total Download</span>
        <span class="text-2xl font-bold" :style="{ color: 'var(--primary)' }">{{ formatBytes(totalRx) }}</span>
      </div>
      <div class="card py-4 px-4">
        <span class="text-xs block mb-1" :style="{ color: 'var(--text-muted)' }">Total Upload</span>
        <span class="text-2xl font-bold" :style="{ color: 'var(--primary)' }">{{ formatBytes(totalTx) }}</span>
      </div>
    </div>

    <!-- Loading Skeleton for Peers Table -->
    <div v-if="wg.loading" class="glass rounded-2xl overflow-hidden">
      <div class="p-4">
        <div v-for="i in 4" :key="i" class="flex items-center gap-4 py-3" :style="i < 4 ? { borderBottom: '1px solid rgba(var(--border-rgb), 0.15)' } : {}">
          <div class="skeleton h-4 w-32"></div>
          <div class="skeleton h-4 w-48"></div>
          <div class="skeleton h-4 w-24"></div>
          <div class="skeleton h-4 w-20"></div>
          <div class="skeleton h-4 w-16 ml-auto"></div>
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-else-if="wg.peers.length === 0 && wg.status" class="glass rounded-2xl p-12 text-center">
      <div class="text-5xl mb-4">&#128274;</div>
      <h3 class="text-lg font-semibold mb-2" :style="{ color: 'var(--text-primary)' }">No VPN Peers</h3>
      <p class="text-sm mb-4" :style="{ color: 'var(--text-muted)' }">Create your first WireGuard peer to start the VPN tunnel.</p>
      <button class="btn-primary" @click="showAddPeer = true">Add Peer</button>
    </div>

    <!-- Peers Table -->
    <div v-else class="glass rounded-2xl overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
              <th class="text-left px-4 py-3 font-medium" :style="{ color: 'var(--text-muted)' }">Name</th>
              <th class="text-left px-4 py-3 font-medium" :style="{ color: 'var(--text-muted)' }">Public Key</th>
              <th class="text-left px-4 py-3 font-medium hidden md:table-cell" :style="{ color: 'var(--text-muted)' }">Last Handshake</th>
              <th class="text-left px-4 py-3 font-medium hidden lg:table-cell" :style="{ color: 'var(--text-muted)' }">Transfer</th>
              <th class="text-center px-4 py-3 font-medium" :style="{ color: 'var(--text-muted)' }">Status</th>
              <th class="text-right px-4 py-3 font-medium" :style="{ color: 'var(--text-muted)' }">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="peer in wg.peers"
              :key="peer.id"
              class="transition-colors"
              :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.15)' }"
            >
              <!-- Name -->
              <td class="px-4 py-3">
                <span class="font-medium" :style="{ color: 'var(--text-primary)' }">{{ peer.name || 'Unnamed' }}</span>
              </td>

              <!-- Public Key (truncated) -->
              <td class="px-4 py-3">
                <div class="flex items-center gap-1.5">
                  <span class="font-mono text-xs" :style="{ color: 'var(--text-muted)' }">{{ truncateKey(peer.public_key) }}</span>
                  <button
                    class="btn-ghost text-xs px-1 py-0.5"
                    @click="copyToClipboard(peer.public_key)"
                    title="Copy full key"
                  >&#9112;</button>
                </div>
              </td>

              <!-- Last Handshake -->
              <td class="px-4 py-3 hidden md:table-cell">
                <span class="text-xs" :style="{ color: 'var(--text-muted)' }">
                  {{ formatHandshake(peer.latest_handshake) }}
                </span>
              </td>

              <!-- Transfer -->
              <td class="px-4 py-3 hidden lg:table-cell">
                <div class="space-y-1.5">
                  <div class="flex items-center gap-2">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                      <line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>
                    </svg>
                    <span class="text-xs" :style="{ color: 'var(--text-muted)' }">{{ formatBytes(peer.transfer_rx) }}</span>
                  </div>
                  <div class="flex items-center gap-2">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="var(--error)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                      <line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/>
                    </svg>
                    <span class="text-xs" :style="{ color: 'var(--text-muted)' }">{{ formatBytes(peer.transfer_tx) }}</span>
                  </div>
                </div>
              </td>

              <!-- Status -->
              <td class="px-4 py-3 text-center">
                <span
                  class="badge text-xs"
                  :class="isPeerActive(peer) ? 'badge-success' : 'badge-warning'"
                >
                  <span
                    class="w-1.5 h-1.5 rounded-full inline-block"
                    :style="{ background: isPeerActive(peer) ? 'var(--success)' : 'var(--warning)' }"
                  ></span>
                  {{ isPeerActive(peer) ? 'Active' : 'Inactive' }}
                </span>
              </td>

              <!-- Actions -->
              <td class="px-4 py-3 text-right">
                <div class="flex items-center justify-end gap-1">
                  <button
                    class="btn-ghost text-xs px-2 py-1"
                    @click="openConfigModal(peer)"
                    title="Download Config"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                      <polyline points="7 10 12 15 17 10"/>
                      <line x1="12" y1="15" x2="12" y2="3"/>
                    </svg>
                  </button>
                  <button
                    class="btn-ghost text-xs px-2 py-1"
                    @click="openQrModal(peer)"
                    title="Show QR Code"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <rect x="3" y="3" width="7" height="7"/>
                      <rect x="14" y="3" width="7" height="7"/>
                      <rect x="3" y="14" width="7" height="7"/>
                      <rect x="14" y="14" width="7" height="7"/>
                    </svg>
                  </button>
                  <button
                    class="btn-ghost text-xs px-2 py-1"
                    :style="{ color: 'var(--error)' }"
                    @click="confirmRemovePeer(peer)"
                    title="Remove Peer"
                  >&#10005;</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Per-Peer Traffic Stats -->
    <div v-if="wg.peers.length > 0" class="glass rounded-2xl p-5 mt-6">
      <h3 class="text-sm font-medium mb-4" :style="{ color: 'var(--text-primary)' }">Traffic per Peer</h3>
      <div class="space-y-4">
        <div v-for="peer in wg.peers" :key="'traffic-' + peer.id">
          <div class="flex items-center justify-between mb-1.5">
            <span class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">{{ peer.name || 'Unnamed' }}</span>
            <span class="text-xs" :style="{ color: 'var(--text-muted)' }">
              {{ formatBytes(peer.transfer_rx) }} / {{ formatBytes(peer.transfer_tx) }}
            </span>
          </div>
          <!-- RX bar -->
          <div class="flex items-center gap-2 mb-1">
            <span class="text-xs w-6 text-right flex-shrink-0" :style="{ color: 'var(--text-muted)' }">RX</span>
            <div class="flex-1 h-2 rounded-full overflow-hidden" :style="{ background: 'rgba(var(--border-rgb), 0.3)' }">
              <div
                class="h-full rounded-full transition-all duration-700"
                :style="{
                  width: trafficPercent(peer.transfer_rx) + '%',
                  background: 'var(--success)'
                }"
              ></div>
            </div>
            <span class="text-xs w-16 text-right flex-shrink-0" :style="{ color: 'var(--text-muted)' }">{{ formatBytes(peer.transfer_rx) }}</span>
          </div>
          <!-- TX bar -->
          <div class="flex items-center gap-2">
            <span class="text-xs w-6 text-right flex-shrink-0" :style="{ color: 'var(--text-muted)' }">TX</span>
            <div class="flex-1 h-2 rounded-full overflow-hidden" :style="{ background: 'rgba(var(--border-rgb), 0.3)' }">
              <div
                class="h-full rounded-full transition-all duration-700"
                :style="{
                  width: trafficPercent(peer.transfer_tx) + '%',
                  background: 'var(--primary)'
                }"
              ></div>
            </div>
            <span class="text-xs w-16 text-right flex-shrink-0" :style="{ color: 'var(--text-muted)' }">{{ formatBytes(peer.transfer_tx) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Add Peer Modal -->
    <Modal v-model="showAddPeer" title="Add VPN Peer" size="md">
      <div class="space-y-4">
        <div>
          <label class="input-label">Peer Name</label>
          <input
            v-model="peerForm.name"
            class="w-full"
            placeholder="e.g. MacBook, iPhone, Office"
          />
        </div>
        <div>
          <label class="input-label">Allowed IPs</label>
          <input
            v-model="peerForm.allowed_ips"
            class="w-full"
            placeholder="0.0.0.0/0, ::/0"
          />
          <p class="text-xs mt-1" :style="{ color: 'var(--text-muted)' }">
            Default routes all traffic through VPN. Use specific subnets for split tunneling.
          </p>
        </div>
        <div>
          <label class="input-label">DNS Servers</label>
          <input
            v-model="peerForm.dns"
            class="w-full"
            placeholder="1.1.1.1"
          />
          <p class="text-xs mt-1" :style="{ color: 'var(--text-muted)' }">
            Comma-separated DNS servers for the client.
          </p>
        </div>
      </div>

      <template #actions>
        <button class="btn-secondary" @click="showAddPeer = false">Cancel</button>
        <button class="btn-primary" :disabled="!peerForm.name.trim() || addingPeer" @click="handleAddPeer">
          {{ addingPeer ? 'Creating...' : 'Create Peer' }}
        </button>
      </template>
    </Modal>

    <!-- QR Code Modal -->
    <Modal v-model="showQrModal" title="QR Code" size="sm">
      <div class="flex flex-col items-center py-4">
        <p class="text-sm mb-4" :style="{ color: 'var(--text-muted)' }">
          Scan this code with the WireGuard mobile app
        </p>
        <div v-if="qrLoading" class="flex items-center justify-center" style="width: 256px; height: 256px;">
          <div class="skeleton w-full h-full rounded-xl"></div>
        </div>
        <div v-else-if="qrImageUrl" class="rounded-xl overflow-hidden" style="background: white; padding: 12px;">
          <img :src="qrImageUrl" alt="WireGuard QR Code" style="width: 232px; height: 232px; image-rendering: pixelated;" />
        </div>
        <div v-else class="text-sm py-8" :style="{ color: 'var(--text-muted)' }">
          QR code generation failed. Download the config file instead.
        </div>
        <p class="text-sm font-medium mt-4" :style="{ color: 'var(--text-primary)' }">{{ qrPeerName }}</p>
      </div>
    </Modal>

    <!-- Config Modal -->
    <Modal v-model="showConfigModal" title="WireGuard Config" size="lg">
      <div class="space-y-4">
        <p class="text-sm" :style="{ color: 'var(--text-muted)' }">
          Client configuration for <span class="font-semibold" :style="{ color: 'var(--text-primary)' }">{{ configPeerName }}</span>
        </p>
        <div class="relative">
          <pre
            class="rounded-xl p-4 text-sm overflow-auto"
            style="background: rgba(var(--bg-rgb), 0.6); font-family: 'JetBrains Mono', 'Fira Code', monospace; max-height: 400px;"
            :style="{ color: 'var(--text-primary)' }"
          ><code>{{ configText }}</code></pre>
          <button
            class="absolute top-3 right-3 btn-ghost text-xs px-2 py-1"
            @click="copyToClipboard(configText)"
          >
            {{ copied ? 'Copied!' : 'Copy' }}
          </button>
        </div>
      </div>

      <template #actions>
        <button class="btn-secondary" @click="showConfigModal = false">Close</button>
        <button class="btn-primary" @click="downloadConfigFile">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="inline mr-1.5">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          Download .conf
        </button>
      </template>
    </Modal>

    <!-- Remove Confirmation Modal -->
    <Modal v-model="showRemoveModal" title="Remove Peer" size="sm">
      <div class="py-2">
        <p class="text-sm" :style="{ color: 'var(--text-primary)' }">
          Are you sure you want to remove <span class="font-semibold">{{ removePeerName }}</span>?
        </p>
        <p class="text-sm mt-2" :style="{ color: 'var(--text-muted)' }">
          This will revoke VPN access for this peer immediately. This action cannot be undone.
        </p>
      </div>

      <template #actions>
        <button class="btn-secondary" @click="showRemoveModal = false">Cancel</button>
        <button
          class="btn-primary"
          :style="{ background: 'var(--error)' }"
          :disabled="removingPeer"
          @click="handleRemovePeer"
        >
          {{ removingPeer ? 'Removing...' : 'Remove Peer' }}
        </button>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useWireguardStore } from '@/stores/wireguard'
import { useNotificationsStore } from '@/stores/notifications'
import Modal from '@/components/Modal.vue'

const wg = useWireguardStore()
const notify = useNotificationsStore()

// Add Peer
const showAddPeer = ref(false)
const addingPeer = ref(false)
const peerForm = ref({
  name: '',
  allowed_ips: '0.0.0.0/0, ::/0',
  dns: '1.1.1.1'
})

// QR Modal
const showQrModal = ref(false)
const qrLoading = ref(false)
const qrImageUrl = ref('')
const qrPeerName = ref('')

// Config Modal
const showConfigModal = ref(false)
const configText = ref('')
const configPeerName = ref('')
const configPeerId = ref('')
const copied = ref(false)

// Remove Modal
const showRemoveModal = ref(false)
const removePeerName = ref('')
const removePeerId = ref('')
const removingPeer = ref(false)

// Computed
const totalRx = computed(() => wg.peers.reduce((sum, p) => sum + (p.transfer_rx || 0), 0))
const totalTx = computed(() => wg.peers.reduce((sum, p) => sum + (p.transfer_tx || 0), 0))
const maxTransfer = computed(() => {
  const allTransfers = wg.peers.flatMap(p => [p.transfer_rx || 0, p.transfer_tx || 0])
  return Math.max(...allTransfers, 1)
})
const activePeerCount = computed(() => wg.peers.filter(p => isPeerActive(p)).length)

// Helpers
function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return parseFloat((bytes / Math.pow(1024, i)).toFixed(1)) + ' ' + sizes[i]
}

function truncateKey(key) {
  if (!key) return ''
  if (key.length <= 16) return key
  return key.substring(0, 8) + '...' + key.substring(key.length - 8)
}

function formatHandshake(ts) {
  if (!ts || ts === '0' || ts === 0) return 'Never'
  const epoch = Number(ts)
  if (isNaN(epoch) || epoch === 0) return ts
  const date = new Date(epoch * 1000)
  const now = new Date()
  const diffMs = now - date
  const diffSec = Math.floor(diffMs / 1000)
  if (diffSec < 60) return `${diffSec}s ago`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`
  return date.toLocaleString()
}

function isPeerActive(peer) {
  if (!peer.latest_handshake || peer.latest_handshake === '0') return false
  const epoch = Number(peer.latest_handshake)
  if (isNaN(epoch) || epoch === 0) return false
  const now = Math.floor(Date.now() / 1000)
  // Consider active if handshake within last 3 minutes
  return (now - epoch) < 180
}

function trafficPercent(value) {
  if (!value || maxTransfer.value === 0) return 0
  return Math.min(100, Math.round((value / maxTransfer.value) * 100))
}

let copiedTimeout = null
async function copyToClipboard(text) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    if (copiedTimeout) clearTimeout(copiedTimeout)
    copiedTimeout = setTimeout(() => { copied.value = false }, 2000)
    notify.success('Copied to clipboard')
  } catch {
    notify.error('Failed to copy')
  }
}

// Actions
async function refreshAll() {
  try {
    await Promise.all([wg.fetchStatus(), wg.fetchPeers()])
  } catch {
    // Errors handled in store
  }
}

async function handleAddPeer() {
  addingPeer.value = true
  try {
    const result = await wg.addPeer({
      name: peerForm.value.name.trim(),
      allowed_ips: peerForm.value.allowed_ips,
      dns: peerForm.value.dns
    })
    showAddPeer.value = false
    peerForm.value = { name: '', allowed_ips: '0.0.0.0/0, ::/0', dns: '1.1.1.1' }

    // If config was returned, show it immediately
    if (result?.client_config) {
      configText.value = result.client_config
      configPeerName.value = result.peer?.name || peerForm.value.name
      configPeerId.value = result.peer?.id || ''
      showConfigModal.value = true
    }

    // Refresh status to update peer count
    await wg.fetchStatus()
  } catch (err) {
    notify.error(err.response?.data?.detail || 'Failed to create peer')
  } finally {
    addingPeer.value = false
  }
}

async function openQrModal(peer) {
  qrPeerName.value = peer.name || 'Unnamed'
  qrImageUrl.value = ''
  qrLoading.value = true
  showQrModal.value = true
  try {
    const url = await wg.getQrCode(peer.id)
    qrImageUrl.value = url
  } catch {
    qrImageUrl.value = ''
  } finally {
    qrLoading.value = false
  }
}

async function openConfigModal(peer) {
  configPeerName.value = peer.name || 'Unnamed'
  configPeerId.value = peer.id
  configText.value = ''
  showConfigModal.value = true
  try {
    const text = await wg.downloadConfig(peer.id)
    configText.value = text || 'No configuration available.'
  } catch {
    configText.value = 'Failed to load configuration.'
  }
}

function downloadConfigFile() {
  if (!configText.value) return
  const blob = new Blob([configText.value], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `wg-peer-${configPeerId.value || 'config'}.conf`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function confirmRemovePeer(peer) {
  removePeerName.value = peer.name || 'Unnamed'
  removePeerId.value = peer.id
  showRemoveModal.value = true
}

async function handleRemovePeer() {
  removingPeer.value = true
  try {
    await wg.removePeer(removePeerId.value)
    showRemoveModal.value = false
    await wg.fetchStatus()
  } catch (err) {
    notify.error(err.response?.data?.detail || 'Failed to remove peer')
  } finally {
    removingPeer.value = false
  }
}

// Cleanup QR blob URLs on unmount
onUnmounted(() => {
  if (qrImageUrl.value && qrImageUrl.value.startsWith('blob:')) {
    URL.revokeObjectURL(qrImageUrl.value)
  }
  if (copiedTimeout) clearTimeout(copiedTimeout)
})

onMounted(refreshAll)
</script>

<style scoped>
table th {
  white-space: nowrap;
}
</style>
