<template>
  <Teleport to="body">
    <Transition name="palette">
      <div
        v-if="modelValue"
        class="palette-overlay"
        @click.self="close"
      >
        <div class="palette-container" @click.stop>
          <!-- Search input -->
          <div class="palette-header">
            <svg class="palette-search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8"/>
              <line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
            <input
              ref="searchInput"
              v-model="query"
              :placeholder="$t('command_palette.placeholder')"
              class="palette-input"
              @keydown.down.prevent="moveSelection(1)"
              @keydown.up.prevent="moveSelection(-1)"
              @keydown.enter.prevent="executeSelected"
              @keydown.escape.prevent="close"
            />
            <kbd class="palette-kbd">ESC</kbd>
          </div>

          <!-- Results -->
          <div class="palette-results" ref="resultsRef">
            <template v-if="filteredItems.length === 0">
              <div class="palette-empty">{{ $t('command_palette.no_results') }}</div>
            </template>
            <template v-else>
              <template v-for="(group, groupIndex) in groupedResults" :key="group.title">
                <div class="palette-group-title">{{ group.title }}</div>
                <div
                  v-for="(item, itemIndex) in group.items"
                  :key="item.id"
                  class="palette-item"
                  :class="{ 'palette-item-active': getGlobalIndex(groupIndex, itemIndex) === selectedIndex }"
                  @click="executeItem(item)"
                  @mouseenter="selectedIndex = getGlobalIndex(groupIndex, itemIndex)"
                  :ref="el => setItemRef(getGlobalIndex(groupIndex, itemIndex), el)"
                >
                  <!-- v-html safe: icon is a hardcoded HTML entity from trusted source, not user input -->
                  <span class="palette-item-icon" v-html="item.icon"></span>
                  <div class="palette-item-text">
                    <span class="palette-item-title">{{ item.title }}</span>
                    <span v-if="item.subtitle" class="palette-item-subtitle">{{ item.subtitle }}</span>
                  </div>
                  <kbd v-if="item.shortcut" class="palette-item-shortcut">{{ item.shortcut }}</kbd>
                </div>
              </template>
            </template>
          </div>

          <!-- Footer -->
          <div class="palette-footer">
            <span><kbd>&uarr;</kbd><kbd>&darr;</kbd> navigate</span>
            <span><kbd>&crarr;</kbd> select</span>
            <span><kbd>esc</kbd> close</span>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  modelValue: Boolean
})

const emit = defineEmits(['update:modelValue'])

const { t } = useI18n()
const router = useRouter()
const query = ref('')
const selectedIndex = ref(0)
const searchInput = ref(null)
const resultsRef = ref(null)
const itemRefs = ref({})

// Recent pages from sessionStorage
const recentPages = ref(JSON.parse(sessionStorage.getItem('hosthive_recent_pages') || '[]'))

function trackPage(path, title) {
  const pages = recentPages.value.filter(p => p.path !== path)
  pages.unshift({ path, title })
  recentPages.value = pages.slice(0, 5)
  sessionStorage.setItem('hosthive_recent_pages', JSON.stringify(recentPages.value))
}

