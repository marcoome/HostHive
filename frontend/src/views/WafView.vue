<template>
  <div class="waf-view">
    <!-- Page Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
      <div>
        <h1 class="text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">Web Application Firewall</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">Protect your domains from malicious traffic</p>
      </div>
      <button class="btn-secondary text-sm self-start sm:self-auto min-h-[44px] inline-flex items-center gap-1.5" @click="refreshAll">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="23 4 23 10 17 10"/>
          <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
        </svg>
        Refresh
      </button>
    </div>

    <!-- Domain Selector + WAF Toggle -->
    <div class="card-static p-5 mb-6">
      <div class="flex flex-col sm:flex-row sm:items-center gap-4">
        <div class="flex-1">
          <label class="input-label">Domain</label>
          <select
            v-model="selectedDomain"
            class="w-full"
            @change="onDomainChange"
          >
            <option value="" disabled>Select a domain...</option>
            <option v-for="s in waf.statuses" :key="s.domain" :value="s.domain">
              {{ s.domain }}
            </option>
          </select>
        </div>
        <div v-if="currentStatus" class="flex items-center gap-4">
          <!-- WAF Toggle -->
          <div class="flex items-center gap-3">
            <span class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">WAF</span>
            <button
              class="toggle-switch"
              :class="{ active: currentStatus.enabled }"
              @click="toggleWaf"
              :disabled="toggling"
            >
              <span class="toggle-knob" />
            </button>
            <span
              class="badge"
              :class="currentStatus.enabled ? 'badge-success' : 'badge-error'"
            >
              {{ currentStatus.enabled ? 'Active' : 'Disabled' }}
            </span>
          </div>
          <!-- Mode selector -->
          <div v-if="currentStatus.enabled" class="flex items-center gap-2">
            <span class="text-sm" :style="{ color: 'var(--text-muted)' }">Mode:</span>
            <select
              :value="currentStatus.mode"
              class="text-sm py-1 px-2"
              @change="onModeChange($event.target.value)"
            >
              <option value="detect">Detect (log only)</option>
              <option value="block">Block (reject)</option>
            </select>
          </div>
        </div>
      </div>
    </div>

    <!-- Loading State -->
    <div v-if="waf.loading && waf.statuses.length === 0" class="grid grid-cols-1 gap-4">
      <div v-for="i in 3" :key="i" class="card-static p-5">
        <div class="skeleton h-5 w-40 mb-3"></div>
        <div class="skeleton h-4 w-full mb-2"></div>
        <div class="skeleton h-4 w-3/4"></div>
      </div>
    </div>

    <!-- No Domains State -->
    <div v-else-if="waf.statuses.length === 0 && !waf.loading" class="card-static p-12 text-center">
      <div class="text-5xl mb-4">&#128737;</div>
      <h3 class="text-lg font-semibold mb-2" :style="{ color: 'var(--text-primary)' }">No Domains Configured</h3>
      <p class="text-sm" :style="{ color: 'var(--text-muted)' }">Add domains first to configure WAF protection.</p>
    </div>

    <!-- Tabs -->
    <div v-else>
      <div class="flex gap-1 mb-6 p-1 rounded-xl" :style="{ background: 'rgba(var(--surface-rgb), 0.5)' }">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          class="flex-1 sm:flex-none px-4 py-2.5 rounded-lg text-sm font-medium transition-all min-h-[44px]"
          :class="activeTab === tab.id ? 'tab-active' : 'tab-inactive'"
          @click="activeTab = tab.id"
        >
          {{ tab.label }}
        </button>
      </div>

      <!-- Rules Tab -->
      <div v-if="activeTab === 'rules'">
        <div class="card-static p-5">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-sm font-semibold" :style="{ color: 'var(--text-primary)' }">
              WAF Rules
              <span v-if="currentRules" class="font-normal" :style="{ color: 'var(--text-muted)' }">
                ({{ currentRules.total }} total)
              </span>
            </h3>
            <button v-if="selectedDomain" class="btn-primary text-sm" @click="showAddRule = true">
              <span>&#10010;</span> Add Rule
            </button>
          </div>

          <!-- No domain selected -->
          <div v-if="!selectedDomain" class="py-8 text-center text-sm" :style="{ color: 'var(--text-muted)' }">
            Select a domain above to manage its WAF rules.
          </div>

          <!-- Rules Table -->
          <div v-else-if="currentRules && currentRules.rules.length > 0" class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
                  <th class="text-left py-3 px-3 font-medium" :style="{ color: 'var(--text-muted)' }">ID</th>
                  <th class="text-left py-3 px-3 font-medium" :style="{ color: 'var(--text-muted)' }">Type</th>
                  <th class="text-left py-3 px-3 font-medium" :style="{ color: 'var(--text-muted)' }">Rule</th>
                  <th class="text-right py-3 px-3 font-medium" :style="{ color: 'var(--text-muted)' }">Actions</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="rule in currentRules.rules"
                  :key="rule.id"
                  class="transition-colors"
                  :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.15)' }"
                >
                  <td class="py-3 px-3 font-mono text-xs" :style="{ color: 'var(--text-primary)' }">
                    {{ rule.id }}
                  </td>
                  <td class="py-3 px-3">
                    <span
                      class="badge"
                      :class="rule.type === 'default' ? 'badge-info' : 'badge-warning'"
                    >
                      {{ rule.type }}
                    </span>
                  </td>
                  <td class="py-3 px-3">
                    <code
                      class="text-xs px-2 py-1 rounded break-all"
                      :style="{ background: 'rgba(var(--border-rgb), 0.2)', color: 'var(--text-primary)' }"
                    >{{ rule.rule }}</code>
                  </td>
                  <td class="py-3 px-3 text-right">
                    <button
                      v-if="rule.type === 'custom'"
                      class="btn-danger text-xs py-1 px-2"
                      @click="onDeleteRule(rule.id)"
                      :disabled="deletingRule === rule.id"
                    >
                      {{ deletingRule === rule.id ? 'Deleting...' : 'Delete' }}
                    </button>
                    <span v-else class="text-xs" :style="{ color: 'var(--text-muted)' }">Built-in</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Empty rules -->
          <div v-else-if="selectedDomain" class="py-8 text-center text-sm" :style="{ color: 'var(--text-muted)' }">
            No WAF rules configured for this domain.
          </div>
        </div>
      </div>

      <!-- Blocked Requests Tab -->
      <div v-if="activeTab === 'blocked'">
        <div class="card-static p-5">
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
            <h3 class="text-sm font-semibold" :style="{ color: 'var(--text-primary)' }">Blocked Requests</h3>
            <div class="flex items-center gap-2">
              <input
                v-model="logSearch"
                type="text"
                placeholder="Search logs..."
                class="text-sm py-1.5 px-3 w-48"
              />
              <select v-model="logLines" class="text-sm py-1.5 px-2" @change="onFetchLog">
                <option :value="50">Last 50</option>
                <option :value="100">Last 100</option>
                <option :value="500">Last 500</option>
              </select>
            </div>
          </div>

          <div v-if="!selectedDomain" class="py-8 text-center text-sm" :style="{ color: 'var(--text-muted)' }">
            Select a domain above to view blocked requests.
          </div>

          <div v-else-if="filteredLogEntries.length > 0" class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
                  <th class="text-left py-3 px-3 font-medium" :style="{ color: 'var(--text-muted)' }">#</th>
                  <th class="text-left py-3 px-3 font-medium" :style="{ color: 'var(--text-muted)' }">Log Entry</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(entry, idx) in filteredLogEntries"
                  :key="idx"
                  :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.15)' }"
                >
                  <td class="py-2 px-3 font-mono text-xs align-top" :style="{ color: 'var(--text-muted)' }">
                    {{ idx + 1 }}
                  </td>
                  <td class="py-2 px-3">
                    <code
                      class="text-xs break-all block whitespace-pre-wrap"
                      :style="{ color: 'var(--text-primary)' }"
                    >{{ entry }}</code>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-else-if="selectedDomain" class="py-8 text-center text-sm" :style="{ color: 'var(--text-muted)' }">
            {{ logSearch ? 'No matching log entries found.' : 'No blocked requests logged for this domain.' }}
          </div>
        </div>
      </div>

      <!-- Geo-Blocking Tab -->
      <div v-if="activeTab === 'geo'">
        <!-- Geo Status Card -->
        <div class="card-static p-5 mb-4">
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h3 class="text-sm font-semibold mb-2" :style="{ color: 'var(--text-primary)' }">GeoIP Status</h3>
              <div class="flex flex-wrap gap-3 text-xs">
                <span class="flex items-center gap-1.5">
                  <span
                    class="w-2 h-2 rounded-full"
                    :style="{ background: waf.geoStatus.installed ? 'var(--success)' : 'var(--error)' }"
                  />
                  Module {{ waf.geoStatus.installed ? 'Installed' : 'Not Installed' }}
                </span>
                <span class="flex items-center gap-1.5">
                  <span
                    class="w-2 h-2 rounded-full"
                    :style="{ background: waf.geoStatus.db_exists ? 'var(--success)' : 'var(--error)' }"
                  />
                  Database {{ waf.geoStatus.db_exists ? 'Available' : 'Missing' }}
                </span>
                <span class="flex items-center gap-1.5">
                  <span
                    class="w-2 h-2 rounded-full"
                    :style="{ background: waf.geoStatus.enabled ? 'var(--success)' : 'var(--text-muted)' }"
                  />
                  {{ waf.geoStatus.enabled ? 'Active' : 'Inactive' }}
                </span>
              </div>
              <p v-if="waf.geoStatus.db_last_modified" class="text-xs mt-2" :style="{ color: 'var(--text-muted)' }">
                Database last updated: {{ formatDate(waf.geoStatus.db_last_modified) }}
              </p>
            </div>
            <button
              class="btn-secondary text-sm self-start"
              :disabled="updatingGeoDb || !waf.geoStatus.geoipupdate_installed"
              @click="onUpdateGeoDb"
            >
              {{ updatingGeoDb ? 'Updating...' : 'Update GeoIP DB' }}
            </button>
          </div>
        </div>

        <!-- Mode + Rules -->
        <div class="card-static p-5">
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-5">
            <div class="flex items-center gap-3">
              <h3 class="text-sm font-semibold" :style="{ color: 'var(--text-primary)' }">Geo-Blocking Rules</h3>
              <select
                :value="waf.geoRules.mode"
                class="text-sm py-1 px-2"
                @change="onGeoModeChange($event.target.value)"
              >
                <option value="blacklist">Blacklist (block listed)</option>
                <option value="whitelist">Whitelist (allow listed only)</option>
              </select>
            </div>
            <button class="btn-primary text-sm self-start" @click="showAddGeoRule = true">
              <span>&#10010;</span> Add Country
            </button>
          </div>

          <!-- Geo Rules List -->
          <div v-if="waf.geoRules.rules.length > 0" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            <div
              v-for="rule in waf.geoRules.rules"
              :key="rule.country_code"
              class="flex items-center justify-between p-3 rounded-lg transition-colors"
              :style="{ background: 'rgba(var(--border-rgb), 0.15)' }"
            >
              <div class="flex items-center gap-2.5">
                <span class="text-lg">{{ countryFlag(rule.country_code) }}</span>
                <div>
                  <span class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">
                    {{ rule.country_code }}
                  </span>
                  <span class="text-xs ml-1.5" :style="{ color: 'var(--text-muted)' }">
                    {{ countryName(rule.country_code) }}
                  </span>
                </div>
                <span
                  class="badge text-xs"
                  :class="rule.action === 'block' ? 'badge-error' : 'badge-success'"
                >
                  {{ rule.action }}
                </span>
              </div>
              <button
                class="p-1.5 rounded-lg transition-colors hover:bg-[rgba(239,68,68,0.15)] text-[var(--text-muted)] hover:text-[var(--error)]"
                @click="onDeleteGeoRule(rule.country_code)"
                :disabled="deletingGeoRule === rule.country_code"
                :title="'Remove ' + rule.country_code"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                </svg>
              </button>
            </div>
          </div>

          <div v-else class="py-8 text-center text-sm" :style="{ color: 'var(--text-muted)' }">
            No geo-blocking rules configured. Add a country to get started.
          </div>
        </div>
      </div>

      <!-- Stats Tab -->
      <div v-if="activeTab === 'stats'">
        <!-- Summary Cards -->
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <div class="card flex flex-col items-center py-5">
            <div
              class="w-12 h-12 rounded-xl flex items-center justify-center mb-3"
              :style="{ background: 'rgba(239, 68, 68, 0.12)', color: 'var(--error)' }"
            >
              <span class="text-xl">&#128737;</span>
            </div>
            <p class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">{{ waf.stats.total_blocked }}</p>
            <p class="text-xs" :style="{ color: 'var(--text-muted)' }">Total Blocked</p>
          </div>
          <div class="card flex flex-col items-center py-5">
            <div
              class="w-12 h-12 rounded-xl flex items-center justify-center mb-3"
              :style="{ background: 'rgba(var(--primary-rgb), 0.12)', color: 'var(--primary)' }"
            >
              <span class="text-xl">&#9673;</span>
            </div>
            <p class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">{{ waf.stats.domains_with_waf }}</p>
            <p class="text-xs" :style="{ color: 'var(--text-muted)' }">Protected Domains</p>
          </div>
          <div class="card flex flex-col items-center py-5">
            <div
              class="w-12 h-12 rounded-xl flex items-center justify-center mb-3"
              :style="{ background: 'rgba(245, 158, 11, 0.12)', color: 'var(--warning)' }"
            >
              <span class="text-xl">&#9888;</span>
            </div>
            <p class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">{{ waf.stats.top_attack_types.length }}</p>
            <p class="text-xs" :style="{ color: 'var(--text-muted)' }">Attack Types</p>
          </div>
          <div class="card flex flex-col items-center py-5">
            <div
              class="w-12 h-12 rounded-xl flex items-center justify-center mb-3"
              :style="{ background: 'rgba(34, 197, 94, 0.12)', color: 'var(--success)' }"
            >
              <span class="text-xl">&#127760;</span>
            </div>
            <p class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">{{ waf.geoRules.total }}</p>
            <p class="text-xs" :style="{ color: 'var(--text-muted)' }">Geo Rules</p>
          </div>
        </div>

        <!-- Charts Row -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
          <!-- Attack Types Pie Chart -->
          <div class="card-static p-5">
            <h3 class="text-sm font-medium mb-4" :style="{ color: 'var(--text-primary)' }">Blocked by Category</h3>
            <div v-if="waf.stats.top_attack_types.length > 0" class="relative h-[250px] w-full flex items-center justify-center">
              <Doughnut :data="attackTypeChartData" :options="pieChartOptions" />
            </div>
            <div v-else class="h-[250px] flex items-center justify-center text-sm" :style="{ color: 'var(--text-muted)' }">
              No attack data available
            </div>
          </div>

          <!-- Top Blocked IPs -->
          <div class="card-static p-5">
            <h3 class="text-sm font-medium mb-4" :style="{ color: 'var(--text-primary)' }">Top Blocked IPs</h3>
            <div v-if="waf.stats.top_ips.length > 0" class="space-y-2 max-h-[250px] overflow-y-auto">
              <div
                v-for="(ipEntry, idx) in waf.stats.top_ips"
                :key="idx"
                class="flex items-center gap-3 p-2.5 rounded-lg"
                :style="{ background: 'rgba(var(--border-rgb), 0.15)' }"
              >
                <span
                  class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0"
                  :style="{
                    background: idx < 3 ? 'rgba(239, 68, 68, 0.15)' : 'rgba(var(--border-rgb), 0.3)',
                    color: idx < 3 ? 'var(--error)' : 'var(--text-muted)'
                  }"
                >
                  {{ idx + 1 }}
                </span>
                <span class="text-sm font-mono flex-1" :style="{ color: 'var(--text-primary)' }">
                  {{ ipEntryKey(ipEntry) }}
                </span>
                <span class="text-sm font-semibold" :style="{ color: 'var(--error)' }">
                  {{ ipEntryValue(ipEntry) }}
                </span>
              </div>
            </div>
            <div v-else class="h-[250px] flex items-center justify-center text-sm" :style="{ color: 'var(--text-muted)' }">
              No blocked IP data available
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Add Rule Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showAddRule" class="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div class="fixed inset-0 bg-black/50 backdrop-blur-sm" @click="showAddRule = false" />
          <div class="glass-strong rounded-2xl p-6 w-full max-w-lg relative z-10">
            <h3 class="text-lg font-semibold mb-4" :style="{ color: 'var(--text-primary)' }">Add WAF Rule</h3>
            <p class="text-sm mb-4" :style="{ color: 'var(--text-muted)' }">
              Enter an Nginx WAF rule directive for <strong>{{ selectedDomain }}</strong>.
            </p>
            <div class="mb-4">
              <label class="input-label">Rule Directive</label>
              <textarea
                v-model="newRule"
                rows="4"
                class="w-full font-mono text-sm"
                placeholder='SecRule ARGS "@contains <script>" "id:1001,phase:2,deny,status:403,msg:XSS attempt"'
              />
            </div>
            <div class="flex justify-end gap-2">
              <button class="btn-secondary" @click="showAddRule = false">Cancel</button>
              <button
                class="btn-primary"
                @click="onAddRule"
                :disabled="!newRule.trim() || addingRule"
              >
                {{ addingRule ? 'Adding...' : 'Add Rule' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Add Geo Rule Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showAddGeoRule" class="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div class="fixed inset-0 bg-black/50 backdrop-blur-sm" @click="showAddGeoRule = false" />
          <div class="glass-strong rounded-2xl p-6 w-full max-w-md relative z-10">
            <h3 class="text-lg font-semibold mb-4" :style="{ color: 'var(--text-primary)' }">Add Geo-Blocking Rule</h3>
            <div class="mb-4">
              <label class="input-label">Country Code (ISO 3166-1 alpha-2)</label>
              <input
                v-model="newGeoCountry"
                type="text"
                class="w-full uppercase"
                placeholder="e.g. CN, RU, KP"
                maxlength="2"
              />
            </div>
            <div class="mb-4">
              <label class="input-label">Action</label>
              <select v-model="newGeoAction" class="w-full">
                <option value="block">Block</option>
                <option value="allow">Allow</option>
              </select>
            </div>
            <div class="flex justify-end gap-2">
              <button class="btn-secondary" @click="showAddGeoRule = false">Cancel</button>
              <button
                class="btn-primary"
                @click="onAddGeoRule"
                :disabled="!isValidCountryCode || addingGeoRule"
              >
                {{ addingGeoRule ? 'Adding...' : 'Add Rule' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Doughnut } from 'vue-chartjs'
import {
  Chart as ChartJS,
  ArcElement,
  Tooltip,
  Legend
} from 'chart.js'
import { useWafStore } from '@/stores/waf'
import { useNotificationsStore } from '@/stores/notifications'

ChartJS.register(ArcElement, Tooltip, Legend)

const waf = useWafStore()
const notify = useNotificationsStore()

// --- State ---
const selectedDomain = ref('')
const activeTab = ref('rules')
const toggling = ref(false)
const deletingRule = ref(null)
const deletingGeoRule = ref(null)
const updatingGeoDb = ref(false)

// Add Rule Modal
const showAddRule = ref(false)
const newRule = ref('')
const addingRule = ref(false)

// Add Geo Rule Modal
const showAddGeoRule = ref(false)
const newGeoCountry = ref('')
const newGeoAction = ref('block')
const addingGeoRule = ref(false)

// Log tab
const logSearch = ref('')
const logLines = ref(100)

const tabs = [
  { id: 'rules', label: 'Rules' },
  { id: 'blocked', label: 'Blocked Requests' },
  { id: 'geo', label: 'Geo-Blocking' },
  { id: 'stats', label: 'Stats' }
]

// --- Computed ---

const currentStatus = computed(() => {
  if (!selectedDomain.value) return null
  return waf.statuses.find(s => s.domain === selectedDomain.value) || null
})

const currentRules = computed(() => {
  if (!selectedDomain.value) return null
  return waf.rules[selectedDomain.value] || null
})

const currentLog = computed(() => {
  if (!selectedDomain.value) return null
  return waf.blockedLog[selectedDomain.value] || null
})

const filteredLogEntries = computed(() => {
  const entries = currentLog.value?.entries || []
  if (!logSearch.value.trim()) return entries
  const q = logSearch.value.toLowerCase()
  return entries.filter(e => e.toLowerCase().includes(q))
})

const isValidCountryCode = computed(() => {
  const cc = newGeoCountry.value.trim().toUpperCase()
  return cc.length === 2 && /^[A-Z]{2}$/.test(cc)
})

// Chart data for attack types
const chartColors = [
  'rgba(239, 68, 68, 0.8)',   // red
  'rgba(245, 158, 11, 0.8)',  // amber
  'rgba(99, 102, 241, 0.8)',  // indigo
  'rgba(34, 197, 94, 0.8)',   // green
  'rgba(168, 85, 247, 0.8)',  // purple
  'rgba(14, 165, 233, 0.8)',  // sky
  'rgba(244, 63, 94, 0.8)',   // rose
  'rgba(20, 184, 166, 0.8)'   // teal
]

const attackTypeChartData = computed(() => {
  const types = waf.stats.top_attack_types || []
  const labels = []
  const values = []
  types.forEach(item => {
    const key = Object.keys(item)[0]
    if (key) {
      labels.push(key)
      values.push(item[key])
    }
  })
  return {
    labels,
    datasets: [{
      data: values,
      backgroundColor: chartColors.slice(0, labels.length),
      borderColor: 'rgba(var(--surface-rgb), 0.8)',
      borderWidth: 2
    }]
  }
})

const pieChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      position: 'bottom',
      labels: {
        color: 'var(--text-muted)',
        padding: 12,
        font: { size: 11 },
        usePointStyle: true,
        pointStyleWidth: 8
      }
    },
    tooltip: {
      backgroundColor: 'rgba(17, 17, 24, 0.9)',
      titleColor: '#e2e8f0',
      bodyColor: '#e2e8f0',
      borderColor: 'rgba(30, 30, 46, 0.5)',
      borderWidth: 1,
      padding: 10,
      cornerRadius: 8
    }
  }
}

