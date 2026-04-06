<template>
  <div>
    <!-- Back button + Header -->
    <div class="mb-6">
      <button class="btn-ghost text-sm mb-4" @click="$router.push({ name: 'dns' })">
        &#8592; Back to DNS Zones
      </button>

      <!-- Zone header skeleton -->
      <div v-if="dns.loading && !dns.currentZone" class="glass rounded-2xl p-6">
        <LoadingSkeleton class="h-7 w-64 mb-2" />
        <LoadingSkeleton class="h-4 w-96" />
      </div>

      <!-- Zone header -->
      <div v-else-if="dns.currentZone" class="glass rounded-2xl p-6">
        <div class="flex items-center justify-between">
          <div>
            <h1 class="text-2xl font-semibold text-text-primary">{{ dns.currentZone.name }}</h1>
            <div class="flex items-center gap-4 mt-2 text-sm text-text-muted">
              <span>SOA: {{ dns.currentZone.soa_email || 'admin@' + dns.currentZone.name }}</span>
              <span>Serial: {{ dns.currentZone.serial || 'N/A' }}</span>
              <span>Refresh: {{ dns.currentZone.refresh || 3600 }}s</span>
              <span>TTL: {{ dns.currentZone.default_ttl || 3600 }}s</span>
            </div>
          </div>
          <div class="flex items-center gap-3">
            <!-- Cloudflare status indicator -->
            <div v-if="dns.cfStatus.enabled" class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-orange-500/10 border border-orange-500/20">
              <span class="w-2 h-2 rounded-full bg-orange-500 animate-pulse"></span>
              <span class="text-xs font-medium text-orange-400">CF Synced</span>
            </div>
            <!-- Cloudflare actions -->
            <button
              v-if="dns.cfStatus.enabled"
              class="btn-secondary text-sm"
              :disabled="dns.cfLoading"
              @click="syncToCloudflare"
            >
              &#8635; Sync CF
            </button>
            <button
              v-if="dns.cfStatus.enabled"
              class="btn-secondary text-sm"
              :disabled="dns.cfLoading"
              @click="importFromCloudflare"
            >
              &#8615; CF Import
            </button>
            <button
              class="text-sm"
              :class="dns.cfStatus.enabled ? 'btn-ghost text-orange-400 hover:text-orange-300' : 'btn-secondary'"
              @click="dns.cfStatus.enabled ? disableCloudflare() : (showCfConfig = true)"
            >
              {{ dns.cfStatus.enabled ? 'Disable CF' : 'Enable Cloudflare' }}
            </button>
            <button class="btn-secondary text-sm" @click="exportZone">
              &#8682; Export
            </button>
            <button class="btn-secondary text-sm" @click="showImport = true">
              &#8681; Import
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- DNSSEC Section -->
    <div class="glass rounded-2xl p-6 mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-text-primary uppercase tracking-wider">DNSSEC</h2>
        <div class="flex items-center gap-3">
          <!-- Status indicator -->
          <div v-if="dns.dnssecStatus.enabled" class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-green-500/10 border border-green-500/20">
            <span class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
            <span class="text-xs font-medium text-green-400">DNSSEC Active</span>
          </div>
          <div v-else class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-500/10 border border-zinc-500/20">
            <span class="w-2 h-2 rounded-full bg-zinc-500"></span>
            <span class="text-xs font-medium text-zinc-400">DNSSEC Inactive</span>
          </div>

          <!-- Enable / Disable toggle -->
          <button
            v-if="dns.dnssecStatus.enabled"
            class="btn-ghost text-sm text-red-400 hover:text-red-300"
            :disabled="dns.dnssecLoading"
            @click="disableDnssec"
          >
            Disable DNSSEC
          </button>
          <button
            v-else
            class="btn-secondary text-sm"
            :disabled="dns.dnssecLoading"
            @click="showDnssecConfig = true"
          >
            {{ dns.dnssecLoading ? 'Enabling...' : 'Enable DNSSEC' }}
          </button>
        </div>
      </div>

      <!-- DNSSEC details when enabled -->
      <div v-if="dns.dnssecStatus.enabled" class="space-y-3">
        <div class="flex items-center gap-6 text-sm text-text-muted">
          <span>Algorithm: <span class="text-text-primary font-mono">{{ dns.dnssecStatus.algorithm }}</span></span>
        </div>

        <!-- DS Record for registrar -->
        <div v-if="dns.dnssecStatus.ds_record">
          <label class="input-label">DS Record (provide to your domain registrar)</label>
          <div class="flex items-start gap-2 mt-1">
            <code class="flex-1 block bg-background/50 border border-border rounded-lg p-3 text-xs font-mono text-text-primary break-all select-all">{{ dns.dnssecStatus.ds_record }}</code>
            <button
              class="btn-secondary text-xs px-3 py-2 shrink-0"
              @click="copyDsRecord"
              title="Copy DS record"
            >
              Copy
            </button>
          </div>
          <p class="text-xs text-text-muted mt-1">
            Add this DS record at your domain registrar to complete the chain of trust.
          </p>
        </div>
        <div v-else class="text-xs text-text-muted">
          DS record not yet available. It will appear once zone signing completes.
        </div>
      </div>
    </div>

    <!-- DNSSEC Enable Configuration Modal -->
    <Modal v-model="showDnssecConfig" title="Enable DNSSEC" size="md">
      <div class="space-y-4">
        <p class="text-sm text-text-muted">
          Enabling DNSSEC will generate signing keys (KSK + ZSK) and sign the zone.
          After enabling, you will need to add the DS record at your domain registrar.
        </p>
        <div>
          <label class="input-label">Signing Algorithm</label>
          <select v-model="dnssecConfig.algorithm" class="w-full">
            <option value="ECDSAP256SHA256">ECDSAP256SHA256 (recommended)</option>
            <option value="ECDSAP384SHA384">ECDSAP384SHA384</option>
            <option value="RSASHA256">RSASHA256</option>
            <option value="RSASHA512">RSASHA512</option>
          </select>
        </div>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showDnssecConfig = false">Cancel</button>
        <button
          class="btn-primary"
          :disabled="dns.dnssecLoading"
          @click="enableDnssec"
        >
          {{ dns.dnssecLoading ? 'Enabling...' : 'Enable DNSSEC' }}
        </button>
      </template>
    </Modal>

    <!-- Add Record Form -->
    <div class="glass rounded-2xl p-6 mb-6">
      <h2 class="text-sm font-semibold text-text-primary uppercase tracking-wider mb-4">Add Record</h2>
      <form @submit.prevent="addRecord" class="flex items-end gap-3 flex-wrap">
        <div class="w-32">
          <label class="input-label">Type</label>
          <select v-model="newRecord.type" class="w-full">
            <option v-for="t in recordTypes" :key="t" :value="t">{{ t }}</option>
          </select>
        </div>
        <div class="flex-1 min-w-[140px]">
          <label class="input-label">Name</label>
          <input v-model="newRecord.name" type="text" class="w-full" placeholder="@" />
        </div>
        <!-- Standard value field (hidden for CAA which uses its own fields) -->
        <div v-if="newRecord.type !== 'CAA'" class="flex-1 min-w-[200px]">
          <label class="input-label">Value</label>
          <input v-model="newRecord.value" type="text" class="w-full"
            :placeholder="newRecord.type === 'PTR' ? 'Hostname (e.g. mail.example.com)' : 'IP address or hostname'"
            :required="newRecord.type !== 'CAA'" />
        </div>

        <!-- CAA-specific fields -->
        <template v-if="newRecord.type === 'CAA'">
          <div class="w-24">
            <label class="input-label">Flags
              <span class="tooltip-icon" title="0 = non-critical (CA may ignore unknown tags), 128 = critical (CA must understand the tag)">?</span>
            </label>
            <select v-model.number="newRecord.caaFlags" class="w-full">
              <option :value="0">0</option>
              <option :value="128">128</option>
            </select>
          </div>
          <div class="w-32">
            <label class="input-label">Tag
              <span class="tooltip-icon" title="issue = authorize a CA for this domain, issuewild = authorize a CA for wildcard certs, iodef = report policy violations to this URL">?</span>
            </label>
            <select v-model="newRecord.caaTag" class="w-full">
              <option value="issue">issue</option>
              <option value="issuewild">issuewild</option>
              <option value="iodef">iodef</option>
            </select>
          </div>
          <div class="flex-1 min-w-[200px]">
            <label class="input-label">Value
              <span class="tooltip-icon" title="For issue/issuewild: CA domain (e.g. letsencrypt.org). For iodef: reporting URL (e.g. mailto:admin@example.com)">?</span>
            </label>
            <input v-model="newRecord.caaValue" type="text" class="w-full"
              :placeholder="newRecord.caaTag === 'iodef' ? 'mailto:admin@example.com' : 'letsencrypt.org'" required />
          </div>
        </template>

        <!-- PTR tooltip -->
        <div v-if="newRecord.type === 'PTR'" class="text-xs text-text-muted self-end pb-2">
          <span class="tooltip-icon" title="PTR records map IP addresses to hostnames (reverse DNS). The name should be the reverse IP (e.g. 1.0.168.192.in-addr.arpa) and the value is the hostname.">?</span>
        </div>

        <div class="w-24">
          <label class="input-label">TTL</label>
          <input v-model.number="newRecord.ttl" type="number" class="w-full" min="60" />
        </div>
        <div v-if="showPriority(newRecord.type)" class="w-24">
          <label class="input-label">Priority</label>
          <input v-model.number="newRecord.priority" type="number" class="w-full" min="0" />
        </div>
        <button type="submit" class="btn-primary" :disabled="addingRecord">
          {{ addingRecord ? 'Adding...' : '+ Add' }}
        </button>
      </form>
    </div>

    <!-- Records Table -->
    <div class="card-static p-0 overflow-hidden rounded-2xl">
      <div class="px-6 py-4 border-b border-border flex items-center justify-between">
        <h2 class="text-sm font-semibold text-text-primary uppercase tracking-wider">
          DNS Records
          <span class="text-text-muted font-normal normal-case ml-2">
            ({{ dns.records.length }} total)
          </span>
        </h2>
        <div class="flex items-center gap-2">
          <input
            v-model="searchQuery"
            type="text"
            class="text-sm py-1.5 px-3"
            placeholder="Filter records..."
          />
        </div>
      </div>

      <!-- Table -->
      <div class="overflow-x-auto">
        <table class="w-full">
          <thead>
            <tr class="border-b border-border">
              <th class="px-6 py-3 text-left text-xs font-semibold text-text-muted uppercase tracking-wider w-28">Type</th>
              <th class="px-6 py-3 text-left text-xs font-semibold text-text-muted uppercase tracking-wider">Name</th>
              <th class="px-6 py-3 text-left text-xs font-semibold text-text-muted uppercase tracking-wider">Value</th>
              <th class="px-6 py-3 text-left text-xs font-semibold text-text-muted uppercase tracking-wider w-24">TTL</th>
              <th class="px-6 py-3 text-left text-xs font-semibold text-text-muted uppercase tracking-wider w-24">Priority</th>
              <th class="px-6 py-3 text-right text-xs font-semibold text-text-muted uppercase tracking-wider w-40">Actions</th>
            </tr>
          </thead>

          <!-- Loading skeleton -->
          <tbody v-if="dns.loading && dns.records.length === 0">
            <tr v-for="i in 5" :key="i" class="border-b border-border">
              <td class="px-6 py-4"><LoadingSkeleton class="h-4 w-14" /></td>
              <td class="px-6 py-4"><LoadingSkeleton class="h-4 w-24" /></td>
              <td class="px-6 py-4"><LoadingSkeleton class="h-4 w-48" /></td>
              <td class="px-6 py-4"><LoadingSkeleton class="h-4 w-12" /></td>
              <td class="px-6 py-4"><LoadingSkeleton class="h-4 w-10" /></td>
              <td class="px-6 py-4"><LoadingSkeleton class="h-4 w-20 ml-auto" /></td>
            </tr>
          </tbody>

          <!-- Empty state -->
          <tbody v-else-if="filteredRecords.length === 0">
            <tr>
              <td colspan="6" class="px-6 py-12 text-center">
                <div class="text-text-muted">
                  <div class="text-3xl mb-2">&#9744;</div>
                  <p class="text-sm">{{ searchQuery ? 'No matching records found.' : 'No records yet. Add your first record above.' }}</p>
                </div>
              </td>
            </tr>
          </tbody>

          <!-- Records -->
          <tbody v-else>
            <tr
              v-for="record in filteredRecords"
              :key="record.id"
              class="border-b border-border last:border-0 hover:bg-background/50 transition-colors group"
            >
              <!-- Type -->
              <td class="px-6 py-3 text-sm" @click="startEdit(record, 'type')">
                <select
                  v-if="editing?.id === record.id && editing.field === 'type'"
                  v-model="editing.value"
                  class="w-full text-sm py-1"
                  @blur="saveEdit(record)"
                  @change="saveEdit(record)"
                  ref="editInput"
                >
                  <option v-for="t in recordTypes" :key="t" :value="t">{{ t }}</option>
                </select>
                <span v-else class="badge badge-info cursor-pointer">{{ record.type }}</span>
              </td>

              <!-- Name -->
              <td class="px-6 py-3 text-sm" @click="startEdit(record, 'name')">
                <input
                  v-if="editing?.id === record.id && editing.field === 'name'"
                  v-model="editing.value"
                  type="text"
                  class="w-full text-sm py-1"
                  @blur="saveEdit(record)"
                  @keydown.enter="saveEdit(record)"
                  @keydown.escape="cancelEdit"
                />
                <span v-else class="font-mono text-sm cursor-pointer hover:text-primary transition-colors">
                  {{ record.name }}
                </span>
              </td>

              <!-- Value -->
              <td class="px-6 py-3 text-sm" @click="startEdit(record, 'value')">
                <input
                  v-if="editing?.id === record.id && editing.field === 'value'"
                  v-model="editing.value"
                  type="text"
                  class="w-full text-sm py-1"
                  @blur="saveEdit(record)"
                  @keydown.enter="saveEdit(record)"
                  @keydown.escape="cancelEdit"
                />
                <template v-else>
                  <!-- CAA: display parsed flags, tag, value -->
                  <span v-if="record.type === 'CAA'" class="font-mono text-sm cursor-pointer hover:text-primary transition-colors break-all">
                    <span class="badge badge-neutral text-xs mr-1">{{ parseCaa(record.value).flags }}</span>
                    <span class="badge badge-info text-xs mr-1">{{ parseCaa(record.value).tag }}</span>
                    <span>{{ parseCaa(record.value).value }}</span>
                  </span>
                  <span v-else class="font-mono text-sm cursor-pointer hover:text-primary transition-colors break-all">
                    {{ record.value }}
                  </span>
                </template>
              </td>

              <!-- TTL -->
              <td class="px-6 py-3 text-sm" @click="startEdit(record, 'ttl')">
                <input
                  v-if="editing?.id === record.id && editing.field === 'ttl'"
                  v-model.number="editing.value"
                  type="number"
                  min="60"
                  class="w-full text-sm py-1"
                  @blur="saveEdit(record)"
                  @keydown.enter="saveEdit(record)"
                  @keydown.escape="cancelEdit"
                />
                <span v-else class="text-text-muted cursor-pointer hover:text-primary transition-colors">
                  {{ record.ttl }}s
                </span>
              </td>

              <!-- Priority -->
              <td class="px-6 py-3 text-sm">
                <template v-if="showPriority(record.type)">
                  <span
                    @click="startEdit(record, 'priority')"
                    class="cursor-pointer hover:text-primary transition-colors"
                  >
                    <input
                      v-if="editing?.id === record.id && editing.field === 'priority'"
                      v-model.number="editing.value"
                      type="number"
                      min="0"
                      class="w-full text-sm py-1"
                      @blur="saveEdit(record)"
                      @keydown.enter="saveEdit(record)"
                      @keydown.escape="cancelEdit"
                    />
                    <span v-else>{{ record.priority }}</span>
                  </span>
                </template>
                <span v-else class="text-text-muted">-</span>
              </td>

              <!-- Actions -->
              <td class="px-6 py-3 text-right">
                <div class="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <!-- Cloudflare proxy toggle (orange cloud) for A/AAAA records -->
                  <button
                    v-if="dns.cfStatus.enabled && (record.type === 'A' || record.type === 'AAAA')"
                    class="btn-ghost text-xs px-2 py-1"
                    :class="record._cfProxied ? 'text-orange-400' : 'text-text-muted'"
                    :title="record._cfProxied ? 'CF Proxy ON - click to disable' : 'CF Proxy OFF - click to enable'"
                    @click="toggleCfProxy(record)"
                  >
                    &#9729;
                  </button>
                  <button
                    class="btn-ghost text-xs px-2 py-1"
                    @click="saveRecordRow(record)"
                    title="Save"
                  >
                    &#10003; Save
                  </button>
                  <button
                    class="btn-ghost text-xs px-2 py-1 text-error hover:text-error"
                    @click="confirmDeleteRecord(record)"
                    title="Delete"
                  >
                    &#10005;
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Import Modal -->
    <Modal v-model="showImport" title="Import Zone Records" size="lg">
      <div class="space-y-4">
        <div>
          <label class="input-label">Zone File Contents</label>
          <textarea
            v-model="importContent"
            class="w-full font-mono text-xs"
            rows="12"
            placeholder="Paste your BIND zone file records here..."
          ></textarea>
        </div>
        <p class="text-xs text-text-muted">
          Existing records will be preserved. Duplicate records will be skipped.
        </p>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showImport = false">Cancel</button>
        <button class="btn-primary" :disabled="importingRecords" @click="importRecords">
          {{ importingRecords ? 'Importing...' : 'Import Records' }}
        </button>
      </template>
    </Modal>

    <!-- Delete Record Confirm -->
    <ConfirmDialog
      v-model="showDeleteRecordConfirm"
      title="Delete DNS Record"
      :message="`Delete ${recordToDelete?.type} record '${recordToDelete?.name}'? This action cannot be undone.`"
      confirm-text="Delete Record"
      :destructive="true"
      @confirm="deleteRecord"
    />

    <!-- Cloudflare Configuration Modal -->
    <Modal v-model="showCfConfig" title="Configure Cloudflare" size="md">
      <div class="space-y-4">
        <p class="text-sm text-text-muted">
          Enter your Cloudflare credentials to enable DNS sync. Records will be
          automatically pushed to Cloudflare when created, updated, or deleted.
        </p>
        <div>
          <label class="input-label">Cloudflare Email</label>
          <input
            v-model="cfConfig.email"
            type="email"
            class="w-full"
            placeholder="you@example.com"
            required
          />
        </div>
        <div>
          <label class="input-label">API Key (Global API Key)</label>
          <input
            v-model="cfConfig.api_key"
            type="password"
            class="w-full"
            placeholder="Enter your Cloudflare Global API Key"
            required
          />
        </div>
        <div>
          <label class="input-label">Cloudflare Zone ID</label>
          <input
            v-model="cfConfig.cf_zone_id"
            type="text"
            class="w-full"
            placeholder="32-character zone ID from CF dashboard"
            required
          />
        </div>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showCfConfig = false">Cancel</button>
        <button
          class="btn-primary"
          :disabled="dns.cfLoading || !cfConfig.email || !cfConfig.api_key || !cfConfig.cf_zone_id"
          @click="enableCloudflare"
        >
          {{ dns.cfLoading ? 'Enabling...' : 'Enable Cloudflare' }}
        </button>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useDnsStore } from '@/stores/dns'
