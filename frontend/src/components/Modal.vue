<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="modelValue"
        class="fixed inset-0 z-50 flex items-center justify-center p-4"
        @keydown.escape="close"
      >
        <!-- Overlay -->
        <div class="absolute inset-0 bg-black/60 backdrop-blur-sm" @click="close" />

        <!-- Modal -->
        <div
          class="relative bg-surface border border-border rounded-lg shadow-2xl w-full"
          :class="sizeClass"
        >
          <!-- Header -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-border">
            <h3 class="text-lg font-semibold text-text-primary">{{ title }}</h3>
            <button
              class="p-1 rounded hover:bg-background text-text-muted hover:text-text-primary transition-colors"
              @click="close"
            >
              &#10005;
            </button>
          </div>

          <!-- Body -->
          <div class="px-6 py-4">
            <slot />
          </div>

          <!-- Actions -->
          <div v-if="$slots.actions" class="flex items-center justify-end gap-3 px-6 py-4 border-t border-border">
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
  const sizes = {
    sm: 'max-w-md',
    md: 'max-w-lg',
    lg: 'max-w-2xl',
    xl: 'max-w-4xl'
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
