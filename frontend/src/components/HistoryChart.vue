<template>
  <div
    ref="chartRoot"
    class="history-chart"
    @mousemove="onMouseMove"
    @mouseleave="onMouseLeave"
  >
    <svg
      :width="width"
      :height="height"
      :viewBox="`0 0 ${width} ${height}`"
      preserveAspectRatio="none"
    >
      <defs>
        <!-- Gradient fill per series -->
        <linearGradient
          v-for="(s, si) in normalizedSeries"
          :key="'grad-' + si"
          :id="`hc-grad-${uid}-${si}`"
          x1="0" y1="0" x2="0" y2="1"
        >
          <stop offset="0%" :stop-color="s.color" stop-opacity="0.35" />
          <stop offset="100%" :stop-color="s.color" stop-opacity="0.03" />
        </linearGradient>
      </defs>

      <!-- Horizontal grid lines -->
      <line
        v-for="i in 4"
        :key="'grid-' + i"
        :x1="padL"
        :y1="padT + ((i - 1) / 3) * plotH"
        :x2="width - padR"
        :y2="padT + ((i - 1) / 3) * plotH"
        stroke="var(--border)"
        stroke-opacity="0.25"
        stroke-dasharray="4 4"
      />

      <!-- Y axis labels -->
      <text
        v-for="i in 4"
        :key="'ylabel-' + i"
        :x="padL - 6"
        :y="padT + ((i - 1) / 3) * plotH + 4"
        text-anchor="end"
        class="chart-axis-label"
      >{{ yLabel(i - 1) }}</text>

      <!-- Area fill (only when fill prop is true) -->
      <template v-if="fill">
        <path
          v-for="(s, si) in normalizedSeries"
          :key="'area-' + si"
          :d="areaPath(s.points)"
          :fill="`url(#hc-grad-${uid}-${si})`"
        />
      </template>

      <!-- Lines -->
      <polyline
        v-for="(s, si) in normalizedSeries"
        :key="'line-' + si"
        :points="polylinePoints(s.points)"
        fill="none"
        :stroke="s.color"
        stroke-width="2"
        stroke-linejoin="round"
        stroke-linecap="round"
        vector-effect="non-scaling-stroke"
      />

      <!-- Hover vertical line -->
      <line
        v-if="hoverIndex >= 0"
        :x1="hoverX"
        :y1="padT"
        :x2="hoverX"
        :y2="padT + plotH"
        stroke="var(--text-muted)"
        stroke-opacity="0.4"
        stroke-width="1"
        stroke-dasharray="3 3"
      />

      <!-- Hover dots -->
      <template v-if="hoverIndex >= 0">
        <circle
          v-for="(s, si) in normalizedSeries"
          :key="'dot-' + si"
          v-show="s.points[hoverIndex]"
          :cx="hoverX"
          :cy="s.points[hoverIndex]?.y ?? 0"
          r="4"
          :fill="s.color"
          stroke="var(--surface)"
          stroke-width="2"
        />
      </template>
    </svg>

    <!-- Tooltip -->
    <Transition name="tooltip-fade">
      <div
        v-if="hoverIndex >= 0 && tooltipData"
        class="chart-tooltip glass-strong"
        :style="tooltipStyle"
      >
        <div class="tooltip-time">{{ tooltipData.time }}</div>
        <div
          v-for="(row, ri) in tooltipData.rows"
          :key="ri"
          class="tooltip-row"
        >
          <span class="tooltip-dot" :style="{ background: row.color }"></span>
          <span class="tooltip-label">{{ row.label }}</span>
          <span class="tooltip-value">{{ row.value }}</span>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'

const props = defineProps({
  /** Array of { label, color, data: number[] } */
  series: { type: Array, required: true },
  /** Array of ISO timestamps matching data length */
  timestamps: { type: Array, default: () => [] },
  /** Chart height in px */
  chartHeight: { type: Number, default: 180 },
  /** Whether to draw area fill under the line */
  fill: { type: Boolean, default: true },
  /** Unit suffix for tooltip values (%, MB, etc.) */
  unit: { type: String, default: '' },
  /** Format function for Y axis / tooltip values */
  formatValue: { type: Function, default: null },
  /** Fixed Y max (auto-scales if 0) */
  yMax: { type: Number, default: 0 },
})

const uid = Math.random().toString(36).slice(2, 8)
const chartRoot = ref(null)
const width = ref(600)
const height = computed(() => props.chartHeight)

// Padding
const padL = 48
const padR = 12
const padT = 12
const padB = 4
const plotH = computed(() => height.value - padT - padB)
const plotW = computed(() => width.value - padL - padR)

// Resize observer
let resizeObs = null
onMounted(() => {
  if (chartRoot.value) {
    width.value = chartRoot.value.clientWidth || 600
    resizeObs = new ResizeObserver((entries) => {
      for (const e of entries) {
        width.value = e.contentRect.width || 600
      }
    })
    resizeObs.observe(chartRoot.value)
  }
})
onUnmounted(() => {
  resizeObs?.disconnect()
})