import { useNotificationsStore } from '@/stores/notifications'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'

const route = useRoute()
const dns = useDnsStore()
const notifications = useNotificationsStore()
const zoneId = route.params.id

const recordTypes = ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS', 'SRV', 'CAA', 'PTR']
const searchQuery = ref('')
const showImport = ref(false)
const showDeleteRecordConfirm = ref(false)
const addingRecord = ref(false)
const importingRecords = ref(false)
const importContent = ref('')
const recordToDelete = ref(null)

// Cloudflare state
const showCfConfig = ref(false)
const cfConfig = ref({ email: '', api_key: '', cf_zone_id: '' })

// DNSSEC state
const showDnssecConfig = ref(false)
const dnssecConfig = ref({ algorithm: 'ECDSAP256SHA256' })

const newRecord = ref({
  type: 'A',
  name: '@',
  value: '',
  ttl: 3600,
  priority: 10,
  caaFlags: 0,
  caaTag: 'issue',
  caaValue: ''
})

const editing = ref(null)

const filteredRecords = computed(() => {
  if (!searchQuery.value) return dns.records
  const q = searchQuery.value.toLowerCase()
  return dns.records.filter(r =>
    r.name.toLowerCase().includes(q) ||
    r.value.toLowerCase().includes(q) ||
    r.type.toLowerCase().includes(q)
  )
})