// --- Helpers ---

function ipEntryKey(entry) {
  return Object.keys(entry)[0] || 'unknown'
}

function ipEntryValue(entry) {
  const key = Object.keys(entry)[0]
  return key ? entry[key] : 0
}

function countryFlag(code) {
  if (!code || code.length !== 2) return ''
  const base = 0x1F1E6
  return String.fromCodePoint(
    base + code.charCodeAt(0) - 65,
    base + code.charCodeAt(1) - 65
  )
}

const COUNTRY_NAMES = {
  AF: 'Afghanistan', AL: 'Albania', DZ: 'Algeria', AD: 'Andorra', AO: 'Angola',
  AR: 'Argentina', AM: 'Armenia', AU: 'Australia', AT: 'Austria', AZ: 'Azerbaijan',
  BH: 'Bahrain', BD: 'Bangladesh', BY: 'Belarus', BE: 'Belgium', BR: 'Brazil',
  BG: 'Bulgaria', CA: 'Canada', CL: 'Chile', CN: 'China', CO: 'Colombia',
  HR: 'Croatia', CU: 'Cuba', CY: 'Cyprus', CZ: 'Czech Republic', DK: 'Denmark',
  EG: 'Egypt', EE: 'Estonia', FI: 'Finland', FR: 'France', GE: 'Georgia',
  DE: 'Germany', GR: 'Greece', HK: 'Hong Kong', HU: 'Hungary', IS: 'Iceland',
  IN: 'India', ID: 'Indonesia', IR: 'Iran', IQ: 'Iraq', IE: 'Ireland',
  IL: 'Israel', IT: 'Italy', JP: 'Japan', JO: 'Jordan', KZ: 'Kazakhstan',
  KE: 'Kenya', KP: 'North Korea', KR: 'South Korea', KW: 'Kuwait', LV: 'Latvia',
  LB: 'Lebanon', LT: 'Lithuania', LU: 'Luxembourg', MY: 'Malaysia', MX: 'Mexico',
  MD: 'Moldova', MN: 'Mongolia', ME: 'Montenegro', MA: 'Morocco', NL: 'Netherlands',
  NZ: 'New Zealand', NG: 'Nigeria', NO: 'Norway', PK: 'Pakistan', PA: 'Panama',
  PE: 'Peru', PH: 'Philippines', PL: 'Poland', PT: 'Portugal', QA: 'Qatar',
  RO: 'Romania', RU: 'Russia', SA: 'Saudi Arabia', RS: 'Serbia', SG: 'Singapore',
  SK: 'Slovakia', SI: 'Slovenia', ZA: 'South Africa', ES: 'Spain', SE: 'Sweden',
  CH: 'Switzerland', SY: 'Syria', TW: 'Taiwan', TH: 'Thailand', TR: 'Turkey',
  UA: 'Ukraine', AE: 'UAE', GB: 'United Kingdom', US: 'United States',
  UY: 'Uruguay', UZ: 'Uzbekistan', VE: 'Venezuela', VN: 'Vietnam', YE: 'Yemen'
}

