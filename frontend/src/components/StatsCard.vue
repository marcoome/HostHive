<template>
  <div class="card flex items-start gap-4">
    <div
      class="w-10 h-10 rounded-lg flex items-center justify-center text-lg flex-shrink-0"
      :class="iconBg"
    >
      <!-- v-html safe: icon is a hardcoded HTML entity from trusted source, not user input -->
      <span v-html="icon"></span>
    </div>
    <div class="flex-1 min-w-0">
      <p class="text-sm" :style="{ color: 'var(--text-muted)' }">{{ label }}</p>
      <p class="text-2xl font-semibold mt-0.5" :style="{ color: 'var(--text-primary)' }">{{ value }}</p>
      <p v-if="trend" class="text-xs mt-1" :style="{ color: trend > 0 ? 'var(--success)' : 'var(--error)' }">
        {{ trend > 0 ? '&#9650;' : '&#9660;' }} {{ Math.abs(trend) }}%
      </p>
    </div>
  </div>
</template>

<script setup>
defineProps({
  icon: { type: String, default: '&#9632;' },
  iconBg: { type: String, default: 'bg-primary/10 text-primary' },
  label: { type: String, required: true },
  value: { type: [String, Number], required: true },
  trend: { type: Number, default: null }
})
</script>
