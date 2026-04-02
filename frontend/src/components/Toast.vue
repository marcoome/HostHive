<template>
  <div
    class="flex items-start gap-3 px-4 py-3 rounded-lg border shadow-lg min-w-[320px] max-w-md"
    :class="classes"
  >
    <!-- v-html safe: icon is a hardcoded HTML entity from trusted source, not user input -->
    <span class="text-base mt-0.5" v-html="icon"></span>
    <p class="flex-1 text-sm">{{ message }}</p>
    <button
      class="text-current opacity-60 hover:opacity-100 transition-opacity text-xs"
      @click="$emit('dismiss')"
    >
      &#10005;
    </button>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  type: { type: String, default: 'info' },
  message: { type: String, required: true }
})

defineEmits(['dismiss'])

const classes = computed(() => {
  const map = {
    success: 'bg-success/10 border-success/30 text-success',
    error: 'bg-error/10 border-error/30 text-error',
    warning: 'bg-warning/10 border-warning/30 text-warning',
    info: 'bg-primary/10 border-primary/30 text-primary'
  }
  return map[props.type] || map.info
})

const icon = computed(() => {
  const map = {
    success: '&#10003;',
    error: '&#10007;',
    warning: '&#9888;',
    info: '&#8505;'
  }
  return map[props.type] || map.info
})
</script>
