<template>
  <div class="space-y-6">
    <!-- Page Header -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">Audit Log</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">
          Track all actions and changes across your hosting panel
        </p>
      </div>
      <button class="btn-secondary" @click="handleExport">
        &#8615; Export CSV
      </button>
    </div>

    <!-- Filter Bar -->
    <div class="glass rounded-2xl p-6">
      <div class="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
        <div>
          <label class="input-label">User</label>
          <select v-model="store.filters.user" class="w-full">
            <option value="">All Users</option>
            <option v-for="u in users" :key="u.id" :value="u.username">{{ u.username }}</option>
          </select>
        </div>
        <div>
          <label class="input-label">Action</label>
          <input
            type="text"
            v-model="store.filters.action"
            class="w-full"
            placeholder="e.g. domain.*"
          />
        </div>
        <div>
          <label class="input-label">Date From</label>
          <input type="date" v-model="store.filters.date_from" class="w-full" />
        </div>
        <div>
          <label class="input-label">Date To</label>
          <input type="date" v-model="store.filters.date_to" class="w-full" />
        </div>
        <div>
          <label class="input-label">IP Address</label>
          <input type="text" v-model="store.filters.ip" class="w-full" placeholder="192.168.1.1" />
        </div>
      </div>
      <div class="mt-4 flex justify-end">
        <button class="btn-primary" @click="applyFilters">
          Apply Filters
        </button>
      </div>
    </div>

    <!-- Suspicious Activity Section -->
    <div v-if="store.suspicious.length > 0" class="glass rounded-2xl overflow-hidden">
      <button
        class="w-full px-6 py-4 flex items-center justify-between text-left"
        @click="showSuspicious = !showSuspicious"
      >
        <div class="flex items-center gap-2">
          <span class="text-error text-lg">&#9888;</span>
          <span class="font-semibold text-sm" :style="{ color: 'var(--text-primary)' }">
            Suspicious Activity Detected ({{ store.suspicious.length }})
          </span>
        </div>
        <span class="text-text-muted text-xs">{{ showSuspicious ? '&#9650;' : '&#9660;' }}</span>
      </button>
      <Transition name="collapse">
        <div v-if="showSuspicious" class="border-t border-border">
          <div
            v-for="entry in store.suspicious"
            :key="entry.id"
            class="px-6 py-3 flex items-center gap-4 text-sm"
            style="background: rgba(239, 68, 68, 0.06);"
          >
            <span class="text-text-muted text-xs whitespace-nowrap">{{ formatTime(entry.timestamp) }}</span>
            <span class="font-medium" :style="{ color: 'var(--text-primary)' }">{{ entry.user }}</span>
            <span class="badge badge-error">{{ entry.action }}</span>
            <span class="text-text-muted">{{ entry.ip }}</span>
            <span class="ml-auto text-xs text-error">{{ entry.reason || '> 10 actions/min' }}</span>
          </div>
        </div>
      </Transition>
    </div>

    <!-- Data Table -->
    <DataTable
      :columns="columns"
      :rows="store.entries"
      :loading="store.loading"
      :current-page="store.pagination.page"
      :total-pages="store.pagination.totalPages"
      :skeleton-rows="10"
      empty-text="No audit log entries found."
      @page-change="handlePageChange"
    >
      <template #cell-timestamp="{ value }">
        <span :title="new Date(value).toLocaleString()">
          {{ formatRelativeTime(value) }}
        </span>
      </template>

      <template #cell-user="{ value }">
        <div class="flex items-center gap-2">
          <div class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium text-white" style="background: var(--primary);">
            {{ (value || '?')[0].toUpperCase() }}
          </div>
          <span>{{ value }}</span>
        </div>
      </template>

      <template #cell-action="{ value }">
        <span class="badge" :class="actionBadgeClass(value)">
          {{ value }}
        </span>
      </template>

      <template #cell-resource="{ row }">
        <span class="text-xs">
          {{ row.resource_type }} <span class="text-text-muted">#{{ row.resource_id }}</span>
        </span>
      </template>

      <template #cell-ip="{ value }">
        <code class="text-xs px-1.5 py-0.5 rounded" :style="{ background: 'var(--surface-elevated)' }">{{ value }}</code>
      </template>

      <template #cell-result="{ value }">
        <span class="badge" :class="value === 'success' ? 'badge-success' : 'badge-error'">
          {{ value }}
        </span>
      </template>

      <template #cell-details="{ value, row }">
        <button
          v-if="value || row.details"
          class="btn-ghost text-xs px-2 py-1"
          :title="value || row.details"
          @click="expandedRow = expandedRow === row.id ? null : row.id"
        >
          {{ expandedRow === row.id ? 'Hide' : 'Details' }}
        </button>
        <span v-else class="text-text-muted text-xs">--</span>
      </template>
    </DataTable>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useAuditStore } from '@/stores/audit'
import DataTable from '@/components/DataTable.vue'
import client from '@/api/client'

const store = useAuditStore()
const users = ref([])
const showSuspicious = ref(false)
const expandedRow = ref(null)

const columns = [
  { key: 'timestamp', label: 'Timestamp' },
  { key: 'user', label: 'User' },
  { key: 'action', label: 'Action' },
  { key: 'resource', label: 'Resource' },
  { key: 'ip', label: 'IP Address' },
  { key: 'result', label: 'Result' },
  { key: 'details', label: 'Details' }
]

function actionBadgeClass(action) {
  if (!action) return 'badge-info'
  const a = action.toLowerCase()
  if (a.includes('create') || a.includes('add')) return 'badge-success'
  if (a.includes('update') || a.includes('edit') || a.includes('modify')) return 'badge-info'
  if (a.includes('delete') || a.includes('remove') || a.includes('revoke')) return 'badge-error'
  if (a.includes('login') || a.includes('auth') || a.includes('logout')) return 'badge-warning'
  return 'badge-info'
}

function formatRelativeTime(timestamp) {
  if (!timestamp) return '--'
  const now = Date.now()
  const then = new Date(timestamp).getTime()
  const diffSec = Math.floor((now - then) / 1000)
  if (diffSec < 60) return `${diffSec}s ago`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`
  if (diffSec < 604800) return `${Math.floor(diffSec / 86400)}d ago`
  return new Date(timestamp).toLocaleDateString()
}

function formatTime(timestamp) {
  if (!timestamp) return '--'
  return new Date(timestamp).toLocaleString()
}

function applyFilters() {
  store.pagination.page = 1
  store.fetchEntries()
}

function handlePageChange(page) {
  store.pagination.page = page
  store.fetchEntries()
}

async function handleExport() {
  await store.exportCsv()
}

async function fetchUsers() {
  try {
    const { data } = await client.get('/users')
    users.value = data.users || data || []
  } catch {
    // Non-critical
  }
}

onMounted(() => {
  store.fetchEntries()
  store.fetchSuspicious()
  fetchUsers()
})
</script>

<style scoped>
.collapse-enter-active,
.collapse-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}
.collapse-enter-from,
.collapse-leave-to {
  max-height: 0;
  opacity: 0;
}
.collapse-enter-to,
.collapse-leave-from {
  max-height: 500px;
  opacity: 1;
}
</style>
