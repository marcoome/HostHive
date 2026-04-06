<template>
  <div class="space-y-6">
    <!-- Page Header -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">Reseller Dashboard</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">Overview of your reseller account</p>
      </div>
      <button class="btn-secondary text-sm" @click="refreshAll">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="23 4 23 10 17 10"/>
          <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
        </svg>
        Refresh
      </button>
    </div>

    <!-- Stats Cards -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <div v-for="stat in statsCards" :key="stat.label" class="card flex items-center gap-3 py-4 px-4">
        <template v-if="loading">
          <div class="skeleton w-10 h-10 rounded-lg flex-shrink-0"></div>
          <div class="flex-1">
            <div class="skeleton w-16 h-3 mb-2"></div>
            <div class="skeleton w-10 h-5"></div>
          </div>
        </template>
        <template v-else>
          <div
            class="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
            :style="{ background: `rgba(var(--primary-rgb), 0.12)`, color: 'var(--primary)' }"
          >
            <span v-html="stat.icon" class="text-lg"></span>
          </div>
          <div>
            <p class="text-xs" :style="{ color: 'var(--text-muted)' }">{{ stat.label }}</p>
            <p class="text-xl font-semibold" :style="{ color: 'var(--text-primary)' }">{{ stat.value }}</p>
          </div>
        </template>
      </div>
    </div>

    <!-- Resource Limits -->
    <div class="glass rounded-2xl p-6" v-if="limits">
      <h3 class="text-sm font-medium mb-4" :style="{ color: 'var(--text-primary)' }">Resource Limits</h3>
      <div class="space-y-4">
        <div v-for="bar in resourceBars" :key="bar.label">
          <div class="flex items-center justify-between mb-1">
            <span class="text-sm" :style="{ color: 'var(--text-primary)' }">{{ bar.label }}</span>
            <span class="text-xs font-mono" :style="{ color: 'var(--text-muted)' }">{{ bar.used }} / {{ bar.total }}</span>
          </div>
          <div class="w-full h-3 rounded-full overflow-hidden" :style="{ background: 'rgba(var(--border-rgb), 0.4)' }">
            <div
              class="h-full rounded-full transition-all duration-1000 ease-out"
              :style="{ width: bar.percent + '%', background: barColor(bar.percent) }"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- Recent Users -->
    <div class="glass rounded-2xl p-6">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">Recent Users</h3>
        <router-link to="/reseller/users" class="text-xs text-primary hover:underline">View all</router-link>
      </div>
      <template v-if="loading">
        <div v-for="i in 5" :key="i" class="skeleton w-full h-12 mb-2 rounded-lg"></div>
      </template>
      <template v-else>
        <div v-if="recentUsers.length === 0" class="text-sm py-4 text-center" :style="{ color: 'var(--text-muted)' }">
          No users created yet
        </div>
        <div v-else class="space-y-1">
          <div
            v-for="user in recentUsers"
            :key="user.id"
            class="flex items-center gap-3 p-2.5 rounded-lg transition-colors hover:bg-[rgba(var(--primary-rgb),0.04)]"
          >
            <div
              class="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 text-xs font-medium"
              style="background: rgba(var(--primary-rgb), 0.15); color: var(--primary)"
            >
              {{ (user.username || 'U').charAt(0).toUpperCase() }}
            </div>
            <div class="flex-1 min-w-0">
              <p class="text-sm font-medium truncate" :style="{ color: 'var(--text-primary)' }">{{ user.username }}</p>
              <p class="text-xs truncate" :style="{ color: 'var(--text-muted)' }">{{ user.email }}</p>
            </div>
            <span
              class="badge text-xs"
              :class="user.is_suspended ? 'badge-error' : 'badge-success'"
            >
              {{ user.is_suspended ? 'Suspended' : 'Active' }}
            </span>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useResellerStore } from '@/stores/reseller'

const store = useResellerStore()
const loading = ref(true)

const statsCards = computed(() => {
  const d = store.dashboard || {}
  return [
    { label: 'Total Users', value: d.total_users ?? 0, icon: '&#9823;' },
    { label: 'Active Users', value: d.active_users ?? 0, icon: '&#9673;' },
    { label: 'Disk Used', value: (d.used_disk_mb ?? 0) + ' MB', icon: '&#9707;' },
    { label: 'Bandwidth Used', value: (d.used_bandwidth_gb ?? 0).toFixed(1) + ' GB', icon: '&#8645;' }
  ]
})

const limits = computed(() => store.limits)

const resourceBars = computed(() => {
  const l = store.limits
  if (!l) return []
  const bars = []
  if (l.max_users != null) {
    const d = store.dashboard || {}
    bars.push({ label: 'Users', used: d.total_users ?? 0, total: l.max_users, percent: safePercent(d.total_users, l.max_users) })
  }
  if (l.max_disk_mb != null) {
    const d = store.dashboard || {}
    const usedMB = d.used_disk_mb ?? l.used_disk_mb ?? 0
    bars.push({ label: 'Disk (MB)', used: usedMB, total: l.max_disk_mb, percent: safePercent(usedMB, l.max_disk_mb) })
  }
  if (l.max_bandwidth_gb != null) {
    const d = store.dashboard || {}
    const usedGB = parseFloat(d.used_bandwidth_gb ?? l.used_bandwidth_gb ?? 0).toFixed(1)
    bars.push({ label: 'Bandwidth (GB)', used: usedGB, total: l.max_bandwidth_gb, percent: safePercent(parseFloat(usedGB), l.max_bandwidth_gb) })
  }
  if (l.max_domains != null) {
    const d = store.dashboard || {}
    bars.push({ label: 'Domains', used: d.total_domains ?? 0, total: l.max_domains, percent: safePercent(d.total_domains, l.max_domains) })
  }
  return bars
})

const recentUsers = computed(() => {
  return (store.users || []).slice(0, 5)
})

function safePercent(used, total) {
  if (!total || total <= 0) return 0
  return Math.min(Math.round((used / total) * 100), 100)
}

function barColor(pct) {
  if (pct < 60) return 'var(--success)'
  if (pct < 80) return 'var(--warning)'
  return 'var(--error)'
}

function formatSize(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return parseFloat((bytes / Math.pow(1024, i)).toFixed(1)) + ' ' + sizes[i]
}

async function refreshAll() {
  loading.value = true
  try {
    await Promise.all([
      store.fetchDashboard(),
      store.fetchUsers(),
      store.fetchLimits()
    ])
  } catch {
    // Use fallback data on error
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    await Promise.all([
      store.fetchDashboard(),
      store.fetchUsers(),
      store.fetchLimits()
    ])
  } catch {
    // Will display empty state
  } finally {
    loading.value = false
  }
})
</script>
