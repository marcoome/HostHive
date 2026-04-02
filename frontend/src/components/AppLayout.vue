<template>
  <div class="min-h-screen animated-bg relative">
    <ParallaxBackground />
    <ImpersonationBanner />
    <AppSidebar />
    <div class="ml-60 relative z-10">
      <AppTopbar />
      <main class="p-6">
        <router-view />
      </main>
    </div>
    <ToastContainer />

    <!-- Command Palette -->
    <CommandPalette v-model="commandPaletteOpen" />

    <!-- Shortcuts Modal -->
    <ShortcutsModal v-model="shortcutsModalOpen" />

    <!-- Floating AI Assistant -->
    <AiAssistant />
  </div>
</template>

<script setup>
import AppSidebar from './AppSidebar.vue'
import AppTopbar from './AppTopbar.vue'
import ToastContainer from './ToastContainer.vue'
import ParallaxBackground from './ParallaxBackground.vue'
import ImpersonationBanner from './ImpersonationBanner.vue'
import CommandPalette from './CommandPalette.vue'
import ShortcutsModal from './ShortcutsModal.vue'
import AiAssistant from './AiAssistant.vue'
import { useThemeStore } from '@/stores/theme'
import { useKeyboardShortcuts } from '@/composables/useKeyboardShortcuts'

// Ensure theme store initializes and applies the theme class
const theme = useThemeStore()

// Initialize keyboard shortcuts
const { commandPaletteOpen, shortcutsModalOpen } = useKeyboardShortcuts()
</script>
