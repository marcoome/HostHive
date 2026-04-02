<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="modelValue"
        class="shortcuts-overlay"
        @click.self="$emit('update:modelValue', false)"
      >
        <div class="shortcuts-modal">
          <div class="shortcuts-header">
            <h2>{{ $t('shortcuts.title') }}</h2>
            <button class="shortcuts-close" @click="$emit('update:modelValue', false)">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div class="shortcuts-body">
            <!-- Navigation -->
            <div class="shortcuts-section">
              <h3>{{ $t('shortcuts.navigation') }}</h3>
              <div class="shortcuts-grid">
                <div class="shortcut-row">
                  <span class="shortcut-desc">{{ $t('shortcuts.go_to_dashboard') }}</span>
                  <span class="shortcut-keys"><kbd>G</kbd> <kbd>D</kbd></span>
                </div>
                <div class="shortcut-row">
                  <span class="shortcut-desc">{{ $t('shortcuts.go_to_domains') }}</span>
                  <span class="shortcut-keys"><kbd>G</kbd> <kbd>W</kbd></span>
                </div>
                <div class="shortcut-row">
                  <span class="shortcut-desc">{{ $t('shortcuts.go_to_databases') }}</span>
                  <span class="shortcut-keys"><kbd>G</kbd> <kbd>B</kbd></span>
                </div>
                <div class="shortcut-row">
                  <span class="shortcut-desc">{{ $t('shortcuts.go_to_email') }}</span>
                  <span class="shortcut-keys"><kbd>G</kbd> <kbd>E</kbd></span>
                </div>
                <div class="shortcut-row">
                  <span class="shortcut-desc">{{ $t('shortcuts.go_to_files') }}</span>
                  <span class="shortcut-keys"><kbd>G</kbd> <kbd>F</kbd></span>
                </div>
                <div class="shortcut-row">
                  <span class="shortcut-desc">{{ $t('shortcuts.go_to_server') }}</span>
                  <span class="shortcut-keys"><kbd>G</kbd> <kbd>S</kbd></span>
                </div>
                <div class="shortcut-row">
                  <span class="shortcut-desc">{{ $t('shortcuts.go_to_monitoring') }}</span>
                  <span class="shortcut-keys"><kbd>G</kbd> <kbd>M</kbd></span>
                </div>
                <div class="shortcut-row">
                  <span class="shortcut-desc">{{ $t('shortcuts.go_to_integrations') }}</span>
                  <span class="shortcut-keys"><kbd>G</kbd> <kbd>I</kbd></span>
                </div>
                <div class="shortcut-row">
                  <span class="shortcut-desc">{{ $t('shortcuts.go_to_ai') }}</span>
                  <span class="shortcut-keys"><kbd>G</kbd> <kbd>A</kbd></span>
                </div>
              </div>
            </div>

            <!-- Actions -->
            <div class="shortcuts-section">
              <h3>{{ $t('shortcuts.actions') }}</h3>
              <div class="shortcuts-grid">
                <div class="shortcut-row">
                  <span class="shortcut-desc">{{ $t('shortcuts.new_domain') }}</span>
                  <span class="shortcut-keys"><kbd>N</kbd> <kbd>D</kbd></span>
                </div>
                <div class="shortcut-row">
                  <span class="shortcut-desc">{{ $t('shortcuts.new_database') }}</span>
                  <span class="shortcut-keys"><kbd>N</kbd> <kbd>B</kbd></span>
                </div>
                <div class="shortcut-row">
                  <span class="shortcut-desc">{{ $t('shortcuts.new_email') }}</span>
                  <span class="shortcut-keys"><kbd>N</kbd> <kbd>E</kbd></span>
                </div>
              </div>
            </div>

            <!-- General -->
            <div class="shortcuts-section">
              <h3>{{ $t('shortcuts.general') }}</h3>
              <div class="shortcuts-grid">
                <div class="shortcut-row">
                  <span class="shortcut-desc">{{ $t('shortcuts.command_palette') }}</span>
                  <span class="shortcut-keys"><kbd>{{ isMac ? 'Cmd' : 'Ctrl' }}</kbd> <kbd>K</kbd></span>
                </div>
                <div class="shortcut-row">
                  <span class="shortcut-desc">{{ $t('shortcuts.show_shortcuts') }}</span>
                  <span class="shortcut-keys"><kbd>?</kbd></span>
                </div>
                <div class="shortcut-row">
                  <span class="shortcut-desc">{{ $t('shortcuts.focus_search') }}</span>
                  <span class="shortcut-keys"><kbd>/</kbd></span>
                </div>
                <div class="shortcut-row">
                  <span class="shortcut-desc">{{ $t('shortcuts.close_modals') }}</span>
                  <span class="shortcut-keys"><kbd>Esc</kbd></span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed } from 'vue'

defineProps({
  modelValue: Boolean
})

defineEmits(['update:modelValue'])

const isMac = computed(() => navigator.platform.toUpperCase().indexOf('MAC') >= 0)
</script>

<style scoped>
.shortcuts-overlay {
  position: fixed;
  inset: 0;
  z-index: 9998;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}

.shortcuts-modal {
  width: 100%;
  max-width: 600px;
  max-height: 80vh;
  background: rgba(var(--surface-rgb, 30, 30, 46), 0.9);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(var(--border-rgb, 255, 255, 255), 0.15);
  border-radius: 16px;
  box-shadow: 0 25px 50px rgba(0, 0, 0, 0.4);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.shortcuts-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  border-bottom: 1px solid rgba(var(--border-rgb, 255, 255, 255), 0.1);
}

.shortcuts-header h2 {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary, #fff);
  margin: 0;
}

.shortcuts-close {
  padding: 4px;
  border-radius: 6px;
  color: var(--text-muted, #999);
  transition: all 0.15s ease;
  background: none;
  border: none;
  cursor: pointer;
}

.shortcuts-close:hover {
  color: var(--text-primary, #fff);
  background: rgba(var(--surface-rgb, 255, 255, 255), 0.1);
}

.shortcuts-body {
  padding: 16px 24px 24px;
  overflow-y: auto;
}

.shortcuts-section {
  margin-bottom: 20px;
}

.shortcuts-section:last-child {
  margin-bottom: 0;
}

.shortcuts-section h3 {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted, #999);
  margin: 0 0 8px;
}

.shortcuts-grid {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.shortcut-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-radius: 6px;
}

.shortcut-row:hover {
  background: rgba(var(--surface-rgb, 255, 255, 255), 0.05);
}

.shortcut-desc {
  font-size: 0.875rem;
  color: var(--text-primary, #fff);
}

.shortcut-keys {
  display: flex;
  align-items: center;
  gap: 4px;
}

.shortcut-keys kbd {
  display: inline-block;
  padding: 2px 8px;
  font-size: 0.7rem;
  font-family: inherit;
  border-radius: 4px;
  background: rgba(var(--surface-rgb, 255, 255, 255), 0.1);
  color: var(--text-muted, #999);
  border: 1px solid rgba(var(--border-rgb, 255, 255, 255), 0.1);
  min-width: 24px;
  text-align: center;
}

/* Transitions */
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.15s ease;
}
.modal-enter-active .shortcuts-modal,
.modal-leave-active .shortcuts-modal {
  transition: transform 0.15s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
.modal-enter-from .shortcuts-modal {
  transform: scale(0.95);
}
.modal-leave-to .shortcuts-modal {
  transform: scale(0.95);
}
</style>
