<template>
  <div>
    <!-- Page Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
      <div>
        <h1 class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">Analytics</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">Traffic insights, bandwidth usage, and visitor statistics</p>
      </div>
      <!-- Date Range Picker -->
      <div class="flex items-center gap-2 self-start sm:self-auto">
        <div class="glass rounded-xl flex overflow-hidden">
          <button
            v-for="preset in datePresets"
            :key="preset.value"
            class="px-3 py-2 text-xs font-medium transition-all min-h-[40px]"
            :style="{
              background: selectedPeriod === preset.value ? 'var(--primary)' : 'transparent',
              color: selectedPeriod === preset.value ? '#fff' : 'var(--text-muted)'
            }"
            @click="setPeriod(preset.value)"
          >
            {{ preset.label }}
          </button>
        </div>
        <button
          class="btn-secondary text-sm min-h-[40px] inline-flex items-center gap-1.5"
          @click="refreshData"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="23 4 23 10 17 10"/>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
          </svg>
          Refresh
        </button>
      </div>
    </div>

    <!-- Overview Cards -->
    <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
      <div v-for="card in overviewCards" :key="card.label" class="glass rounded-2xl p-5">
        <template v-if="analytics.loading">
          <div class="skeleton w-20 h-3 mb-3"></div>
          <div class="skeleton w-24 h-7 mb-2"></div>
          <div class="skeleton w-16 h-3"></div>
        </template>
        <template v-else>
          <div class="flex items-center justify-between mb-1">
            <span class="text-xs font-semibold uppercase tracking-wider" :style="{ color: 'var(--text-muted)' }">
              {{ card.label }}
            </span>
            <span class="w-8 h-8 rounded-lg flex items-center justify-center" :style="{ background: card.bgColor }">
              <!-- v-html safe: icon is hardcoded SVG from trusted source -->
              <span v-html="card.icon" class="text-sm"></span>
            </span>
          </div>
          <div class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">{{ card.value }}</div>
          <div v-if="card.sub" class="text-xs mt-1" :style="{ color: 'var(--text-muted)' }">{{ card.sub }}</div>
        </template>
      </div>
    </div>

    <div class="grid grid-cols-1 xl:grid-cols-3 gap-6 mb-6">
      <!-- Traffic by Domain (bar chart) -->
      <div class="xl:col-span-2">
        <div class="glass rounded-2xl p-6">
          <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">
            Traffic by Domain
          </h3>
          <template v-if="analytics.loading">
            <div v-for="i in 5" :key="i" class="skeleton w-full h-8 mb-2 rounded-lg"></div>
          </template>
          <template v-else-if="analytics.trafficByDomain.length === 0">
            <div class="text-sm text-center py-12" :style="{ color: 'var(--text-muted)' }">No traffic data available</div>
          </template>
          <template v-else>
            <div class="space-y-3">
              <div v-for="domain in analytics.trafficByDomain" :key="domain.domain" class="group">
                <div class="flex items-center justify-between mb-1">
                  <span class="text-sm font-medium truncate max-w-[60%]" :style="{ color: 'var(--text-primary)' }">
                    {{ domain.domain }}
                  </span>
                  <span class="text-xs font-semibold" :style="{ color: 'var(--primary)' }">
                    {{ formatNumber(domain.requests || domain.hits || 0) }}
                  </span>
                </div>
                <div class="w-full h-6 rounded-lg overflow-hidden" :style="{ background: 'rgba(var(--border-rgb), 0.2)' }">
                  <div
                    class="h-full rounded-lg transition-all duration-700 ease-out relative overflow-hidden"
                    :style="{
                      width: trafficBarWidth(domain.requests || domain.hits || 0) + '%',
                      background: 'linear-gradient(90deg, var(--primary), rgba(var(--primary-rgb), 0.7))',
                      minWidth: '4px'
                    }"
                  >
                    <div class="absolute inset-0 opacity-20" style="background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent)"></div>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- Response Codes (donut chart) -->
      <div>
        <div class="glass rounded-2xl p-6 h-full">
          <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">
            Response Codes
          </h3>
          <template v-if="analytics.loading">
            <div class="flex items-center justify-center py-8">
              <div class="skeleton w-40 h-40 rounded-full"></div>
            </div>
          </template>
          <template v-else-if="responseCodeGroups.length === 0">
            <div class="text-sm text-center py-12" :style="{ color: 'var(--text-muted)' }">No data available</div>
          </template>
          <template v-else>
            <!-- SVG Donut Chart -->
            <div class="flex flex-col items-center">
              <div class="relative w-44 h-44 mb-4">
                <svg viewBox="0 0 36 36" class="w-full h-full -rotate-90">
                  <circle
                    v-for="(seg, i) in donutSegments"
                    :key="i"
                    cx="18" cy="18" r="15.9"
                    fill="none"
                    :stroke="seg.color"
                    stroke-width="3.5"
                    :stroke-dasharray="seg.dashArray"
                    :stroke-dashoffset="seg.offset"
                    class="transition-all duration-700"
                  />
                </svg>
                <!-- Center label -->
                <div class="absolute inset-0 flex flex-col items-center justify-center">
                  <span class="text-xl font-bold" :style="{ color: 'var(--text-primary)' }">
                    {{ formatNumber(totalResponseCodes) }}
                  </span>
                  <span class="text-[10px]" :style="{ color: 'var(--text-muted)' }">total</span>
                </div>
              </div>
              <!-- Legend -->
              <div class="grid grid-cols-2 gap-x-4 gap-y-2 w-full">
                <div v-for="group in responseCodeGroups" :key="group.label" class="flex items-center gap-2">
                  <span class="w-3 h-3 rounded-sm flex-shrink-0" :style="{ background: group.color }"></span>
                  <span class="text-xs" :style="{ color: 'var(--text-muted)' }">{{ group.label }}</span>
                  <span class="text-xs font-semibold ml-auto" :style="{ color: 'var(--text-primary)' }">
                    {{ group.pct }}%
                  </span>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- Bandwidth History (line chart) -->
    <div class="glass rounded-2xl p-6 mb-6">
      <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">
        Bandwidth Over Time
      </h3>
      <template v-if="analytics.loading">
        <div class="skeleton w-full h-48 rounded-lg"></div>
      </template>
      <template v-else-if="analytics.bandwidthHistory.length === 0">
        <div class="h-48 flex items-center justify-center">
          <span class="text-sm" :style="{ color: 'var(--text-muted)' }">No bandwidth data available</span>
        </div>
      </template>
      <template v-else>
        <!-- SVG Line Chart -->
        <div class="relative h-48 w-full">
          <svg class="w-full h-full" :viewBox="`0 0 ${bwChartWidth} ${bwChartHeight}`" preserveAspectRatio="none">
            <!-- Grid lines -->
            <line
              v-for="i in 4"
              :key="'grid-' + i"
              :x1="0"
              :y1="(bwChartHeight / 4) * i"
              :x2="bwChartWidth"
              :y2="(bwChartHeight / 4) * i"
              stroke="rgba(var(--border-rgb), 0.2)"
              stroke-width="0.5"
            />
            <!-- Area fill -->
            <polygon
              :points="bwAreaPoints"
              :fill="`url(#bw-gradient)`"
            />
            <!-- Line -->
            <polyline
              :points="bwLinePoints"
              fill="none"
              stroke="var(--primary)"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              vector-effect="non-scaling-stroke"
            />
            <!-- Gradient definition -->
            <defs>
              <linearGradient id="bw-gradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="var(--primary)" stop-opacity="0.25"/>
                <stop offset="100%" stop-color="var(--primary)" stop-opacity="0.02"/>
              </linearGradient>
            </defs>
          </svg>
          <!-- Hover dots -->
          <div class="absolute inset-0 flex items-end">
            <div
              v-for="(point, i) in analytics.bandwidthHistory"
              :key="i"
              class="flex-1 h-full relative group cursor-pointer"
            >
              <!-- Tooltip -->
              <div class="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block z-10">
                <div class="glass-strong rounded px-2 py-1 text-[10px] whitespace-nowrap" :style="{ color: 'var(--text-primary)' }">
                  {{ point.date || point.label || '' }}: {{ formatBytes(point.bytes || point.value || 0) }}
                </div>
              </div>
            </div>
          </div>
        </div>
        <!-- X-axis labels -->
        <div class="flex justify-between mt-2">
          <span
            v-for="label in bwXLabels"
            :key="label"
            class="text-[10px]"
            :style="{ color: 'var(--text-muted)' }"
          >{{ label }}</span>
        </div>
      </template>
    </div>

    <div class="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-6">
      <!-- Top Pages Table -->
      <div class="glass rounded-2xl p-6">
        <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">
          Top Pages
        </h3>
        <template v-if="analytics.loading">
          <div v-for="i in 5" :key="i" class="skeleton w-full h-10 mb-2 rounded-lg"></div>
        </template>
        <template v-else-if="analytics.topPages.length === 0">
          <div class="text-sm text-center py-8" :style="{ color: 'var(--text-muted)' }">No page data available</div>
        </template>
        <template v-else>
          <div class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
                  <th class="text-left py-2 px-2 text-xs font-semibold uppercase tracking-wider" :style="{ color: 'var(--text-muted)' }">URL</th>
                  <th class="text-right py-2 px-2 text-xs font-semibold uppercase tracking-wider" :style="{ color: 'var(--text-muted)' }">Hits</th>
                  <th class="text-right py-2 px-2 text-xs font-semibold uppercase tracking-wider hidden sm:table-cell" :style="{ color: 'var(--text-muted)' }">Bandwidth</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(page, i) in analytics.topPages.slice(0, 10)"
                  :key="i"
                  :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.15)' }"
                >
                  <td class="py-2.5 px-2 truncate max-w-[250px]" :style="{ color: 'var(--text-primary)' }">
                    <span class="font-mono text-xs">{{ page.path || page.url || '-' }}</span>
                  </td>
                  <td class="py-2.5 px-2 text-right font-semibold" :style="{ color: 'var(--primary)' }">
                    {{ formatNumber(page.hits || 0) }}
                  </td>
                  <td class="py-2.5 px-2 text-right hidden sm:table-cell" :style="{ color: 'var(--text-muted)' }">
                    {{ formatBytes(page.bandwidth || page.bytes || 0) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </div>

      <!-- Top Referrers Table -->
      <div class="glass rounded-2xl p-6">
        <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">
          Top Referrers
        </h3>
        <template v-if="analytics.loading">
          <div v-for="i in 5" :key="i" class="skeleton w-full h-10 mb-2 rounded-lg"></div>
        </template>
        <template v-else-if="analytics.topReferrers.length === 0">
          <div class="text-sm text-center py-8" :style="{ color: 'var(--text-muted)' }">No referrer data available</div>
        </template>
        <template v-else>
          <div class="space-y-2">
            <div
              v-for="(ref, i) in analytics.topReferrers.slice(0, 10)"
              :key="i"
              class="flex items-center gap-3 p-3 rounded-xl transition-colors"
              :style="{ background: 'rgba(var(--border-rgb), 0.08)' }"
            >
              <div
                class="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 text-xs font-bold"
                :style="{ background: 'rgba(var(--primary-rgb), 0.12)', color: 'var(--primary)' }"
              >
                {{ i + 1 }}
              </div>
              <div class="flex-1 min-w-0">
                <span class="text-sm font-medium truncate block" :style="{ color: 'var(--text-primary)' }">
                  {{ ref.source || ref.referrer || ref.url || 'Direct' }}
                </span>
              </div>
              <span class="text-sm font-semibold flex-shrink-0" :style="{ color: 'var(--primary)' }">
                {{ formatNumber(ref.count || ref.hits || 0) }}
              </span>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAnalyticsStore } from '@/stores/analytics'

const analytics = useAnalyticsStore()

const selectedPeriod = ref('7d')

const datePresets = [
  { label: 'Today', value: '1d' },
  { label: '7 Days', value: '7d' },
  { label: '30 Days', value: '30d' }
]

// -----------------------------------------------------------------------
// Overview cards
// -----------------------------------------------------------------------
const overviewCards = computed(() => {
  const o = analytics.overview || {}
  return [
    {
      label: 'Total Requests',
      value: formatNumber(o.total_requests || 0),
      sub: periodLabel.value,
      icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
      bgColor: 'rgba(var(--primary-rgb), 0.12)'
    },
    {
      label: 'Unique Visitors',
      value: formatNumber(o.unique_visitors || 0),
      sub: periodLabel.value,
      icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
      bgColor: 'rgba(34, 197, 94, 0.12)'
    },
    {
      label: 'Bandwidth Used',
      value: formatBytes(o.bandwidth_bytes || o.bandwidth || 0),
      sub: periodLabel.value,
      icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--warning)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
      bgColor: 'rgba(245, 158, 11, 0.12)'
    },
    {
      label: 'Avg Response Time',
      value: (o.avg_response_time || 0) + 'ms',
      sub: periodLabel.value,
      icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#6ee7b7" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
      bgColor: 'rgba(110, 231, 183, 0.12)'
    }
  ]
})