function showPriority(type) {
  return type === 'MX' || type === 'SRV'
}

function parseCaa(value) {
  // CAA value format: "flags tag "value""  e.g. '0 issue "letsencrypt.org"'
  const match = value && value.match(/^(\d+)\s+(\S+)\s+"?([^"]*)"?$/)
  if (match) {
    return { flags: match[1], tag: match[2], value: match[3] }
  }
  return { flags: '-', tag: '-', value: value || '' }
}

onMounted(async () => {
  await Promise.all([
    dns.fetchZone(zoneId),
    dns.fetchRecords(zoneId),
    dns.cfFetchStatus(zoneId),
    dns.dnssecFetchStatus(zoneId)
  ])
})

async function addRecord() {
  const rec = newRecord.value
  // For CAA, build value from sub-fields; for others, require value
  if (rec.type === 'CAA') {
    if (!rec.caaValue) return
    rec.value = `${rec.caaFlags} ${rec.caaTag} "${rec.caaValue}"`
  } else {
    if (!rec.value) return
  }
  addingRecord.value = true
  try {
    const payload = { ...rec }
    // Backend expects record_type, frontend uses type
    if (payload.type && !payload.record_type) {
      payload.record_type = payload.type
      delete payload.type
    }
    // Clean up CAA-specific fields before sending
    delete payload.caaFlags
    delete payload.caaTag
    delete payload.caaValue
    if (!showPriority(payload.record_type || payload.type)) delete payload.priority
    await dns.createRecord(zoneId, payload)
    notifications.success(`${rec.type} record added`)
    newRecord.value = { type: 'A', name: '@', value: '', ttl: 3600, priority: 10, caaFlags: 0, caaTag: 'issue', caaValue: '' }
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to add record')
  } finally {
    addingRecord.value = false
  }
}

