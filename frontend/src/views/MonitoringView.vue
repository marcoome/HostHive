<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">Monitoring</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">Real-time server metrics and anomaly detection</p>
      </div>
    </div>

    <!-- Real-time Stats -->
    <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
      <div v-for="metric in realtimeMetrics" :key="metric.key" class="glass rounded-2xl p-5">
        <div class="flex items-center justify-between mb-3">
          <span class="text-xs font-semibold uppercase tracking-wider" :style="{ color: 'var(--text-muted)' }">{{ metric.label }}</span>
          <span class="text-lg font-bold" :style="{ color: metric.color }">
            {{ currentValue(metric.key) }}{{ metric.unit }}
          </span>
        </div>
        <!-- Mini Chart -->
        <div class="h-16 flex items-end gap-0.5">
          <div
            v-for="(point, i) in monitor.realtimeStats[metric.key]"
            :key="i"
            class="flex-1 rounded-t transition-all duration-300"
            :style="{
              height: Math.max(2, point.value) + '%',
              background: metric.color,
              opacity: 0.3 + (i / monitor.realtimeStats[metric.key].length) * 0.7
            }"
          ></div>
          <div
            v-if="monitor.realtimeStats[metric.key].length === 0"
            v-for="i in 20"
            :key="'placeholder-' + i"
            class="flex-1 rounded-t"
            :style="{ height: '4px', background: 'rgba(var(--border-rgb), 0.3)' }"
          ></div>
        </div>
      </div>
    </div>

    <div class="grid grid-cols-1 xl:grid-cols-3 gap-6 mb-6">
      <!-- Services Health Grid -->
      <div class="xl:col-span-2">
        <div class="glass rounded-2xl p-6">
          <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">Services Health</h3>
          <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <div v-if="monitor.healthChecks.length === 0" v-for="i in 6" :key="i" class="skeleton h-20 rounded-xl"></div>
            <div
              v-for="svc in monitor.healthChecks"
              :key="svc.name"
              class="glass rounded-xl p-4"
            >
              <div class="flex items-center gap-2 mb-2">
                <span
                  class="w-2.5 h-2.5 rounded-full flex-shrink-0"
                  :style="{ background: svc.status === 'healthy' ? 'var(--success)' : svc.status === 'degraded' ? 'var(--warning)' : 'var(--error)' }"
                ></span>
                <span class="text-sm font-medium truncate" :style="{ color: 'var(--text-primary)' }">{{ svc.name }}</span>
              </div>
              <div class="flex justify-between text-xs">
                <span :style="{ color: 'var(--text-muted)' }">{{ svc.response_time || 0 }}ms</span>
                <span :style="{ color: 'var(--success)' }">{{ svc.uptime || 100 }}% uptime</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Disk Prediction -->
      <div>
        <div class="glass rounded-2xl p-6 h-full">
          <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">Disk Prediction</h3>
          <div v-if="monitor.diskPrediction" class="text-center">
            <div class="text-4xl font-bold mb-2" :style="{ color: diskDaysColor }">
              ~{{ monitor.diskPrediction.days_until_full || '?' }}
            </div>
            <p class="text-sm" :style="{ color: 'var(--text-muted)' }">days until disk full</p>

            <!-- Trend Line -->
            <div class="mt-6 h-24 flex items-end justify-center gap-1">
              <div
                v-for="(point, i) in (monitor.diskPrediction.trend || [])"
                :key="i"
                class="w-3 rounded-t transition-all duration-300"
                :style="{
                  height: point + '%',
                  background: point > 80 ? 'var(--error)' : point > 60 ? 'var(--warning)' : 'var(--primary)',
                  opacity: 0.5 + (i / (monitor.diskPrediction.trend || []).length) * 0.5
                }"
              ></div>
            </div>

            <div class="mt-2 flex justify-between text-xs" :style="{ color: 'var(--text-muted)' }">
              <span>30d ago</span>
              <span>Now</span>
              <span>Predicted</span>
            </div>
          </div>
          <div v-else class="flex items-center justify-center h-40">
            <div class="skeleton h-12 w-12 rounded-full"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Anomaly Alerts -->
    <div v-if="monitor.anomalies.length > 0" class="mb-6">
      <div class="glass rounded-2xl p-6">
        <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">Anomaly Alerts</h3>
        <div class="space-y-3">
          <div
            v-for="anomaly in monitor.anomalies"
            :key="anomaly.id"
            class="glass rounded-xl p-4 flex items-center gap-4"
            :style="{
              borderLeft: `3px solid ${anomaly.severity === 'critical' ? 'var(--error)' : anomaly.severity === 'warning' ? 'var(--warning)' : 'var(--primary)'}`
            }"
          >
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-1">
                <span
                  class="badge"
                  :class="{
                    'badge-error': anomaly.severity === 'critical',
                    'badge-warning': anomaly.severity === 'warning',
                    'badge-info': anomaly.severity === 'info'
                  }"
                >
                  {{ anomaly.severity }}
                </span>
                <span class="text-xs" :style="{ color: 'var(--text-muted)' }">{{ anomaly.timestamp }}</span>
              </div>
              <p class="text-sm" :style="{ color: 'var(--text-primary)' }">{{ anomaly.message }}</p>
            </div>
            <button
              v-if="!anomaly.acknowledged"
              class="btn-secondary text-xs flex-shrink-0"
              @click="monitor.acknowledgeAnomaly(anomaly.id)"
            >
              Acknowledge
            </button>
            <span v-else class="badge badge-success flex-shrink-0">Acknowledged</span>
          </div>
        </div>
      </div>
    </div>

    <div class="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-6">
      <!-- Traffic Heatmap -->
      <div class="glass rounded-2xl p-6">
        <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">Traffic Heatmap</h3>
        <div class="overflow-x-auto">
          <!-- Hours header -->
          <div class="flex gap-0.5 mb-1 ml-12">
            <div
              v-for="h in 24"
              :key="'h' + h"
              class="flex-1 text-center text-[9px]"
              :style="{ color: 'var(--text-muted)', minWidth: '16px' }"
            >
              {{ (h - 1).toString().padStart(2, '0') }}
            </div>
          </div>
          <!-- Rows (days) -->
          <div class="space-y-0.5">
            <div v-for="(day, di) in dayLabels" :key="di" class="flex items-center gap-1">
              <span class="w-10 text-[10px] text-right flex-shrink-0" :style="{ color: 'var(--text-muted)' }">{{ day }}</span>
              <div class="flex gap-0.5 flex-1">
                <div
                  v-for="h in 24"
                  :key="di + '-' + h"
                  class="flex-1 aspect-square rounded-sm cursor-pointer transition-all hover:scale-125 relative group"
                  :style="{
                    background: getHeatmapColor(di, h - 1),
                    minWidth: '16px',
                    minHeight: '16px'
                  }"
                >
                  <!-- Tooltip -->
                  <div class="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block z-10">
                    <div class="glass-strong rounded px-2 py-1 text-[10px] whitespace-nowrap" :style="{ color: 'var(--text-primary)' }">
                      {{ day }} {{ (h - 1).toString().padStart(2, '0') }}:00 - {{ getHeatmapValue(di, h - 1) }} requests
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <!-- Legend -->
          <div class="flex items-center justify-end gap-1 mt-3">
            <span class="text-[10px]" :style="{ color: 'var(--text-muted)' }">Less</span>
            <div
              v-for="i in 5"
              :key="'legend' + i"
              class="w-3 h-3 rounded-sm"
              :style="{ background: `rgba(var(--primary-rgb), ${i * 0.2})` }"
            ></div>
            <span class="text-[10px]" :style="{ color: 'var(--text-muted)' }">More</span>
          </div>
        </div>
      </div>

      <!-- Incidents Timeline -->
      <div class="glass rounded-2xl p-6">
        <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">Incidents Timeline</h3>
        <div class="space-y-0 relative">
          <!-- Vertical line -->
          <div
            class="absolute left-[11px] top-2 bottom-2 w-0.5"
            :style="{ background: 'rgba(var(--border-rgb), 0.4)' }"
          ></div>

          <div v-if="monitor.incidents.length === 0" class="text-sm text-center py-8" :style="{ color: 'var(--text-muted)' }">
            No incidents recorded
          </div>

          <div
            v-for="incident in monitor.incidents"
            :key="incident.id"
            class="flex gap-4 py-3 relative"
          >
            <!-- Dot -->
            <div
              class="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 z-10"
              :style="{
                background: incident.severity === 'critical' ? 'var(--error)' :
                  incident.severity === 'major' ? 'var(--warning)' : 'var(--primary)',
                boxShadow: `0 0 8px ${incident.severity === 'critical' ? 'var(--error)' : incident.severity === 'major' ? 'var(--warning)' : 'var(--primary)'}`
              }"
            >
              <span class="w-2 h-2 rounded-full bg-white"></span>
            </div>

            <!-- Content -->
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-1">
                <span class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">{{ incident.title }}</span>
                <span
                  v-if="incident.resolved"
                  class="badge badge-success"
                >Resolved</span>
                <span
                  v-else
                  class="badge badge-error"
                >Active</span>
              </div>
              <p class="text-xs" :style="{ color: 'var(--text-muted)' }">{{ incident.description }}</p>
              <span class="text-[10px]" :style="{ color: 'var(--text-muted)' }">{{ incident.timestamp }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Domain Bandwidth -->
    <div class="glass rounded-2xl p-6">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-sm font-semibold uppercase tracking-wider" :style="{ color: 'var(--text-muted)' }">Domain Bandwidth (Last 30 Days)</h3>
        <select v-model="selectedDomain" class="text-sm px-3 py-1.5" @change="loadBandwidth">
          <option value="">Select domain...</option>
          <option v-for="d in availableDomains" :key="d" :value="d">{{ d }}</option>
        </select>
      </div>

      <div v-if="bandwidthData.length > 0" class="h-48 flex items-end gap-1">
        <div
          v-for="(bar, i) in bandwidthData"
          :key="i"
          class="flex-1 rounded-t transition-all duration-300 cursor-pointer relative group"
          :style="{
            height: (bar.value / maxBandwidth * 100) + '%',
            background: 'var(--primary)',
            opacity: 0.5 + (bar.value / maxBandwidth) * 0.5,
            minHeight: '4px'
          }"
        >
          <div class="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block z-10">
            <div class="glass-strong rounded px-2 py-1 text-[10px] whitespace-nowrap" :style="{ color: 'var(--text-primary)' }">
              {{ bar.date }}: {{ formatBytes(bar.value) }}
            </div>
          </div>
        </div>
      </div>
      <div v-else class="h-48 flex items-center justify-center">
        <span class="text-sm" :style="{ color: 'var(--text-muted)' }">Select a domain to view bandwidth</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useMonitoringStore } from '@/stores/monitoring'