const periodLabel = computed(() => {
  const map = { '1d': 'Today', '7d': 'Last 7 days', '30d': 'Last 30 days' }
  return map[selectedPeriod.value] || selectedPeriod.value
})

// -----------------------------------------------------------------------
// Traffic by domain: bar width helper
// -----------------------------------------------------------------------
const maxTraffic = computed(() => {
  if (!analytics.trafficByDomain.length) return 1
  return Math.max(...analytics.trafficByDomain.map(d => d.requests || d.hits || 0), 1)
})

function trafficBarWidth(val) {
  return Math.max(2, (val / maxTraffic.value) * 100)
}

// -----------------------------------------------------------------------
// Response codes donut
// -----------------------------------------------------------------------
const codeColors = {
  '2xx': 'var(--success)',
  '3xx': 'var(--primary)',
  '4xx': 'var(--warning)',
  '5xx': 'var(--error)'
}

const responseCodeGroups = computed(() => {
  const codes = analytics.responseCodes
  if (!codes || codes.length === 0) return []
  const total = codes.reduce((sum, c) => sum + (c.count || c.hits || 0), 0) || 1
  return codes.map(c => ({
    label: c.code || c.group || c.label || 'Unknown',
    count: c.count || c.hits || 0,
    pct: Math.round(((c.count || c.hits || 0) / total) * 100),
    color: codeColors[c.code || c.group || ''] || 'var(--text-muted)'
  }))
})