// All command items
const allItems = computed(() => {
  const items = []

  // Navigation items
  const navItems = [
    { id: 'nav-dashboard', title: t('nav.dashboard'), icon: '&#9632;', path: '/dashboard', shortcut: 'G D', section: 'navigation' },
    { id: 'nav-domains', title: t('nav.domains'), icon: '&#9673;', path: '/domains', shortcut: 'G W', section: 'navigation' },
    { id: 'nav-databases', title: t('nav.databases'), icon: '&#9707;', path: '/databases', shortcut: 'G B', section: 'navigation' },
    { id: 'nav-email', title: t('nav.email'), icon: '&#9993;', path: '/email', shortcut: 'G E', section: 'navigation' },
    { id: 'nav-dns', title: t('nav.dns'), icon: '&#9881;', path: '/dns', section: 'navigation' },
    { id: 'nav-ftp', title: t('nav.ftp'), icon: '&#8645;', path: '/ftp', section: 'navigation' },
    { id: 'nav-cron', title: t('nav.cron'), icon: '&#8635;', path: '/cron', section: 'navigation' },
    { id: 'nav-ssl', title: t('nav.ssl'), icon: '&#9919;', path: '/ssl', section: 'navigation' },
    { id: 'nav-backups', title: t('nav.backups'), icon: '&#9744;', path: '/backups', section: 'navigation' },
    { id: 'nav-files', title: t('nav.files'), icon: '&#9782;', path: '/files', shortcut: 'G F', section: 'navigation' },
    { id: 'nav-server', title: t('nav.server'), icon: '&#9874;', path: '/server', shortcut: 'G S', section: 'navigation' },
    { id: 'nav-apps', title: t('nav.apps', 'App Store'), icon: '&#9881;', path: '/apps', section: 'navigation' },
    { id: 'nav-docker', title: t('nav.docker'), icon: '&#9830;', path: '/docker', section: 'navigation' },
    { id: 'nav-wordpress', title: t('nav.wordpress'), icon: '&#9998;', path: '/wordpress', section: 'navigation' },
    { id: 'nav-ai', title: t('nav.ai'), icon: '&#10024;', path: '/ai', shortcut: 'G A', section: 'navigation' },
    { id: 'nav-monitoring', title: t('nav.monitoring'), icon: '&#9729;', path: '/monitoring', shortcut: 'G M', section: 'navigation' },
    { id: 'nav-integrations', title: t('nav.integrations'), icon: '&#10731;', path: '/integrations', shortcut: 'G I', section: 'navigation' },
    { id: 'nav-settings', title: t('nav.settings'), icon: '&#9881;', path: '/settings', section: 'navigation' }
  ]
  items.push(...navItems)

  // Action items
  const actionItems = [
    { id: 'act-new-domain', title: t('domains.add_domain'), icon: '&#43;', action: 'new-domain', shortcut: 'N D', section: 'actions' },
    { id: 'act-new-database', title: t('databases.add_database'), icon: '&#43;', action: 'new-database', shortcut: 'N B', section: 'actions' },
    { id: 'act-new-email', title: t('email.add_account'), icon: '&#43;', action: 'new-email', shortcut: 'N E', section: 'actions' },
    { id: 'act-new-ftp', title: t('ftp.add_account'), icon: '&#43;', action: 'new-ftp', section: 'actions' },
    { id: 'act-new-cron', title: t('cron.add_job'), icon: '&#43;', action: 'new-cron', section: 'actions' },
    { id: 'act-backup', title: t('backups.create_backup'), icon: '&#9744;', action: 'create-backup', section: 'actions' },
    { id: 'act-ssl', title: t('ssl.issue_certificate'), icon: '&#9919;', action: 'issue-ssl', section: 'actions' },
    { id: 'act-scan', title: 'Run Security Scan', icon: '&#9888;', action: 'security-scan', section: 'actions' }
  ]
  items.push(...actionItems)

  // Recent pages
  recentPages.value.forEach((page, i) => {
    items.push({
      id: `recent-${i}`,
      title: page.title,
      subtitle: page.path,
      icon: '&#8635;',
      path: page.path,
      section: 'recent'
    })
  })

  return items
})

const filteredItems = computed(() => {
  if (!query.value.trim()) return allItems.value
  const q = query.value.toLowerCase()
  return allItems.value.filter(item =>
    item.title.toLowerCase().includes(q) ||
    (item.subtitle && item.subtitle.toLowerCase().includes(q)) ||
    (item.path && item.path.toLowerCase().includes(q))
  )
})

const groupedResults = computed(() => {
  const groups = {}
  const sectionLabels = {
    recent: t('command_palette.recent'),
    navigation: t('command_palette.navigation'),
    actions: t('command_palette.actions'),
    domains: t('command_palette.domains'),
    databases: t('command_palette.databases')
  }
  const order = ['recent', 'navigation', 'actions', 'domains', 'databases']

  for (const item of filteredItems.value) {
    const section = item.section || 'navigation'
    if (!groups[section]) {
      groups[section] = { title: sectionLabels[section] || section, items: [] }
    }
    groups[section].items.push(item)
  }

  return order.filter(k => groups[k]).map(k => groups[k])
})

function getGlobalIndex(groupIndex, itemIndex) {
  let idx = 0
  for (let g = 0; g < groupIndex; g++) {
    idx += groupedResults.value[g].items.length
  }
  return idx + itemIndex
}

function setItemRef(index, el) {
  if (el) itemRefs.value[index] = el
}

function moveSelection(delta) {
  const total = filteredItems.value.length
  if (total === 0) return
  selectedIndex.value = (selectedIndex.value + delta + total) % total
  nextTick(() => {
    const el = itemRefs.value[selectedIndex.value]
    if (el) el.scrollIntoView({ block: 'nearest' })
  })
}

function executeSelected() {
  const item = filteredItems.value[selectedIndex.value]
  if (item) executeItem(item)
}

