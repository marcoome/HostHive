<template>
  <header class="h-[60px] glass-strong flex items-center justify-between px-6 relative z-20">
    <div class="text-sm" :style="{ color: 'var(--text-muted)' }">
      <!-- Breadcrumb or page title area -->
    </div>

    <div class="flex items-center gap-3">
      <!-- Language selector -->
      <div class="relative" ref="langDropdownRef">
        <button
          class="topbar-btn"
          @click="showLangDropdown = !showLangDropdown"
          title="Language"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <line x1="2" y1="12" x2="22" y2="12"/>
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
          </svg>
        </button>

        <div
          v-if="showLangDropdown"
          class="absolute right-0 top-full mt-1 w-36 glass rounded-lg shadow-xl py-1 z-50"
        >
          <button
            v-for="lang in languages"
            :key="lang.code"
            class="dropdown-item w-full text-left flex items-center gap-2"
            :class="{ 'dropdown-item-active': currentLocale === lang.code }"
            @click="switchLanguage(lang.code)"
          >
            <span>{{ lang.flag }}</span>
            <span>{{ lang.name }}</span>
          </button>
        </div>
      </div>

      <!-- Theme toggle -->
      <button
        class="theme-toggle-btn"
        @click="themeStore.toggleTheme()"
        :title="themeStore.isDark ? 'Switch to light mode' : 'Switch to dark mode'"
      >
        <span class="theme-icon" :class="{ 'rotate-spin': rotating }">
          <template v-if="themeStore.isDark">
            <!-- Sun icon -->
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="5"/>
              <line x1="12" y1="1" x2="12" y2="3"/>
              <line x1="12" y1="21" x2="12" y2="23"/>
              <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
              <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
              <line x1="1" y1="12" x2="3" y2="12"/>
              <line x1="21" y1="12" x2="23" y2="12"/>
              <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
              <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
            </svg>
          </template>
          <template v-else>
            <!-- Moon icon -->
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
            </svg>
          </template>
        </span>
      </button>

      <!-- Notifications -->
      <button
        class="topbar-btn relative"
        @click="showNotifications = !showNotifications"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
          <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
        </svg>
        <span
          v-if="unreadCount > 0"
          class="absolute -top-0.5 -right-0.5 w-4 h-4 text-white text-[10px] font-bold rounded-full flex items-center justify-center"
          :style="{ backgroundColor: 'var(--error)' }"
        >
          {{ unreadCount > 9 ? '9+' : unreadCount }}
        </span>
      </button>

      <!-- User dropdown -->
      <div class="relative" ref="dropdownRef">
        <button
          class="flex items-center gap-2 p-1.5 rounded-lg transition-colors"
          :style="{ ':hover': { backgroundColor: 'var(--surface)' } }"
          @click="showDropdown = !showDropdown"
        >
          <div
            class="w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium"
            style="background: rgba(var(--primary-rgb), 0.2); color: var(--primary)"
          >
            {{ userInitial }}
          </div>
          <span class="text-sm" :style="{ color: 'var(--text-primary)' }">
            {{ auth.user?.username || 'User' }}
          </span>
          <span :style="{ color: 'var(--text-muted)' }" class="text-xs">&#9662;</span>
        </button>

        <div
          v-if="showDropdown"
          class="absolute right-0 top-full mt-1 w-48 glass rounded-lg shadow-xl py-1 z-50"
        >
          <router-link
            to="/settings"
            class="dropdown-item"
            @click="showDropdown = false"
          >
            {{ $t('auth.profile_settings') }}
          </router-link>
          <div :style="{ borderTop: '1px solid var(--border)' }" class="my-1"></div>
          <button
            class="dropdown-item w-full text-left"
            :style="{ color: 'var(--error)' }"
            @click="handleLogout"
          >
            {{ $t('auth.log_out') }}
          </button>
        </div>
      </div>
    </div>
  </header>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { onClickOutside } from '@vueuse/core'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'

const { locale: currentLocale } = useI18n()
const auth = useAuthStore()
const themeStore = useThemeStore()
const showDropdown = ref(false)
const showNotifications = ref(false)
const showLangDropdown = ref(false)
const dropdownRef = ref(null)
const langDropdownRef = ref(null)
const unreadCount = ref(0)
const rotating = ref(false)

const languages = [
  { code: 'en', name: 'English', flag: 'EN' },
  { code: 'pl', name: 'Polski', flag: 'PL' }
]

onClickOutside(dropdownRef, () => {
  showDropdown.value = false
})

onClickOutside(langDropdownRef, () => {
  showLangDropdown.value = false
})

const userInitial = computed(() => {
  return (auth.user?.username || 'U').charAt(0).toUpperCase()
})

function switchLanguage(code) {
  currentLocale.value = code
  localStorage.setItem('locale', code)
  showLangDropdown.value = false
}

function handleLogout() {
  showDropdown.value = false
  auth.logout()
}
</script>

<style scoped>
.topbar-btn {
  padding: 0.5rem;
  border-radius: 8px;
  color: var(--text-muted);
  transition: all 0.2s ease;
}
.topbar-btn:hover {
  color: var(--text-primary);
  background: rgba(var(--surface-rgb), 0.6);
}

.theme-toggle-btn {
  padding: 0.5rem;
  border-radius: 8px;
  color: var(--text-muted);
  transition: all 0.2s ease;
}
.theme-toggle-btn:hover {
  color: var(--warning);
  background: rgba(var(--surface-rgb), 0.6);
}

.theme-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.5s ease;
}

.rotate-spin {
  transform: rotate(360deg);
}

.dropdown-item {
  display: block;
  padding: 0.5rem 1rem;
  font-size: 0.875rem;
  color: var(--text-muted);
  transition: all 0.15s ease;
}
.dropdown-item:hover {
  color: var(--text-primary);
  background: rgba(var(--surface-rgb), 0.5);
}
.dropdown-item-active {
  color: var(--primary);
}
</style>