// Compute Y scale
const computedYMax = computed(() => {
  if (props.yMax > 0) return props.yMax
  let max = 0
  for (const s of props.series) {
    for (const v of (s.data || [])) {
      if (v > max) max = v
    }
  }
  // Add 10% headroom and round to a nice number
  if (max === 0) return 100
  const headroom = max * 1.1
  const magnitude = Math.pow(10, Math.floor(Math.log10(headroom)))
  return Math.ceil(headroom / magnitude) * magnitude
})

// Normalize series data into SVG coordinates
const normalizedSeries = computed(() => {
  const yMax = computedYMax.value
  return props.series.map((s) => {
    const data = s.data || []
    const len = data.length
    const points = data.map((val, i) => {
      const x = len <= 1 ? padL + plotW.value / 2 : padL + (i / (len - 1)) * plotW.value
      const y = padT + plotH.value - (Math.min(val, yMax) / yMax) * plotH.value
      return { x, y, raw: val }
    })
    return { label: s.label, color: s.color, points }
  })
})

function polylinePoints(pts) {
  return pts.map((p) => `${p.x},${p.y}`).join(' ')
}

function areaPath(pts) {
  if (pts.length === 0) return ''
  const baseline = padT + plotH.value
  let d = `M ${pts[0].x},${baseline}`
  for (const p of pts) d += ` L ${p.x},${p.y}`
  d += ` L ${pts[pts.length - 1].x},${baseline} Z`
  return d
}

function yLabel(idx) {
  // idx: 0 = top, 3 = bottom
  const yMax = computedYMax.value
  const val = yMax - (idx / 3) * yMax
  if (props.formatValue) return props.formatValue(val)
  if (val >= 1000000000) return (val / 1000000000).toFixed(1) + 'G'
  if (val >= 1000000) return (val / 1000000).toFixed(1) + 'M'
  if (val >= 1000) return (val / 1000).toFixed(1) + 'K'
  return Math.round(val).toString()
}

// Hover / tooltip
const hoverIndex = ref(-1)
const hoverClientX = ref(0)
const hoverX = ref(0)

function onMouseMove(e) {
  if (!chartRoot.value) return
  const rect = chartRoot.value.getBoundingClientRect()
  const mx = e.clientX - rect.left
  hoverClientX.value = e.clientX - rect.left
  // Find closest data index
  const dataLen = props.series[0]?.data?.length || 0
  if (dataLen === 0) { hoverIndex.value = -1; return }
  const relX = (mx - padL) / plotW.value
  const idx = Math.round(relX * (dataLen - 1))
  if (idx < 0 || idx >= dataLen) { hoverIndex.value = -1; return }
  hoverIndex.value = idx
  hoverX.value = dataLen <= 1 ? padL + plotW.value / 2 : padL + (idx / (dataLen - 1)) * plotW.value
}

function onMouseLeave() {
  hoverIndex.value = -1
}

const tooltipData = computed(() => {
  if (hoverIndex.value < 0) return null
  const idx = hoverIndex.value
  const ts = props.timestamps[idx]
  let time = ''
  if (ts) {
    try {
      const d = new Date(ts)
      time = d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    } catch { time = ts }
  }
  const rows = props.series.map((s) => {
    const raw = (s.data || [])[idx] ?? 0
    const formatted = props.formatValue ? props.formatValue(raw) : raw.toFixed(1)
    return { label: s.label, color: s.color, value: formatted + (props.unit ? ' ' + props.unit : '') }
  })
  return { time, rows }
})

const tooltipStyle = computed(() => {
  if (hoverIndex.value < 0) return {}
  const leftPx = hoverClientX.value
  const chartW = width.value
  // Flip tooltip to left side if near right edge
  const flipLeft = leftPx > chartW * 0.7
  return {
    top: '8px',
    [flipLeft ? 'right' : 'left']: flipLeft ? (chartW - leftPx + 12) + 'px' : (leftPx + 12) + 'px',
  }
})
</script>

<style scoped>
.history-chart {
  position: relative;
  width: 100%;
  user-select: none;
  cursor: crosshair;
}

.history-chart svg {
  display: block;
  width: 100%;
  overflow: visible;
}

.chart-axis-label {
  font-size: 10px;
  fill: var(--text-muted);
  font-family: inherit;
}

.chart-tooltip {
  position: absolute;
  z-index: 20;
  padding: 8px 12px;
  border-radius: 10px;
  min-width: 140px;
  pointer-events: none;
}

.tooltip-time {
  font-size: 10px;
  color: var(--text-muted);
  margin-bottom: 4px;
  white-space: nowrap;
}

.tooltip-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-primary);
  line-height: 1.6;
}

.tooltip-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.tooltip-label {
  flex: 1;
  color: var(--text-muted);
  white-space: nowrap;
}

.tooltip-value {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.tooltip-fade-enter-active,
.tooltip-fade-leave-active {
  transition: opacity 0.15s ease;
}
.tooltip-fade-enter-from,
.tooltip-fade-leave-to {
  opacity: 0;
}
</style>