function countryName(code) {
  return COUNTRY_NAMES[code] || code
}

function formatDate(isoStr) {
  if (!isoStr) return 'Unknown'
  try {
    return new Date(isoStr).toLocaleString()
  } catch {
    return isoStr
  }
}

// --- Actions ---

async function refreshAll() {
  try {
    await Promise.all([
      waf.fetchWafStatus(),
      waf.fetchStats(),
      waf.fetchGeoStatus(),
      waf.fetchGeoRules()
    ])
    if (selectedDomain.value) {
      await Promise.all([
        waf.fetchRules(selectedDomain.value),
        waf.fetchBlockedRequests(selectedDomain.value, logLines.value)
      ])
    }
  } catch (err) {
    notify.error('Failed to refresh WAF data')
  }
}

async function onDomainChange() {
  if (!selectedDomain.value) return
  try {
    await Promise.all([
      waf.fetchRules(selectedDomain.value),
      waf.fetchBlockedRequests(selectedDomain.value, logLines.value)
    ])
  } catch (err) {
    notify.error('Failed to load domain WAF data')
  }
}

async function toggleWaf() {
  if (!selectedDomain.value || !currentStatus.value) return
  toggling.value = true
  try {
    if (currentStatus.value.enabled) {
      await waf.disableWaf(selectedDomain.value)
    } else {
      await waf.enableWaf(selectedDomain.value)
    }
  } catch (err) {
    notify.error(err.response?.data?.detail || 'Failed to toggle WAF')
  } finally {
    toggling.value = false
  }
}

