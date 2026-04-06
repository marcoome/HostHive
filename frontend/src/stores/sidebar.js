import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useSidebarStore = defineStore('sidebar', () => {
  const mobileOpen = ref(false)

  function toggle() {
    mobileOpen.value = !mobileOpen.value
  }

  function open() {
    mobileOpen.value = true
  }

  function close() {
    mobileOpen.value = false
  }

  return { mobileOpen, toggle, open, close }
})
