<template>
  <!-- Mobile backdrop -->
  <Transition name="sidebar-backdrop">
    <div
      v-if="mobileOpen"
      class="fixed inset-0 bg-black/50 backdrop-blur-sm z-30 md:hidden"
      @click="mobileOpen = false"
    />
  </Transition>

  <aside
    class="fixed left-0 top-0 bottom-0 w-60 glass-strong flex flex-col z-40 transition-transform duration-300 ease-in-out"
    :class="mobileOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'"
  >
    <!-- Logo -->
    <div class="h-[60px] flex items-center px-5" :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
      <router-link to="/dashboard" class="flex items-center gap-2.5 no-underline">
        <img :src="logoSrc" alt="HostHive" class="w-8 h-8 flex-shrink-0" />
        <span class="text-lg font-semibold" :style="{ color: 'var(--text-primary)' }">HostHive</span>
      </router-link>
      <!-- Mobile close button -->
      <button
        class="ml-auto p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[rgba(var(--surface-rgb),0.5)] md:hidden min-w-[44px] min-h-[44px] flex items-center justify-center"
        @click="mobileOpen = false"
        aria-label="Close sidebar"
      >
        &#10005;
      </button>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 overflow-y-auto py-4 px-3">
      <div class="space-y-0.5">
        <router-link
          v-for="item in mainNav"
          :key="item.to"
          :to="item.to"
          class="nav-link"
          active-class="nav-link-active"
          @click="closeMobile"
        >
          <!-- v-html safe: icon is a hardcoded HTML entity from trusted source, not user input -->
          <span class="nav-icon" v-html="item.icon"></span>
          <span>{{ item.label }}</span>
        </router-link>
      </div>

      <!-- Reseller Section -->
      <div v-if="auth.isReseller" class="mt-6">
        <div class="px-3 mb-2 text-xs font-semibold uppercase tracking-wider" :style="{ color: 'var(--text-muted)' }">
          Reseller
        </div>
        <div class="space-y-0.5">
          <router-link
            v-for="item in resellerNav"
            :key="item.to"
            :to="item.to"
            class="nav-link"
            active-class="nav-link-active"
            @click="closeMobile"
          >
            <!-- v-html safe: icon is a hardcoded HTML entity from trusted source, not user input -->
            <span class="nav-icon" v-html="item.icon"></span>
            <span>{{ item.label }}</span>
          </router-link>
        </div>
      </div>

      <!-- Admin Section -->
      <div v-if="auth.isAdmin" class="mt-6">
        <div class="px-3 mb-2 text-xs font-semibold uppercase tracking-wider" :style="{ color: 'var(--text-muted)' }">
          {{ $t('nav.administration') }}
        </div>
        <div class="space-y-0.5">
          <router-link
            v-for="item in adminNav"
            :key="item.to"
            :to="item.to"
            class="nav-link"
            active-class="nav-link-active"
            @click="closeMobile"
          >
            <!-- v-html safe: icon is a hardcoded HTML entity from trusted source, not user input -->
            <span class="nav-icon" v-html="item.icon"></span>
            <span>{{ item.label }}</span>
          </router-link>
        </div>
      </div>

      <!-- Status Page Link -->
      <div class="mt-6">
        <div class="px-3 mb-2 text-xs font-semibold uppercase tracking-wider" :style="{ color: 'var(--text-muted)' }">
          {{ $t('nav.external') }}
        </div>
        <div class="space-y-0.5">
          <a
            href="/status"
            target="_blank"
            rel="noopener"
            class="nav-link"
            @click="closeMobile"
          >
            <span class="nav-icon">&#9673;</span>
            <span>{{ $t('nav.status_page') }}</span>
            <span class="ml-auto text-xs opacity-50">&#8599;</span>
          </a>
        </div>
      </div>
    </nav>

    <!-- Version -->
    <div class="px-5 py-3" :style="{ borderTop: '1px solid rgba(var(--border-rgb), 0.3)' }">
      <span class="text-xs" :style="{ color: 'var(--text-muted)' }">HostHive v1.0.0</span>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { useSidebarStore } from '@/stores/sidebar'
import logoSrc from '@/assets/logo-icon.svg'

const { t } = useI18n()
const auth = useAuthStore()
const sidebar = useSidebarStore()

const mobileOpen = computed({
  get: () => sidebar.mobileOpen,
  set: (val) => { sidebar.mobileOpen = val }
})

function closeMobile() {
  sidebar.mobileOpen = false
}

