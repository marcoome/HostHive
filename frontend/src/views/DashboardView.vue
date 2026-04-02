<template>
  <div class="dashboard" ref="dashboardRef">
    <!-- Page Header -->
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">Dashboard</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">Server overview and monitoring</p>
      </div>
      <button class="btn-secondary text-sm" @click="refreshAll">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="23 4 23 10 17 10"/>
          <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
        </svg>
        Refresh
      </button>
    </div>

    <!-- Server Stats Gauges -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <!-- CPU -->
      <div class="card flex flex-col items-center py-5">
        <template v-if="loading">
          <div class="skeleton w-[100px] h-[100px] rounded-full mb-3"></div>
          <div class="skeleton w-16 h-4"></div>
        </template>
        <template v-else>
          <GaugeChart :value="cpuUsage" label="CPU" :size="100" :stroke-width="7" />
          <p class="text-xs mt-2" :style="{ color: 'var(--text-muted)' }">{{ serverStats.cpu_cores || 0 }} Cores</p>
        </template>
      </div>

      <!-- RAM -->
      <div class="card flex flex-col items-center py-5">
        <template v-if="loading">
          <div class="skeleton w-[100px] h-[100px] rounded-full mb-3"></div>
          <div class="skeleton w-16 h-4"></div>
        </template>
        <template v-else>
          <GaugeChart :value="ramUsage" label="RAM" :size="100" :stroke-width="7" />
          <p class="text-xs mt-2" :style="{ color: 'var(--text-muted)' }">
            {{ formatBytes(serverStats.ram_used) }} / {{ formatBytes(serverStats.ram_total) }}
          </p>
        </template>
      </div>

      <!-- Disk -->
      <div class="card py-5 px-5">
        <template v-if="loading">
          <div class="skeleton w-full h-4 mb-3"></div>
          <div class="skeleton w-full h-6 mb-2"></div>
          <div class="skeleton w-24 h-4"></div>
        </template>
        <template v-else>
          <div class="flex items-center justify-between mb-3">
            <span class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">Disk Usage</span>
            <span class="text-sm font-semibold" :style="{ color: diskColor }">{{ diskUsage }}%</span>
          </div>
          <div class="w-full h-3 rounded-full overflow-hidden" :style="{ background: 'rgba(var(--border-rgb), 0.4)' }">
            <div
              class="h-full rounded-full transition-all duration-1000 ease-out"
              :style="{ width: diskUsage + '%', background: diskColor }"
            />
          </div>
          <p class="text-xs mt-2" :style="{ color: 'var(--text-muted)' }">
            {{ formatBytes(serverStats.disk_used) }} / {{ formatBytes(serverStats.disk_total) }}
          </p>
        </template>
      </div>

      <!-- Network -->
      <div class="card py-5 px-5">
        <template v-if="loading">
          <div class="skeleton w-full h-4 mb-4"></div>
          <div class="skeleton w-full h-4 mb-3"></div>
          <div class="skeleton w-full h-4"></div>
        </template>
        <template v-else>
          <span class="text-sm font-medium block mb-3" :style="{ color: 'var(--text-primary)' }">Network I/O</span>
          <div class="flex items-center gap-2 mb-2">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>
            </svg>
            <span class="text-xs" :style="{ color: 'var(--text-muted)' }">IN</span>
            <span class="text-sm font-semibold ml-auto" :style="{ color: 'var(--text-primary)' }">
              {{ formatBytes(serverStats.net_in || 0) }}/s
            </span>
          </div>
          <div class="flex items-center gap-2">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--error)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/>
            </svg>
            <span class="text-xs" :style="{ color: 'var(--text-muted)' }">OUT</span>
            <span class="text-sm font-semibold ml-auto" :style="{ color: 'var(--text-primary)' }">
              {{ formatBytes(serverStats.net_out || 0) }}/s
            </span>
          </div>
        </template>
      </div>
    </div>

    <!-- Quick Stats Row -->
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <div v-for="stat in quickStats" :key="stat.label" class="card flex items-center gap-3 py-4 px-4">
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
            <!-- v-html safe: icon is a hardcoded HTML entity from trusted source, not user input -->
            <span v-html="stat.icon" class="text-lg"></span>
          </div>
          <div>
            <p class="text-xs" :style="{ color: 'var(--text-muted)' }">{{ stat.label }}</p>
            <p class="text-xl font-semibold" :style="{ color: 'var(--text-primary)' }">{{ stat.value }}</p>
          </div>
        </template>
      </div>
    </div>

    <!-- Charts Section -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
      <div class="card-static p-5">
        <h3 class="text-sm font-medium mb-4" :style="{ color: 'var(--text-primary)' }">CPU Usage (24h)</h3>
        <template v-if="loading">
          <div class="skeleton w-full h-[250px] rounded-lg"></div>
        </template>
        <template v-else>
          <div class="relative h-[250px] w-full overflow-hidden">
            <Line :data="cpuChartData" :options="chartOptions" />
          </div>
        </template>
      </div>
      <div class="card-static p-5">
        <h3 class="text-sm font-medium mb-4" :style="{ color: 'var(--text-primary)' }">RAM Usage (24h)</h3>
        <template v-if="loading">
          <div class="skeleton w-full h-[250px] rounded-lg"></div>
        </template>
        <template v-else>
          <div class="relative h-[250px] w-full overflow-hidden">
            <Line :data="ramChartData" :options="chartOptions" />
          </div>
        </template>
      </div>
    </div>

    <!-- Alerts + Activity -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <!-- Alerts -->
      <div class="card-static p-5">
        <h3 class="text-sm font-medium mb-4" :style="{ color: 'var(--text-primary)' }">Alerts</h3>
        <template v-if="loading">
          <div v-for="i in 3" :key="i" class="skeleton w-full h-10 mb-2 rounded-lg"></div>
        </template>
        <template v-else>
          <div v-if="alerts.length === 0" class="text-sm py-4 text-center" :style="{ color: 'var(--text-muted)' }">
            No active alerts
          </div>
          <div v-else class="space-y-2">
            <div
              v-for="alert in alerts"
              :key="alert.id"
              class="flex items-center gap-3 p-3 rounded-lg"
              :style="{ background: 'rgba(var(--border-rgb), 0.15)' }"
            >
              <span :class="alert.badgeClass" class="badge">{{ alert.type }}</span>
              <span class="text-sm flex-1" :style="{ color: 'var(--text-primary)' }">{{ alert.message }}</span>
            </div>
          </div>
        </template>
      </div>

      <!-- Recent Activity -->
      <div class="card-static p-5">
        <h3 class="text-sm font-medium mb-4" :style="{ color: 'var(--text-primary)' }">Recent Activity</h3>
        <template v-if="loading">
          <div v-for="i in 5" :key="i" class="skeleton w-full h-12 mb-2 rounded-lg"></div>
        </template>
        <template v-else>
          <div v-if="recentActivity.length === 0" class="text-sm py-4 text-center" :style="{ color: 'var(--text-muted)' }">
            No recent activity
          </div>
          <div v-else class="space-y-1 max-h-[320px] overflow-y-auto">
            <div
              v-for="item in recentActivity"
              :key="item.id"
              class="flex items-start gap-3 p-2.5 rounded-lg transition-colors"
              :class="{ 'hover:bg-surface/40': true }"
            >
              <div
                class="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 text-xs font-medium mt-0.5"
                style="background: rgba(var(--primary-rgb), 0.15); color: var(--primary)"
              >
                {{ (item.user || 'S').charAt(0).toUpperCase() }}
              </div>
              <div class="flex-1 min-w-0">
                <p class="text-sm" :style="{ color: 'var(--text-primary)' }">
                  <span class="font-medium">{{ item.user }}</span>
                  {{ item.action }}
                </p>
                <p class="text-xs mt-0.5" :style="{ color: 'var(--text-muted)' }">
                  {{ item.time }} &middot; {{ item.ip }}
                </p>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip
} from 'chart.js'
import GaugeChart from '@/components/GaugeChart.vue'
import { useServerStore } from '@/stores/server'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip)