function startEdit(record, field) {
  editing.value = { id: record.id, field, value: record[field] }
  nextTick(() => {
    const inputs = document.querySelectorAll('input:focus, select:focus')
    if (inputs.length === 0) {
      const row = document.querySelector(`input[type], select`)
      if (row) row.focus()
    }
  })
}

function cancelEdit() {
  editing.value = null
}

async function saveEdit(record) {
  if (!editing.value) return
  const { field, value } = editing.value
  if (record[field] === value) {
    editing.value = null
    return
  }
  try {
    const payload = { [field]: value }
    await dns.updateRecord(zoneId, record.id, payload)
    notifications.success('Record updated')
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to update record')
  }
  editing.value = null
}

async function saveRecordRow(record) {
  try {
    const payload = {
      type: record.type,
      name: record.name,
      value: record.value,
      ttl: record.ttl
    }
    if (showPriority(record.type)) payload.priority = record.priority
    await dns.updateRecord(zoneId, record.id, payload)
    notifications.success('Record saved')
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to save record')
  }
}

function confirmDeleteRecord(record) {
  recordToDelete.value = record
  showDeleteRecordConfirm.value = true
}

async function deleteRecord() {
  if (!recordToDelete.value) return
  try {
    await dns.removeRecord(zoneId, recordToDelete.value.id)
    notifications.success('Record deleted')
    recordToDelete.value = null
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to delete record')
  }
}