const totalResponseCodes = computed(() => {
  return (analytics.responseCodes || []).reduce((sum, c) => sum + (c.count || c.hits || 0), 0)
})

const donutSegments = computed(() => {
  const groups = responseCodeGroups.value
  if (!groups.length) return []
  const total = groups.reduce((sum, g) => sum + g.count, 0) || 1
  const circumference = 100 // SVG stroke-dasharray percentage
  let currentOffset = 0
  return groups.map(g => {
    const pct = (g.count / total) * circumference
    const segment = {
      color: g.color,
      dashArray: `${pct} ${circumference - pct}`,
      offset: -currentOffset
    }
    currentOffset += pct
    return segment
  })
})

// -----------------------------------------------------------------------
// Bandwidth history line chart
// -----------------------------------------------------------------------
const bwChartWidth = 800
const bwChartHeight = 200

const maxBandwidth = computed(() => {
  if (!analytics.bandwidthHistory.length) return 1
  return Math.max(...analytics.bandwidthHistory.map(p => p.bytes || p.value || 0), 1)
})

const bwLinePoints = computed(() => {
  const data = analytics.bandwidthHistory
  if (!data.length) return ''
  const stepX = bwChartWidth / Math.max(data.length - 1, 1)
  return data.map((p, i) => {
    const x = i * stepX
    const y = bwChartHeight - ((p.bytes || p.value || 0) / maxBandwidth.value) * (bwChartHeight * 0.9)
    return `${x},${y}`
  }).join(' ')
})