const serverStore = useServerStore()
const loading = ref(true)
const dashboardRef = ref(null)

// Mock data structures (will use real data from store when available)
const serverStats = computed(() => serverStore.stats || {
  cpu_usage: 42,
  cpu_cores: 8,
  ram_used: 6442450944,
  ram_total: 17179869184,
  ram_usage: 37,
  disk_used: 107374182400,
  disk_total: 536870912000,
  disk_usage: 20,
  net_in: 1258291,
  net_out: 524288
})

const cpuUsage = computed(() => serverStats.value.cpu_usage || 0)
const ramUsage = computed(() => serverStats.value.ram_usage || 0)
const diskUsage = computed(() => serverStats.value.disk_usage || 0)

const diskColor = computed(() => {
  const v = diskUsage.value
  if (v < 60) return 'var(--success)'
  if (v < 80) return 'var(--warning)'
  return 'var(--error)'
})

const quickStats = computed(() => [
  { label: 'Domains', value: serverStats.value.domains_count ?? 12, icon: '&#9673;' },
  { label: 'Databases', value: serverStats.value.databases_count ?? 8, icon: '&#9707;' },
  { label: 'Email Accounts', value: serverStats.value.email_count ?? 24, icon: '&#9993;' },
  { label: 'FTP Accounts', value: serverStats.value.ftp_count ?? 5, icon: '&#8645;' }
])

// Chart data - generates mock 24h data
function generateChartPoints(base, variance) {
  const points = []
  for (let i = 0; i < 24; i++) {
    points.push(Math.max(0, Math.min(100, base + (Math.random() - 0.5) * variance * 2)))
  }
  return points
}

const chartLabels = Array.from({ length: 24 }, (_, i) => {
  const h = (new Date().getHours() - 23 + i + 24) % 24
  return `${h.toString().padStart(2, '0')}:00`
})