const mainNav = computed(() => [
  { to: '/dashboard', label: t('nav.dashboard'), icon: '&#9632;' },
  { to: '/domains', label: t('nav.domains'), icon: '&#9673;' },
  { to: '/databases', label: t('nav.databases'), icon: '&#9707;' },
  { to: '/email', label: t('nav.email'), icon: '&#9993;' },
  { to: '/dns', label: t('nav.dns'), icon: '&#9881;' },
  { to: '/ftp', label: t('nav.ftp'), icon: '&#8645;' },
  { to: '/cron', label: t('nav.cron'), icon: '&#8635;' },
  { to: '/ssl', label: t('nav.ssl'), icon: '&#9919;' },
  { to: '/backups', label: t('nav.backups'), icon: '&#9744;' },
  { to: '/files', label: t('nav.files'), icon: '&#9782;' },
  { to: '/api-keys', label: t('nav.api_keys'), icon: '&#9919;' },
  { to: '/ai', label: t('nav.ai'), icon: '&#129504;' },
  { to: '/apps', label: t('nav.apps', 'App Store'), icon: '&#9881;' },
  { to: '/runtime', label: t('nav.runtime', 'Runtime Apps'), icon: '&#9654;' },
  { to: '/docker', label: t('nav.docker'), icon: '&#9898;' },
  { to: '/wordpress', label: t('nav.wordpress'), icon: '&#127760;' }
])

const resellerNav = computed(() => [
  { to: '/reseller', label: t('nav.reseller_dashboard', 'Reseller Dashboard'), icon: '&#9632;' },
  { to: '/reseller/users', label: t('nav.my_users', 'My Users'), icon: '&#9823;' },
  { to: '/reseller/branding', label: t('nav.branding', 'Branding'), icon: '&#9998;' }
])

const adminNav = computed(() => [
  { to: '/packages', label: t('nav.packages'), icon: '&#9830;' },
  { to: '/users', label: t('nav.users'), icon: '&#9823;' },
  { to: '/server', label: t('nav.server'), icon: '&#9874;' },
  { to: '/monitoring', label: t('nav.monitoring'), icon: '&#9889;' },
  { to: '/security', label: t('nav.security', 'Security'), icon: '&#128737;' },
  { to: '/analytics', label: t('nav.analytics', 'Analytics'), icon: '&#9906;' },
  { to: '/integrations', label: t('nav.integrations'), icon: '&#10731;' },
  { to: '/audit-log', label: t('nav.audit'), icon: '&#9993;' },
  { to: '/logs', label: t('nav.logs', 'Logs'), icon: '&#128220;' },
  { to: '/settings', label: t('nav.settings'), icon: '&#9881;' },
  { to: '/translations', label: t('nav.translations'), icon: '&#127760;' },
  { to: '/wireguard', label: t('nav.wireguard', 'WireGuard VPN'), icon: '&#128274;' },
  { to: '/antivirus', label: t('nav.antivirus', 'Antivirus'), icon: '&#9737;' },
  { to: '/settings/mcp', label: 'MCP Server', icon: '&#10731;' },
  { to: '/settings/ai', label: 'AI Settings', icon: '&#129504;' },
  { to: '/waf', label: t('nav.waf', 'WAF'), icon: '&#128737;' },
  { to: '/ip-manager', label: t('nav.ip_manager', 'IP Manager'), icon: '&#127760;' }
])
</script>

<style scoped>
.nav-link {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.625rem 0.75rem;
  border-radius: 8px;
  font-size: 0.875rem;
  color: var(--text-muted);
  transition: all 0.2s ease;
  position: relative;
  min-height: 44px;
}

.nav-link:hover {
  color: var(--text-primary);
  background: rgba(var(--primary-rgb), 0.06);
}

.nav-link-active {
  color: var(--primary);
  background: rgba(var(--primary-rgb), 0.1);
  box-shadow: 0 0 15px rgba(var(--primary-rgb), 0.1);
}

.nav-link-active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 60%;
  border-radius: 0 4px 4px 0;
  background: var(--primary);
}

.nav-icon {
  width: 1.25rem;
  text-align: center;
  font-size: 1rem;
}

/* Backdrop transition */
.sidebar-backdrop-enter-active,
.sidebar-backdrop-leave-active {
  transition: opacity 0.3s ease;
}
.sidebar-backdrop-enter-from,
.sidebar-backdrop-leave-to {
  opacity: 0;
}
</style>
