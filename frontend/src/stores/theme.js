import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

export const useThemeStore = defineStore('theme', () => {
  const stored = localStorage.getItem('hosthive_theme')
  const theme = ref(stored || 'dark')

  const isDark = computed(() => theme.value === 'dark')

  function applyTheme(t) {
    const el = document.documentElement
    el.classList.remove('dark', 'light')
    el.classList.add(t)
    el.style.colorScheme = t
  }

  function toggleTheme() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
  }

  watch(theme, (val) => {
    localStorage.setItem('hosthive_theme', val)
    applyTheme(val)
  }, { immediate: true })

  return { theme, isDark, toggleTheme }
})