async function onModeChange(mode) {
  if (!selectedDomain.value) return
  try {
    await waf.setWafMode(selectedDomain.value, mode)
  } catch (err) {
    notify.error(err.response?.data?.detail || 'Failed to change WAF mode')
  }
}

async function onAddRule() {
  if (!selectedDomain.value || !newRule.value.trim()) return
  addingRule.value = true
  try {
    await waf.addRule(selectedDomain.value, newRule.value.trim())
    newRule.value = ''
    showAddRule.value = false
  } catch (err) {
    notify.error(err.response?.data?.detail || 'Failed to add rule')
  } finally {
    addingRule.value = false
  }
}

async function onDeleteRule(ruleId) {
  if (!selectedDomain.value) return
  deletingRule.value = ruleId
  try {
    await waf.deleteRule(selectedDomain.value, ruleId)
  } catch (err) {
    notify.error(err.response?.data?.detail || 'Failed to delete rule')
  } finally {
    deletingRule.value = null
  }
}

async function onFetchLog() {
  if (!selectedDomain.value) return
  try {
    await waf.fetchBlockedRequests(selectedDomain.value, logLines.value)
  } catch (err) {
    notify.error('Failed to fetch blocked requests')
  }
}

async function onGeoModeChange(mode) {
  try {
    await waf.setGeoMode(mode)
  } catch (err) {
    notify.error(err.response?.data?.detail || 'Failed to change geo mode')
  }
}