function executeItem(item) {
  close()
  if (item.path) {
    trackPage(item.path, item.title)
    router.push(item.path)
  } else if (item.action) {
    window.dispatchEvent(new CustomEvent('open-modal', { detail: item.action }))
  }
}

function close() {
  emit('update:modelValue', false)
}

// Reset state when opening
watch(() => props.modelValue, (val) => {
  if (val) {
    query.value = ''
    selectedIndex.value = 0
    itemRefs.value = {}
    nextTick(() => {
      searchInput.value?.focus()
    })
  }
})

// Reset selection on query change
watch(query, () => {
  selectedIndex.value = 0
})
</script>

<style scoped>
.palette-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 15vh;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.palette-container {
  width: 100%;
  max-width: 640px;
  background: rgba(var(--surface-rgb, 30, 30, 46), 0.85);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(var(--border-rgb, 255, 255, 255), 0.15);
  border-radius: 16px;
  box-shadow:
    0 25px 50px rgba(0, 0, 0, 0.4),
    0 0 0 1px rgba(255, 255, 255, 0.05) inset;
  overflow: hidden;
}

.palette-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(var(--border-rgb, 255, 255, 255), 0.1);
}

.palette-search-icon {
  flex-shrink: 0;
  color: var(--text-muted, #999);
}

.palette-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  font-size: 1rem;
  color: var(--text-primary, #fff);
  font-family: inherit;
}

.palette-input::placeholder {
  color: var(--text-muted, #666);
}

.palette-kbd {
  font-size: 0.7rem;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(var(--surface-rgb, 255, 255, 255), 0.1);
  color: var(--text-muted, #999);
  border: 1px solid rgba(var(--border-rgb, 255, 255, 255), 0.1);
  font-family: inherit;
}

.palette-results {
  max-height: 400px;
  overflow-y: auto;
  padding: 8px;
}

.palette-results::-webkit-scrollbar {
  width: 6px;
}

.palette-results::-webkit-scrollbar-thumb {
  background: rgba(var(--text-muted-rgb, 255, 255, 255), 0.2);
  border-radius: 3px;
}

.palette-group-title {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted, #999);
  padding: 12px 12px 4px;
}

.palette-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.1s ease;
}

.palette-item:hover,
.palette-item-active {
  background: rgba(var(--primary-rgb, 99, 102, 241), 0.15);
}

.palette-item-icon {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1rem;
  color: var(--text-muted, #999);
  flex-shrink: 0;
}

.palette-item-active .palette-item-icon {
  color: var(--primary, #6366f1);
}

.palette-item-text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.palette-item-title {
  font-size: 0.875rem;
  color: var(--text-primary, #fff);
}

.palette-item-subtitle {
  font-size: 0.75rem;
  color: var(--text-muted, #999);
}

.palette-item-shortcut {
  font-size: 0.65rem;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(var(--surface-rgb, 255, 255, 255), 0.08);
  color: var(--text-muted, #999);
  border: 1px solid rgba(var(--border-rgb, 255, 255, 255), 0.08);
  font-family: inherit;
  flex-shrink: 0;
}

.palette-empty {
  padding: 32px;
  text-align: center;
  color: var(--text-muted, #999);
  font-size: 0.875rem;
}

.palette-footer {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 20px;
  border-top: 1px solid rgba(var(--border-rgb, 255, 255, 255), 0.1);
  font-size: 0.7rem;
  color: var(--text-muted, #999);
}

.palette-footer kbd {
  font-size: 0.65rem;
  padding: 1px 5px;
  border-radius: 3px;
  background: rgba(var(--surface-rgb, 255, 255, 255), 0.1);
  border: 1px solid rgba(var(--border-rgb, 255, 255, 255), 0.08);
  font-family: inherit;
  margin-right: 4px;
}

/* Transitions */
.palette-enter-active {
  transition: opacity 0.15s ease;
}
.palette-enter-active .palette-container {
  transition: transform 0.15s ease, opacity 0.15s ease;
}
.palette-leave-active {
  transition: opacity 0.1s ease;
}
.palette-leave-active .palette-container {
  transition: transform 0.1s ease, opacity 0.1s ease;
}
.palette-enter-from {
  opacity: 0;
}
.palette-enter-from .palette-container {
  opacity: 0;
  transform: scale(0.96) translateY(-10px);
}
.palette-leave-to {
  opacity: 0;
}
.palette-leave-to .palette-container {
  opacity: 0;
  transform: scale(0.96) translateY(-10px);
}
</style>
