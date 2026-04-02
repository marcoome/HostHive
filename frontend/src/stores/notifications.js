import { defineStore } from 'pinia'
import { ref } from 'vue'

let nextId = 0

export const useNotificationsStore = defineStore('notifications', () => {
  const toasts = ref([])

  function add(type, message, duration = 5000) {
    const id = nextId++
    toasts.value.push({ id, type, message })
    if (duration > 0) {
      setTimeout(() => remove(id), duration)
    }
  }

  function remove(id) {
    toasts.value = toasts.value.filter(t => t.id !== id)
  }

  function success(message, duration) {
    add('success', message, duration)
  }

  function error(message, duration) {
    add('error', message, duration)
  }

  function warning(message, duration) {
    add('warning', message, duration)
  }

  function info(message, duration) {
    add('info', message, duration)
  }

  return { toasts, add, remove, success, error, warning, info }
})