async function onAddGeoRule() {
  if (!isValidCountryCode.value) return
  addingGeoRule.value = true
  try {
    await waf.addGeoRule(newGeoCountry.value.trim(), newGeoAction.value)
    newGeoCountry.value = ''
    newGeoAction.value = 'block'
    showAddGeoRule.value = false
  } catch (err) {
    notify.error(err.response?.data?.detail || 'Failed to add geo rule')
  } finally {
    addingGeoRule.value = false
  }
}

async function onDeleteGeoRule(countryCode) {
  deletingGeoRule.value = countryCode
  try {
    await waf.deleteGeoRule(countryCode)
  } catch (err) {
    notify.error(err.response?.data?.detail || 'Failed to delete geo rule')
  } finally {
    deletingGeoRule.value = null
  }
}

async function onUpdateGeoDb() {
  updatingGeoDb.value = true
  try {
    await waf.updateGeoDb()
  } catch (err) {
    notify.error(err.response?.data?.detail || 'Failed to update GeoIP database')
  } finally {
    updatingGeoDb.value = false
  }
}

// --- Lifecycle ---

onMounted(async () => {
  await Promise.all([
    waf.fetchWafStatus(),
    waf.fetchStats(),
    waf.fetchGeoStatus(),
    waf.fetchGeoRules()
  ])
  // Auto-select first domain if available
  if (waf.statuses.length > 0 && !selectedDomain.value) {
    selectedDomain.value = waf.statuses[0].domain
    await onDomainChange()
  }
})
</script>

