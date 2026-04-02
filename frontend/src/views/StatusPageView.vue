<template>
  <div class="status-page" :class="themeClass">
    <!-- Header -->
    <header class="status-header">
      <div class="status-container">
        <div class="flex items-center gap-3">
          <div class="w-9 h-9 rounded-lg flex items-center justify-center" style="background: #6366f1;">
            <span class="text-white font-bold text-sm">H</span>
          </div>
          <span class="text-xl font-semibold">HostHive Status</span>
        </div>
      </div>
    </header>

    <!-- Overall Status Banner -->
    <section class="status-container mt-8">
      <div v-if="loading" class="status-banner status-banner--loading">
        <div class="skeleton h-6 w-48 mx-auto" style="border-radius: 6px;"></div>
      </div>
      <div v-else class="status-banner" :class="overallBannerClass">
        <div class="flex items-center justify-center gap-3">
          <span class="text-2xl">{{ overallIcon }}</span>
          <span class="text-lg font-semibold">{{ overallMessage }}</span>
        </div>
        <p class="text-sm opacity-75 mt-1">Last updated: {{ lastUpdated }}</p>
      </div>
    </section>

    <!-- Services Grid -->
    <section class="status-container mt-8">
      <h2 class="text-lg font-semibold mb-4">Services</h2>
      <div v-if="loading" class="space-y-3">
        <div v-for="i in 6" :key="i" class="status-service-card">
          <div class="flex items-center justify-between mb-2">
            <div class="skeleton h-4 w-32"></div>
            <div class="skeleton h-4 w-16"></div>
          </div>
          <div class="flex gap-[2px]">
            <div v-for="j in 90" :key="j" class="skeleton" style="width: 6px; height: 20px; border-radius: 2px;"></div>
          </div>
        </div>
      </div>
      <div v-else class="space-y-3">
        <div v-for="svc in services" :key="svc.name" class="status-service-card">
          <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-2">
              <span class="status-dot" :class="statusDotClass(svc.status)"></span>
              <span class="font-medium text-sm">{{ svc.name }}</span>
            </div>
            <span class="text-sm opacity-60">{{ svc.uptime }}% uptime</span>
          </div>
          <!-- 90-day uptime bar -->
          <div class="flex gap-[2px]" :title="`90-day uptime history for ${svc.name}`">
            <div
              v-for="(day, idx) in svc.daily_status"
              :key="idx"
              class="uptime-bar-segment"
              :class="uptimeBarClass(day)"
              :title="`${dayLabel(idx)}: ${day}`"
            ></div>
          </div>
          <div class="flex justify-between mt-1">
            <span class="text-xs opacity-40">90 days ago</span>
            <span class="text-xs opacity-40">Today</span>
          </div>
        </div>
      </div>
    </section>

    <!-- Incidents -->
    <section class="status-container mt-8 mb-16">
      <h2 class="text-lg font-semibold mb-4">Recent Incidents</h2>
      <div v-if="loading" class="space-y-4">
        <div v-for="i in 3" :key="i" class="status-incident-card">
          <div class="skeleton h-4 w-48 mb-2"></div>
          <div class="skeleton h-3 w-full mb-1"></div>
          <div class="skeleton h-3 w-3/4"></div>
        </div>
      </div>
      <div v-else-if="groupedIncidents.length === 0" class="status-incident-card text-center opacity-60">
        <p class="text-sm">No incidents reported in the last 30 days.</p>
      </div>
      <div v-else class="space-y-6">
        <div v-for="group in groupedIncidents" :key="group.date">
          <h3 class="text-sm font-semibold mb-3 opacity-60">{{ group.dateLabel }}</h3>
          <div class="space-y-3">
            <div v-for="incident in group.incidents" :key="incident.id" class="status-incident-card">
              <div class="flex items-center gap-2 mb-2">
                <span class="font-medium text-sm">{{ incident.title }}</span>
                <span class="status-severity-badge" :class="severityClass(incident.severity)">
                  {{ incident.severity }}
                </span>
                <span class="status-severity-badge" :class="incidentStatusClass(incident.status)">
                  {{ incident.status }}
                </span>
              </div>
              <p class="text-sm opacity-70">{{ incident.description }}</p>
              <div class="flex gap-4 mt-2 text-xs opacity-50">
                <span>Started: {{ formatIncidentTime(incident.started_at) }}</span>
                <span v-if="incident.resolved_at">Resolved: {{ formatIncidentTime(incident.resolved_at) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Footer -->
    <footer class="status-footer">
      <div class="status-container text-center">
        <p class="text-sm opacity-50">Powered by HostHive</p>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import axios from 'axios'

const loading = ref(true)
const services = ref([])
const incidents = ref([])
const overallStatus = ref('operational')
let refreshInterval = null

const themeClass = computed(() => {
  if (typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'status-dark'
  }
  return 'status-light'
})

const overallBannerClass = computed(() => {
  const map = {
    operational: 'status-banner--ok',
    degraded: 'status-banner--degraded',
    outage: 'status-banner--outage'
  }
  return map[overallStatus.value] || map.operational
})

const overallIcon = computed(() => {
  const map = { operational: '\u2713', degraded: '\u26A0', outage: '\u2717' }
  return map[overallStatus.value] || '\u2713'
})

const overallMessage = computed(() => {
  const map = {
    operational: 'All Systems Operational',
    degraded: 'Some Systems Degraded',
    outage: 'Major Outage'
  }
  return map[overallStatus.value] || 'All Systems Operational'
})

const lastUpdated = computed(() => new Date().toLocaleTimeString())

const groupedIncidents = computed(() => {
  const groups = {}
  incidents.value.forEach(inc => {
    const date = new Date(inc.started_at).toISOString().slice(0, 10)
    if (!groups[date]) {
      groups[date] = {
        date,
        dateLabel: new Date(inc.started_at).toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' }),
        incidents: []
      }
    }
    groups[date].incidents.push(inc)
  })
  return Object.values(groups).sort((a, b) => b.date.localeCompare(a.date))
})

function statusDotClass(status) {
  const map = { operational: 'dot-green', degraded: 'dot-yellow', outage: 'dot-red' }
  return map[status] || 'dot-green'
}

function uptimeBarClass(status) {
  if (status === 'operational' || status === 'up') return 'bar-green'
  if (status === 'degraded' || status === 'partial') return 'bar-yellow'
  if (status === 'outage' || status === 'down') return 'bar-red'
  return 'bar-gray'
}

function dayLabel(idx) {
  const d = new Date()
  d.setDate(d.getDate() - (89 - idx))
  return d.toLocaleDateString()
}

function severityClass(severity) {
  const map = { critical: 'sev-red', major: 'sev-red', minor: 'sev-yellow', maintenance: 'sev-blue' }
  return map[severity] || 'sev-blue'
}

function incidentStatusClass(status) {
  if (status === 'resolved') return 'sev-green'
  if (status === 'monitoring') return 'sev-blue'
  if (status === 'investigating') return 'sev-yellow'
  return 'sev-yellow'
}

function formatIncidentTime(ts) {
  if (!ts) return '--'
  return new Date(ts).toLocaleString()
}

async function fetchStatus() {
  try {
    const { data } = await axios.get('/api/v1/status')
    services.value = data.services || []
    incidents.value = data.incidents || []
    overallStatus.value = data.overall || 'operational'
  } catch {
    // If API fails, show empty state
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchStatus()
  refreshInterval = setInterval(fetchStatus, 60000)
})

onUnmounted(() => {
  if (refreshInterval) clearInterval(refreshInterval)
})
</script>

<style scoped>
.status-page {
  min-height: 100vh;
  font-family: 'Inter', system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
}

/* Light theme (default for public page) */
.status-light {
  background: #f8fafc;
  color: #1e293b;
}

.status-dark {
  background: #0f172a;
  color: #e2e8f0;
}

.status-container {
  max-width: 720px;
  margin: 0 auto;
  padding: 0 1.5rem;
}

.status-header {
  padding: 1.25rem 0;
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
}
.status-dark .status-header {
  border-bottom-color: rgba(255, 255, 255, 0.08);
}

/* Banners */
.status-banner {
  padding: 1.5rem;
  border-radius: 12px;
  text-align: center;
}
.status-banner--ok {
  background: #dcfce7;
  color: #166534;
}
.status-dark .status-banner--ok {
  background: rgba(34, 197, 94, 0.15);
  color: #4ade80;
}
.status-banner--degraded {
  background: #fef3c7;
  color: #92400e;
}
.status-dark .status-banner--degraded {
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
}
.status-banner--outage {
  background: #fee2e2;
  color: #991b1b;
}
.status-dark .status-banner--outage {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
}
.status-banner--loading {
  background: rgba(0, 0, 0, 0.04);
}
.status-dark .status-banner--loading {
  background: rgba(255, 255, 255, 0.04);
}

/* Service cards */
.status-service-card {
  padding: 1rem 1.25rem;
  border-radius: 10px;
  border: 1px solid rgba(0, 0, 0, 0.06);
  background: white;
}
.status-dark .status-service-card {
  border-color: rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.04);
}

/* Status dots */
.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}
.dot-green { background: #22c55e; }
.dot-yellow { background: #f59e0b; }
.dot-red { background: #ef4444; }

/* Uptime bar segments */
.uptime-bar-segment {
  flex: 1;
  height: 22px;
  border-radius: 2px;
  transition: opacity 0.2s;
}
.uptime-bar-segment:hover {
  opacity: 0.7;
}
.bar-green { background: #22c55e; }
.bar-yellow { background: #f59e0b; }
.bar-red { background: #ef4444; }
.bar-gray { background: #d1d5db; }
.status-dark .bar-gray { background: #374151; }

/* Incident cards */
.status-incident-card {
  padding: 1rem 1.25rem;
  border-radius: 10px;
  border: 1px solid rgba(0, 0, 0, 0.06);
  background: white;
}
.status-dark .status-incident-card {
  border-color: rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.04);
}

/* Severity badges */
.status-severity-badge {
  display: inline-flex;
  align-items: center;
  padding: 0.125rem 0.5rem;
  border-radius: 9999px;
  font-size: 0.675rem;
  font-weight: 500;
  text-transform: capitalize;
}
.sev-red {
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
}
.sev-yellow {
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
}
.sev-blue {
  background: rgba(99, 102, 241, 0.12);
  color: #6366f1;
}
.sev-green {
  background: rgba(34, 197, 94, 0.12);
  color: #22c55e;
}

/* Skeleton (standalone, no tailwind dependency) */
.skeleton {
  background: linear-gradient(90deg, rgba(0,0,0,0.06) 25%, rgba(0,0,0,0.1) 50%, rgba(0,0,0,0.06) 75%);
  background-size: 200% 100%;
  animation: status-shimmer 1.5s ease-in-out infinite;
  border-radius: 4px;
}
.status-dark .skeleton {
  background: linear-gradient(90deg, rgba(255,255,255,0.04) 25%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.04) 75%);
  background-size: 200% 100%;
}
@keyframes status-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.status-footer {
  padding: 2rem 0;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}
.status-dark .status-footer {
  border-top-color: rgba(255, 255, 255, 0.06);
}
</style>
