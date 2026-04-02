<template>
  <div class="gauge-chart" :style="{ width: size + 'px', height: size + 'px' }">
    <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`">
      <!-- Background circle -->
      <circle
        :cx="center"
        :cy="center"
        :r="radius"
        fill="none"
        :stroke="trackColor"
        :stroke-width="strokeWidth"
        stroke-linecap="round"
      />
      <!-- Value arc -->
      <circle
        :cx="center"
        :cy="center"
        :r="radius"
        fill="none"
        :stroke="gaugeColor"
        :stroke-width="strokeWidth"
        stroke-linecap="round"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="dashOffset"
        :style="{ transition: 'stroke-dashoffset 1s ease, stroke 0.3s ease' }"
        transform-origin="center"
        :transform="`rotate(-90 ${center} ${center})`"
      />
    </svg>
    <div class="gauge-label">
      <span class="gauge-value" :style="{ color: gaugeColor }">{{ animatedValue }}%</span>
      <span class="gauge-text">{{ label }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch, onMounted } from 'vue'

const props = defineProps({
  value: { type: Number, default: 0 },
  label: { type: String, default: '' },
  size: { type: Number, default: 120 },
  strokeWidth: { type: Number, default: 8 }
})

const animatedValue = ref(0)
const center = computed(() => props.size / 2)
const radius = computed(() => (props.size - props.strokeWidth) / 2 - 4)
const circumference = computed(() => 2 * Math.PI * radius.value)
const dashOffset = computed(() => {
  const progress = Math.min(Math.max(animatedValue.value, 0), 100) / 100
  return circumference.value * (1 - progress)
})

const trackColor = computed(() => `rgba(var(--border-rgb), 0.4)`)

const gaugeColor = computed(() => {
  const v = props.value
  if (v < 60) return 'var(--success)'
  if (v < 80) return 'var(--warning)'
  return 'var(--error)'
})

function animateTo(target) {
  const start = animatedValue.value
  const diff = target - start
  const duration = 800
  const startTime = performance.now()

  function tick(now) {
    const elapsed = now - startTime
    const progress = Math.min(elapsed / duration, 1)
    const eased = 1 - Math.pow(1 - progress, 3)
    animatedValue.value = Math.round(start + diff * eased)
    if (progress < 1) requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
}

onMounted(() => {
  animateTo(props.value)
})

watch(() => props.value, (val) => {
  animateTo(val)
})
</script>

<style scoped>
.gauge-chart {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.gauge-label {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.gauge-value {
  font-size: 1.25rem;
  font-weight: 700;
  line-height: 1;
}

.gauge-text {
  font-size: 0.625rem;
  color: var(--text-muted);
  margin-top: 2px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
</style>