const bwAreaPoints = computed(() => {
  const data = analytics.bandwidthHistory
  if (!data.length) return ''
  const stepX = bwChartWidth / Math.max(data.length - 1, 1)
  const lineCoords = data.map((p, i) => {
    const x = i * stepX
    const y = bwChartHeight - ((p.bytes || p.value || 0) / maxBandwidth.value) * (bwChartHeight * 0.9)
    return `${x},${y}`
  })
  return `0,${bwChartHeight} ${lineCoords.join(' ')} ${bwChartWidth},${bwChartHeight}`
})

const bwXLabels = computed(() => {
  const data = analytics.bandwidthHistory
  if (!data.length) return []
  if (data.length <= 7) return data.map(p => p.date || p.label || '')
  // Show ~5 evenly spaced labels
  const step = Math.floor(data.length / 5)
  const labels = []
  for (let i = 0; i < data.length; i += step) {
    labels.push(data[i].date || data[i].label || '')
  }
  if (labels.length < 5) labels.push(data[data.length - 1].date || data[data.length - 1].label || '')
  return labels
})

// -----------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------
function formatNumber(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return parseFloat((bytes / Math.pow(1024, i)).toFixed(1)) + ' ' + sizes[i]
}

// -----------------------------------------------------------------------
// Actions
// -----------------------------------------------------------------------
function setPeriod(period) {
  selectedPeriod.value = period
  refreshData()
}

async function refreshData() {
  await analytics.fetchAll(selectedPeriod.value)
}

onMounted(() => {
  refreshData()
})
</script>