function exportZone() {
  const url = `/api/v1/dns/zones/${zoneId}/export`
  const link = document.createElement('a')
  link.href = url
  link.download = `${dns.currentZone?.name || 'zone'}.zone`
  link.click()
  notifications.info('Exporting zone file')
}

async function importRecords() {
  if (!importContent.value.trim()) return
  importingRecords.value = true
  try {
    const client = (await import('@/api/client')).default
    await client.post(`/dns/zones/${zoneId}/import`, {
      zone_file: importContent.value
    })
    await dns.fetchRecords(zoneId)
    notifications.success('Records imported successfully')
    showImport.value = false
    importContent.value = ''
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to import records')
  } finally {
    importingRecords.value = false
  }
}

// ----- DNSSEC actions -----

async function enableDnssec() {
  try {
    await dns.dnssecEnable(zoneId, dnssecConfig.value)
    notifications.success('DNSSEC enabled successfully')
    showDnssecConfig.value = false
    dnssecConfig.value = { algorithm: 'ECDSAP256SHA256' }
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to enable DNSSEC')
  }
}

async function disableDnssec() {
  if (!confirm('Disable DNSSEC? This will remove signing keys and the DS record. You should also remove the DS record from your registrar.')) return
  try {
    await dns.dnssecDisable(zoneId)
    notifications.success('DNSSEC disabled')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to disable DNSSEC')
  }
}

