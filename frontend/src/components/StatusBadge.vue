<template>
  <span
    class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-badge text-xs font-medium"
    :class="classes"
  >
    <span class="w-1.5 h-1.5 rounded-full" :class="dotClass"></span>
    {{ label }}
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: { type: String, required: true },
  label: { type: String, default: '' }
})

const classes = computed(() => {
  const map = {
    active: 'bg-success/10 text-success',
    running: 'bg-success/10 text-success',
    online: 'bg-success/10 text-success',
    enabled: 'bg-success/10 text-success',
    inactive: 'bg-text-muted/10 text-text-muted',
    stopped: 'bg-error/10 text-error',
    offline: 'bg-error/10 text-error',
    disabled: 'bg-text-muted/10 text-text-muted',
    error: 'bg-error/10 text-error',
    warning: 'bg-warning/10 text-warning',
    pending: 'bg-warning/10 text-warning'
  }
  return map[props.status] || map.inactive
})

const dotClass = computed(() => {
  const map = {
    active: 'bg-success',
    running: 'bg-success',
    online: 'bg-success',
    enabled: 'bg-success',
    inactive: 'bg-text-muted',
    stopped: 'bg-error',
    offline: 'bg-error',
    disabled: 'bg-text-muted',
    error: 'bg-error',
    warning: 'bg-warning',
    pending: 'bg-warning'
  }
  return map[props.status] || map.inactive
})
</script>
