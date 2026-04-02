import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

const commandPaletteOpen = ref(false)
const shortcutsModalOpen = ref(false)
const pendingKey = ref(null)
const pendingTimer = ref(null)

export function useKeyboardShortcuts() {
  const router = useRouter()

  function isInputFocused() {
    const el = document.activeElement
    if (!el) return false
    const tag = el.tagName.toLowerCase()
    return tag === 'input' || tag === 'textarea' || tag === 'select' || el.isContentEditable
  }

  function handleKeyDown(e) {
    // Cmd/Ctrl+K — always intercept for command palette
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault()
      commandPaletteOpen.value = !commandPaletteOpen.value
      return
    }

    // Escape — close modals
    if (e.key === 'Escape') {
      commandPaletteOpen.value = false
      shortcutsModalOpen.value = false
      return
    }

    // Don't process other shortcuts if typing in an input or command palette is open
    if (isInputFocused() || commandPaletteOpen.value) return

    const key = e.key.toLowerCase()

    // Two-key sequences
    if (pendingKey.value) {
      clearTimeout(pendingTimer.value)
      const combo = `${pendingKey.value} ${key}`
      pendingKey.value = null

      const twoKeyShortcuts = {
        'g d': '/dashboard',
        'g w': '/domains',
        'g b': '/databases',
        'g e': '/email',
        'g f': '/files',
        'g s': '/server',
        'g m': '/monitoring',
        'g i': '/integrations',
        'g a': '/ai'
      }

      if (twoKeyShortcuts[combo]) {
        e.preventDefault()
        router.push(twoKeyShortcuts[combo])
        return
      }

      // n-key actions emit custom events
      const actionShortcuts = {
        'n d': 'new-domain',
        'n b': 'new-database',
        'n e': 'new-email'
      }

      if (actionShortcuts[combo]) {
        e.preventDefault()
        window.dispatchEvent(new CustomEvent('open-modal', { detail: actionShortcuts[combo] }))
        return
      }
      return
    }

    // Start two-key sequence
    if (key === 'g' || key === 'n') {
      pendingKey.value = key
      pendingTimer.value = setTimeout(() => {
        pendingKey.value = null
      }, 500)
      return
    }

    // Single-key shortcuts
    if (key === '?') {
      e.preventDefault()
      shortcutsModalOpen.value = true
      return
    }

    if (key === '/') {
      e.preventDefault()
      const searchInput = document.querySelector('[data-global-search]')
      if (searchInput) searchInput.focus()
      return
    }
  }

  onMounted(() => {
    document.addEventListener('keydown', handleKeyDown)
  })

  onUnmounted(() => {
    document.removeEventListener('keydown', handleKeyDown)
    if (pendingTimer.value) clearTimeout(pendingTimer.value)
  })

  return {
    commandPaletteOpen,
    shortcutsModalOpen
  }
}