function copyDsRecord() {
  const ds = dns.dnssecStatus.ds_record
  if (!ds) return
  navigator.clipboard.writeText(ds).then(() => {
    notifications.success('DS record copied to clipboard')
  }).catch(() => {
    notifications.error('Failed to copy to clipboard')
  })
}

// ----- Cloudflare actions -----

async function enableCloudflare() {
  try {
    await dns.cfEnable(zoneId, cfConfig.value)
    notifications.success('Cloudflare integration enabled')
    showCfConfig.value = false
    cfConfig.value = { email: '', api_key: '', cf_zone_id: '' }
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to enable Cloudflare')
  }
}

async function disableCloudflare() {
  try {
    await dns.cfDisable(zoneId)
    notifications.success('Cloudflare integration disabled')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to disable Cloudflare')
  }
}

async function syncToCloudflare() {
  try {
    const result = await dns.cfSync(zoneId)
    notifications.success(`Synced ${result?.synced ?? 0} records to Cloudflare`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Cloudflare sync failed')
  }
}

async function importFromCloudflare() {
  try {
    const result = await dns.cfImport(zoneId)
    notifications.success(`Imported ${result?.records_imported ?? 0} records from Cloudflare`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Cloudflare import failed')
  }
}

async function toggleCfProxy(record) {
  const newState = !record._cfProxied
  try {
    await dns.cfToggleProxy(zoneId, record.id, newState)
    record._cfProxied = newState
    notifications.success(`Proxy ${newState ? 'enabled' : 'disabled'} for ${record.name}`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to toggle CF proxy')
  }
}
</script>
