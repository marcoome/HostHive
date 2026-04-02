<template>
  <Modal :modelValue="modelValue" @update:modelValue="v => emit('update:modelValue', v)" :title="title" size="sm">
    <p class="text-sm text-text-muted">{{ message }}</p>

    <template #actions>
      <button class="btn-secondary" @click="cancel">Cancel</button>
      <button :class="destructive ? 'btn-danger' : 'btn-primary'" @click="confirm">
        {{ confirmText }}
      </button>
    </template>
  </Modal>
</template>

<script setup>
import Modal from './Modal.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: 'Are you sure?' },
  message: { type: String, default: 'This action cannot be undone.' },
  confirmText: { type: String, default: 'Confirm' },
  destructive: { type: Boolean, default: true }
})

const emit = defineEmits(['update:modelValue', 'confirm', 'cancel'])

function cancel() {
  emit('update:modelValue', false)
  emit('cancel')
}

function confirm() {
  emit('update:modelValue', false)
  emit('confirm')
}
</script>