const cpuChartData = computed(() => ({
  labels: chartLabels,
  datasets: [{
    label: 'CPU %',
    data: serverStats.value.cpu_history || generateChartPoints(cpuUsage.value, 15),
    borderColor: 'rgba(99, 102, 241, 1)',
    backgroundColor: 'rgba(99, 102, 241, 0.1)',
    fill: true,
    tension: 0.4,
    pointRadius: 0,
    pointHitRadius: 10,
    borderWidth: 2
  }]
}))

const ramChartData = computed(() => ({
  labels: chartLabels,
  datasets: [{
    label: 'RAM %',
    data: serverStats.value.ram_history || generateChartPoints(ramUsage.value, 10),
    borderColor: 'rgba(34, 197, 94, 1)',
    backgroundColor: 'rgba(34, 197, 94, 0.1)',
    fill: true,
    tension: 0.4,
    pointRadius: 0,
    pointHitRadius: 10,
    borderWidth: 2
  }]
}))

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: {
    intersect: false,
    mode: 'index'
  },
  plugins: {
    tooltip: {
      backgroundColor: 'rgba(17, 17, 24, 0.9)',
      titleColor: '#e2e8f0',
      bodyColor: '#e2e8f0',
      borderColor: 'rgba(30, 30, 46, 0.5)',
      borderWidth: 1,
      padding: 10,
      cornerRadius: 8,
      displayColors: false
    }
  },
  scales: {
    x: {
      grid: { color: 'rgba(var(--border-rgb), 0.15)' },
      ticks: {
        color: 'var(--text-muted)',
        font: { size: 10 },
        maxTicksLimit: 8
      }
    },
    y: {
      min: 0,
      max: 100,
      grid: { color: 'rgba(var(--border-rgb), 0.15)' },
      ticks: {
        color: 'var(--text-muted)',
        font: { size: 10 },
        callback: (v) => v + '%'
      }
    }
  }
}

// Alerts
const alerts = computed(() => {
  const list = []
  if (diskUsage.value > 90) {
    list.push({ id: 'disk', type: 'CRITICAL', message: `Disk usage at ${diskUsage.value}%`, badgeClass: 'badge-error' })
  } else if (diskUsage.value > 80) {
    list.push({ id: 'disk', type: 'WARNING', message: `Disk usage at ${diskUsage.value}%`, badgeClass: 'badge-warning' })
  }

  // Mock SSL expiry alerts
  const sslAlerts = serverStats.value.ssl_expiring || [
    { domain: 'example.com', days: 7 },
    { domain: 'api.example.com', days: 3 }
  ]
  sslAlerts.forEach((ssl, i) => {
    list.push({
      id: `ssl-${i}`,
      type: ssl.days <= 3 ? 'CRITICAL' : 'WARNING',
      message: `SSL for ${ssl.domain} expires in ${ssl.days} days`,
      badgeClass: ssl.days <= 3 ? 'badge-error' : 'badge-warning'
    })
  })

  // Mock service down alerts
  const downServices = serverStore.services.filter(s => s.status === 'stopped') || []
  downServices.forEach((svc, i) => {
    list.push({
      id: `svc-${i}`,
      type: 'DOWN',
      message: `Service ${svc.name} is not running`,
      badgeClass: 'badge-error'
    })
  })

  return list
})

// Recent Activity (mock)
const recentActivity = ref([
  { id: 1, user: 'admin', action: 'created domain example.com', time: '2 min ago', ip: '192.168.1.100' },
  { id: 2, user: 'admin', action: 'issued SSL certificate for example.com', time: '5 min ago', ip: '192.168.1.100' },
  { id: 3, user: 'john', action: 'created database myapp_db', time: '12 min ago', ip: '10.0.0.15' },
  { id: 4, user: 'admin', action: 'restarted nginx service', time: '25 min ago', ip: '192.168.1.100' },
  { id: 5, user: 'sarah', action: 'created email account info@example.com', time: '1 hour ago', ip: '172.16.0.5' },
  { id: 6, user: 'admin', action: 'updated firewall rules', time: '2 hours ago', ip: '192.168.1.100' },
  { id: 7, user: 'john', action: 'uploaded files via FTP', time: '3 hours ago', ip: '10.0.0.15' },
  { id: 8, user: 'admin', action: 'created backup (full)', time: '5 hours ago', ip: '192.168.1.100' },
  { id: 9, user: 'sarah', action: 'added DNS record A for api.example.com', time: '6 hours ago', ip: '172.16.0.5' },
  { id: 10, user: 'admin', action: 'updated server settings', time: '8 hours ago', ip: '192.168.1.100' }
])

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return parseFloat((bytes / Math.pow(1024, i)).toFixed(1)) + ' ' + sizes[i]
}

async function refreshAll() {
  loading.value = true
  try {
    await Promise.all([
      serverStore.fetchStats(),
      serverStore.fetchServices()
    ])
  } catch {
    // Use fallback mock data on error
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    await Promise.all([
      serverStore.fetchStats(),
      serverStore.fetchServices()
    ])
  } catch {
    // Will use default mock data
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.dashboard {
  position: relative;
  z-index: 1;
}
</style>