const monitor = useMonitoringStore()

const selectedDomain = ref('')
const bandwidthData = ref([])
const availableDomains = ref([])
let pollingInterval = null

const dayLabels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const realtimeMetrics = [
  { key: 'cpu', label: 'CPU Usage', unit: '%', color: 'var(--primary)' },
  { key: 'ram', label: 'Memory', unit: '%', color: 'var(--success)' },
  { key: 'diskIo', label: 'Disk I/O', unit: ' MB/s', color: 'var(--warning)' },
  { key: 'networkIo', label: 'Network I/O', unit: ' Mbps', color: '#6ee7b7' }
]

const diskDaysColor = computed(() => {
  const days = monitor.diskPrediction?.days_until_full
  if (!days) return 'var(--text-muted)'
  if (days < 7) return 'var(--error)'
  if (days < 30) return 'var(--warning)'
  return 'var(--success)'
})

const maxBandwidth = computed(() => {
  if (!bandwidthData.value.length) return 1
  return Math.max(...bandwidthData.value.map(b => b.value), 1)
})

function currentValue(key) {
  const data = monitor.realtimeStats[key]
  if (!data || data.length === 0) return 0
  return data[data.length - 1].value
}

function getHeatmapValue(day, hour) {
  if (!monitor.heatmapData || !monitor.heatmapData[day]) return 0
  return monitor.heatmapData[day][hour] || 0
}