<style scoped>
.waf-view {
  position: relative;
  z-index: 1;
}

/* Toggle switch */
.toggle-switch {
  position: relative;
  width: 44px;
  height: 24px;
  border-radius: 9999px;
  background: rgba(var(--border-rgb), 0.5);
  border: none;
  cursor: pointer;
  transition: background 0.3s ease;
  flex-shrink: 0;
}

.toggle-switch.active {
  background: var(--success);
}

.toggle-knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 20px;
  height: 20px;
  border-radius: 9999px;
  background: white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
  transition: transform 0.3s ease;
}

.toggle-switch.active .toggle-knob {
  transform: translateX(20px);
}

/* Tabs */
.tab-active {
  background: rgba(var(--primary-rgb), 0.12);
  color: var(--primary);
  box-shadow: 0 0 12px rgba(var(--primary-rgb), 0.1);
}

.tab-inactive {
  color: var(--text-muted);
}

.tab-inactive:hover {
  color: var(--text-primary);
  background: rgba(var(--border-rgb), 0.2);
}

/* Modal transition */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .glass-strong,
.modal-leave-active .glass-strong {
  transition: transform 0.2s ease, opacity 0.2s ease;
}

.modal-enter-from .glass-strong {
  transform: scale(0.95);
  opacity: 0;
}

.modal-leave-to .glass-strong {
  transform: scale(0.95);
  opacity: 0;
}
</style>
