<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="modelValue"
        class="fixed inset-0 z-50 flex items-end sm:items-center justify-center sm:p-4"
        @keydown.escape="close"
      >
        <!-- Overlay -->
        <div class="absolute inset-0 bg-black/60 backdrop-blur-sm" @click="close" />

        <!-- Modal -->
        <div
          class="relative bg-surface border border-border shadow-2xl w-full max-h-[100dvh] sm:max-h-[90vh] flex flex-col rounded-t-2xl sm:rounded-lg"
          :class="sizeClass"
        >
          <!-- Header -->
          <div class="flex items-center justify-between px-4 sm:px-6 py-4 border-b border-border flex-shrink-0">
            <h3 class="text-lg font-semibold text-text-primary">{{ title }}</h3>
            <button
              class="p-2 rounded hover:bg-background text-text-muted hover:text-text-primary transition-colors min-w-[44px] min-h-[44px] flex items-center justify-center"
              @click="close"
            >
              &#10005;
            </button>
          </div>

          <!-- Body -->
          <div class="px-4 sm:px-6 py-4 overflow-y-auto flex-1">
            <slot />
          </div>

          <!-- Actions -->
          <div v-if="$slots.actions" class="flex items-center justify-end gap-3 px-4 sm:px-6 py-4 border-t border-border flex-shrink-0 flex-wrap">
            <slot name="actions" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
  size: { type: String, default: 'md' }
})

const emit = defineEmits(['update:modelValue'])

const sizeClass = computed(() => {
  // On mobile (<640px), modal is full-width sheet from bottom via CSS above
  // On sm+, apply max-width constraints
  const sizes = {
    sm: 'sm:max-w-md',
    md: 'sm:max-w-lg',
    lg: 'sm:max-w-2xl',
    xl: 'sm:max-w-4xl'
  }
  return sizes[props.size] || sizes.md
})

function close() {
  emit('update:modelValue', false)
}

watch(() => props.modelValue, (val) => {
  document.body.style.overflow = val ? 'hidden' : ''
})
</script>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>