function getHeatmapColor(day, hour) {
  const val = getHeatmapValue(day, hour)
  const maxVal = getMaxHeatmap()
  if (maxVal === 0) return 'rgba(var(--primary-rgb), 0.05)'
  const intensity = val / maxVal
  return `rgba(var(--primary-rgb), ${Math.max(0.05, intensity)})`
}

function getMaxHeatmap() {
  if (!monitor.heatmapData || !monitor.heatmapData.length) return 0
  let max = 0
  for (const row of monitor.heatmapData) {
    if (row) {
      for (const v of row) {
        if (v > max) max = v
      }
    }
  }
  return max
}

function formatBytes(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + ' MB'
  return (bytes / 1073741824).toFixed(2) + ' GB'
}

async function loadBandwidth() {
  if (!selectedDomain.value) {
    bandwidthData.value = []
    return
  }
  try {
    const data = await monitor.fetchBandwidth(selectedDomain.value)
    bandwidthData.value = data || []
  } catch {
    bandwidthData.value = []
  }
}

onMounted(async () => {
  try {
    await Promise.all([
      monitor.fetchHealth(),
      monitor.fetchIncidents(),
      monitor.fetchAnomalies(),
      monitor.fetchDiskPrediction(),
      monitor.fetchHeatmap()
    ])
  } catch {}

  // Populate available domains from health checks
  availableDomains.value = monitor.healthChecks
    .filter(h => h.domain)
    .map(h => h.domain)

  // Polling for real-time stats
  pollingInterval = setInterval(async () => {
    try { await monitor.fetchRealtimeStats() } catch {}
  }, 2000)

  // Initial fetch
  try { await monitor.fetchRealtimeStats() } catch {}
})

onUnmounted(() => {
  if (pollingInterval) clearInterval(pollingInterval)
})
</script>
