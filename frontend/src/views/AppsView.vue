<template>
  <div>
    <!-- Page Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
      <div>
        <h1 class="text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">App Store</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">One-click application installer</p>
      </div>
      <div class="flex items-center gap-3 self-start sm:self-auto">
        <div class="relative">
          <input
            v-model="search"
            type="text"
            placeholder="Search apps..."
            class="pl-9 pr-4 py-2 text-sm rounded-lg w-56"
            :style="{
              background: 'rgba(var(--surface-rgb), 0.6)',
              border: '1px solid rgba(var(--border-rgb), 0.3)',
              color: 'var(--text-primary)'
            }"
          />
          <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" :style="{ color: 'var(--text-muted)' }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
        </div>
        <button class="btn-secondary text-sm min-h-[44px] inline-flex items-center gap-1.5" @click="refresh">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="23 4 23 10 17 10"/>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
          </svg>
          Refresh
        </button>
      </div>
    </div>

    <!-- Tabs -->
    <div class="flex gap-1 mb-5" :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
      <button
        v-for="tab in ['Available', 'Installed']"
        :key="tab"
        class="px-5 py-2.5 text-sm font-medium transition-colors relative"
        :style="{
          color: activeTab === tab ? 'var(--primary)' : 'var(--text-muted)',
          borderBottom: activeTab === tab ? '2px solid var(--primary)' : '2px solid transparent'
        }"
        @click="activeTab = tab"
      >
        {{ tab }}
        <span
          v-if="tab === 'Installed' && apps.installedApps.length > 0"
          class="ml-1.5 text-xs px-1.5 py-0.5 rounded-full"
          :style="{ background: 'rgba(var(--primary-rgb), 0.15)', color: 'var(--primary)' }"
        >{{ apps.installedApps.length }}</span>
      </button>
    </div>

    <!-- Available Tab -->
    <template v-if="activeTab === 'Available'">
      <!-- Category Filter Chips -->
      <div class="flex flex-wrap gap-2 mb-5">
        <button
          v-for="cat in apps.categories"
          :key="cat"
          class="px-3.5 py-1.5 text-xs font-medium rounded-full transition-all"
          :style="{
            background: selectedCategory === cat ? 'var(--primary)' : 'rgba(var(--surface-rgb), 0.6)',
            color: selectedCategory === cat ? '#fff' : 'var(--text-muted)',
            border: selectedCategory === cat ? '1px solid var(--primary)' : '1px solid rgba(var(--border-rgb), 0.3)'
          }"
          @click="selectedCategory = cat"
        >
          {{ cat }}
        </button>
      </div>

      <!-- Loading Skeleton -->
      <div v-if="apps.loading" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        <div v-for="i in 8" :key="i" class="glass rounded-2xl p-5">
          <div class="flex items-center gap-3 mb-3">
            <div class="skeleton w-11 h-11 rounded-xl"></div>
            <div class="flex-1">
              <div class="skeleton h-4 w-24 mb-1.5"></div>
              <div class="skeleton h-3 w-16"></div>
            </div>
          </div>
          <div class="skeleton h-3 w-full mb-4"></div>
          <div class="skeleton h-9 w-full rounded-lg"></div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-else-if="filteredCatalog.length === 0" class="glass rounded-2xl p-12 text-center">
        <div class="text-5xl mb-4">&#128270;</div>
        <h3 class="text-lg font-semibold mb-2" :style="{ color: 'var(--text-primary)' }">No Apps Found</h3>
        <p class="text-sm" :style="{ color: 'var(--text-muted)' }">Try adjusting your search or category filter.</p>
      </div>

      <!-- App Cards Grid -->
      <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        <div
          v-for="app in filteredCatalog"
          :key="app.slug"
          class="glass rounded-2xl p-5 transition-all hover:shadow-lg group"
          :style="{ border: '1px solid rgba(var(--border-rgb), 0.2)' }"
        >
          <!-- App Header -->
          <div class="flex items-center gap-3 mb-3">
            <div
              class="w-11 h-11 rounded-xl flex items-center justify-center text-lg font-bold flex-shrink-0"
              :style="{
                background: appIconBg(app.slug),
                color: appIconColor(app.slug)
              }"
            >
              <!-- v-html safe: appIcon returns hardcoded SVG/text from trusted source -->
              <span v-html="appIcon(app.slug)"></span>
            </div>
            <div class="min-w-0">
              <h3 class="font-semibold text-sm truncate" :style="{ color: 'var(--text-primary)' }">{{ app.name }}</h3>
              <span
                class="text-xs px-2 py-0.5 rounded-full"
                :style="{
                  background: categoryBg(app.category),
                  color: categoryColor(app.category)
                }"
              >{{ app.category }}</span>
            </div>
          </div>

          <!-- Description -->
          <p class="text-xs leading-relaxed mb-4 line-clamp-2" :style="{ color: 'var(--text-muted)' }">
            {{ app.description }}
          </p>

          <!-- Footer -->
          <div class="flex items-center justify-between">
            <span class="text-xs" :style="{ color: 'var(--text-muted)' }">v{{ app.version }}</span>
            <button
              class="btn-primary text-xs px-4 py-1.5 rounded-lg"
              :disabled="apps.installing"
              @click="openInstallModal(app)"
            >
              Install
            </button>
          </div>
        </div>
      </div>
    </template>

    <!-- Installed Tab -->
    <template v-if="activeTab === 'Installed'">
      <!-- Loading Skeleton -->
      <div v-if="apps.loading" class="space-y-3">
        <div v-for="i in 4" :key="i" class="glass rounded-2xl p-5 flex items-center gap-4">
          <div class="skeleton w-10 h-10 rounded-lg"></div>
          <div class="flex-1">
            <div class="skeleton h-4 w-32 mb-2"></div>
            <div class="skeleton h-3 w-48"></div>
          </div>
          <div class="skeleton h-8 w-20"></div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-else-if="apps.installedApps.length === 0" class="glass rounded-2xl p-12 text-center">
        <div class="text-5xl mb-4">&#128230;</div>
        <h3 class="text-lg font-semibold mb-2" :style="{ color: 'var(--text-primary)' }">No Installed Apps</h3>
        <p class="text-sm mb-4" :style="{ color: 'var(--text-muted)' }">Browse the catalog and install your first app.</p>
        <button class="btn-primary" @click="activeTab = 'Available'">Browse Apps</button>
      </div>

      <!-- Installed Apps List -->
      <div v-else class="space-y-3">
        <div
          v-for="app in apps.installedApps"
          :key="app.domain"
          class="glass rounded-2xl p-5 transition-all"
          :style="{ border: '1px solid rgba(var(--border-rgb), 0.2)' }"
        >
          <div class="flex flex-col sm:flex-row sm:items-center gap-4">
            <!-- App Info -->
            <div class="flex items-center gap-3 flex-1 min-w-0">
              <div
                class="w-10 h-10 rounded-xl flex items-center justify-center text-base font-bold flex-shrink-0"
                :style="{
                  background: 'rgba(var(--primary-rgb), 0.12)',
                  color: 'var(--primary)'
                }"
              >
                <!-- v-html safe: runtimeIcon returns hardcoded text from trusted source -->
                <span v-html="runtimeIcon(app.runtime)"></span>
              </div>
              <div class="min-w-0">
                <h3 class="font-semibold text-sm truncate" :style="{ color: 'var(--text-primary)' }">{{ app.domain }}</h3>
                <div class="flex items-center gap-2 mt-0.5 flex-wrap">
                  <span class="text-xs" :style="{ color: 'var(--text-muted)' }">{{ app.runtime || 'App' }}</span>
                  <span v-if="app.port" class="text-xs px-1.5 py-0.5 rounded" :style="{ background: 'rgba(var(--primary-rgb), 0.1)', color: 'var(--primary)' }">:{{ app.port }}</span>
                </div>
              </div>
            </div>

            <!-- Status -->
            <div class="flex items-center gap-3">
              <span
                class="badge flex-shrink-0"
                :class="{
                  'badge-success': app.status === 'running',
                  'badge-error': app.status === 'stopped' || app.status === 'error',
                  'badge-warning': app.status === 'restarting'
                }"
              >
                <span class="w-1.5 h-1.5 rounded-full" :style="{
                  background: app.status === 'running' ? 'var(--success)' :
                              app.status === 'stopped' || app.status === 'error' ? 'var(--error)' : 'var(--warning)'
                }"></span>
                {{ app.status }}
              </span>
            </div>

            <!-- Actions -->
            <div class="flex gap-1.5 flex-wrap">
              <a
                :href="'https://' + app.domain"
                target="_blank"
                rel="noopener"
                class="btn-ghost text-xs px-2.5 py-1.5 inline-flex items-center gap-1"
              >
                &#8599; Open
              </a>
              <button
                v-if="app.status !== 'running'"
                class="btn-ghost text-xs px-2.5 py-1.5"
                @click="apps.startApp(app.domain)"
              >&#9654; Start</button>
              <button
                v-if="app.status === 'running'"
                class="btn-ghost text-xs px-2.5 py-1.5"
                @click="apps.stopApp(app.domain)"
              >&#9632; Stop</button>
              <button
                class="btn-ghost text-xs px-2.5 py-1.5"
                @click="apps.restartApp(app.domain)"
              >&#8635; Restart</button>
              <button
                class="btn-ghost text-xs px-2.5 py-1.5"
                :style="{ color: 'var(--error)' }"
                @click="confirmUninstall(app.domain)"
              >&#10005; Uninstall</button>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- Install Modal -->
    <Modal v-model="showInstallModal" :title="'Install ' + (selectedApp?.name || '')" size="lg">
      <div v-if="selectedApp" class="space-y-4">
        <!-- App Info Banner -->
        <div class="flex items-center gap-3 p-3 rounded-xl" :style="{ background: 'rgba(var(--primary-rgb), 0.06)' }">
          <div
            class="w-10 h-10 rounded-xl flex items-center justify-center text-base font-bold flex-shrink-0"
            :style="{ background: appIconBg(selectedApp.slug), color: appIconColor(selectedApp.slug) }"
          >
            <!-- v-html safe: appIcon returns hardcoded SVG/text from trusted source -->
            <span v-html="appIcon(selectedApp.slug)"></span>
          </div>
          <div>
            <h4 class="font-semibold text-sm" :style="{ color: 'var(--text-primary)' }">{{ selectedApp.name }}</h4>
            <p class="text-xs" :style="{ color: 'var(--text-muted)' }">v{{ selectedApp.version }} &middot; {{ selectedApp.category }}</p>
          </div>
        </div>

        <!-- Domain -->
        <div>
          <label class="input-label">Domain</label>
          <select
            v-model="installForm.domain"
            class="w-full"
            :style="{
              background: 'rgba(var(--surface-rgb), 0.6)',
              border: '1px solid rgba(var(--border-rgb), 0.3)',
              color: 'var(--text-primary)'
            }"
          >
            <option value="" disabled>Select a domain</option>
            <option v-for="d in domains" :key="d.domain || d.name || d.id" :value="d.domain || d.name">
              {{ d.domain || d.name }}
            </option>
          </select>
          <p v-if="domains.length === 0" class="text-xs mt-1" :style="{ color: 'var(--warning)' }">
            No domains found. Create a domain first.
          </p>
        </div>

        <!-- Sub-path (optional) -->
        <div>
          <label class="input-label">Sub-path (optional)</label>
          <input
            v-model="installForm.path"
            type="text"
            class="w-full"
            placeholder="e.g. /blog"
            :style="{
              background: 'rgba(var(--surface-rgb), 0.6)',
              border: '1px solid rgba(var(--border-rgb), 0.3)',
              color: 'var(--text-primary)'
            }"
          />
        </div>

        <!-- Database Type (if requires_database) -->
        <div v-if="selectedApp.requires_database">
          <label class="input-label">Database Type</label>
          <select
            v-model="installForm.db_type"
            class="w-full"
            :style="{
              background: 'rgba(var(--surface-rgb), 0.6)',
              border: '1px solid rgba(var(--border-rgb), 0.3)',
              color: 'var(--text-primary)'
            }"
          >
            <option v-for="dbType in (selectedApp.database_types || ['mysql'])" :key="dbType" :value="dbType">
              {{ dbType === 'mysql' ? 'MySQL / MariaDB' : dbType === 'postgresql' ? 'PostgreSQL' : dbType }}
            </option>
          </select>
        </div>

        <!-- Port (for runtime apps) -->
        <div v-if="needsPort">
          <label class="input-label">Port</label>
          <input
            v-model.number="installForm.port"
            type="number"
            class="w-full"
            :placeholder="defaultPort"
            min="1024"
            max="65535"
            :style="{
              background: 'rgba(var(--surface-rgb), 0.6)',
              border: '1px solid rgba(var(--border-rgb), 0.3)',
              color: 'var(--text-primary)'
            }"
          />
        </div>

        <!-- Version Override (optional) -->
        <div>
          <label class="input-label">Version (optional override)</label>
          <input
            v-model="installForm.version"
            type="text"
            class="w-full"
            :placeholder="'Default: ' + selectedApp.version"
            :style="{
              background: 'rgba(var(--surface-rgb), 0.6)',
              border: '1px solid rgba(var(--border-rgb), 0.3)',
              color: 'var(--text-primary)'
            }"
          />
        </div>

        <!-- Requirements Info -->
        <div v-if="selectedApp.min_php" class="text-xs flex items-center gap-2 p-2.5 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)', color: 'var(--text-muted)' }">
          <span>&#9432;</span>
          <span>Requires PHP {{ selectedApp.min_php }}+</span>
        </div>
      </div>

      <template #actions>
        <button class="btn-secondary" @click="showInstallModal = false">Cancel</button>
        <button
          class="btn-primary"
          :disabled="!installForm.domain || apps.installing"
          @click="doInstall"
        >
          <span v-if="apps.installing" class="inline-flex items-center gap-2">
            <svg class="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" stroke-linecap="round" class="opacity-25"/>
              <path d="M4 12a8 8 0 018-8" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
            </svg>
            Installing...
          </span>
          <span v-else>Install</span>
        </button>
      </template>
    </Modal>

    <!-- Install Progress Modal -->
    <Modal v-model="showProgressModal" title="Installation Progress" size="md">
      <div v-if="apps.installProgress" class="space-y-6 py-2">
        <!-- Steps -->
        <div class="space-y-3">
          <div
            v-for="(step, idx) in apps.installProgress.steps"
            :key="step"
            class="flex items-center gap-3"
          >
            <!-- Step Indicator -->
            <div
              class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold flex-shrink-0 transition-all duration-300"
              :style="stepIndicatorStyle(idx)"
            >
              <template v-if="idx < apps.installProgress.currentStep">
                &#10003;
              </template>
              <template v-else-if="idx === apps.installProgress.currentStep && apps.installProgress.status === 'in_progress'">
                <svg class="animate-spin w-3.5 h-3.5" viewBox="0 0 24 24" fill="none">
                  <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" class="opacity-25"/>
                  <path d="M4 12a8 8 0 018-8" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
                </svg>
              </template>
              <template v-else-if="idx === apps.installProgress.currentStep && apps.installProgress.status === 'error'">
                &#10005;
              </template>
              <template v-else>
                {{ idx + 1 }}
              </template>
            </div>

            <!-- Step Label -->
            <span
              class="text-sm font-medium transition-colors"
              :style="{
                color: idx <= apps.installProgress.currentStep ? 'var(--text-primary)' : 'var(--text-muted)'
              }"
            >{{ step }}</span>

            <!-- Connecting line (visual) -->
          </div>
        </div>

        <!-- Error Message -->
        <div
          v-if="apps.installProgress.status === 'error'"
          class="p-3 rounded-lg text-sm"
          :style="{ background: 'rgba(var(--error-rgb, 239, 68, 68), 0.1)', color: 'var(--error)' }"
        >
          {{ apps.installProgress.error || 'Installation failed. Please try again.' }}
        </div>

        <!-- Success Message -->
        <div
          v-if="apps.installProgress.status === 'done'"
          class="p-3 rounded-lg text-sm"
          :style="{ background: 'rgba(var(--success-rgb, 34, 197, 94), 0.1)', color: 'var(--success)' }"
        >
          Application installed successfully! You can now access it from the Installed tab.
        </div>
      </div>

      <template #actions>
        <button
          class="btn-primary"
          :disabled="apps.installProgress?.status === 'in_progress'"
          @click="closeProgress"
        >
          {{ apps.installProgress?.status === 'done' ? 'Done' : apps.installProgress?.status === 'error' ? 'Close' : 'Installing...' }}
        </button>
      </template>
    </Modal>

    <!-- Uninstall Confirmation Modal -->
    <Modal v-model="showUninstallModal" title="Confirm Uninstall" size="sm">
      <div class="text-center py-4">
        <div class="text-4xl mb-3">&#9888;</div>
        <p class="text-sm" :style="{ color: 'var(--text-primary)' }">
          Are you sure you want to uninstall <strong>{{ uninstallDomain }}</strong>?
        </p>
        <p class="text-xs mt-2" :style="{ color: 'var(--text-muted)' }">
          This action will stop the application. Associated data may be lost.
        </p>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showUninstallModal = false">Cancel</button>
        <button
          class="px-4 py-2 rounded-lg text-sm font-medium text-white"
          :style="{ background: 'var(--error)' }"
          @click="doUninstall"
        >
          Uninstall
        </button>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useAppsStore } from '@/stores/apps'
import { useDomainsStore } from '@/stores/domains'
import Modal from '@/components/Modal.vue'

const apps = useAppsStore()
const domainsStore = useDomainsStore()

const activeTab = ref('Available')
const search = ref('')
const selectedCategory = ref('All')
const showInstallModal = ref(false)
const showProgressModal = ref(false)
const showUninstallModal = ref(false)
const selectedApp = ref(null)
const uninstallDomain = ref('')

const installForm = ref({
  domain: '',
  path: '',
  db_type: 'mysql',
  port: null,
  version: ''
})

const domains = computed(() => domainsStore.domains || [])

const needsPort = computed(() => {
  if (!selectedApp.value) return false
  const slug = selectedApp.value.slug
  return [
    'nodejs', 'python-django', 'ghost', 'gitea', 'mattermost',
    'discourse', 'invoiceninja', 'uptimekuma', 'grafana',
    'portainer', 'minio'
  ].includes(slug)
})

const defaultPort = computed(() => {
  if (!selectedApp.value) return '3000'
  const portMap = {
    nodejs: '3000',
    'python-django': '8000',
    ghost: '2368',
    gitea: '3000',
    mattermost: '8065',
    discourse: '4200',
    invoiceninja: '9080',
    uptimekuma: '3001',
    grafana: '3100',
    portainer: '9443',
    minio: '9001'
  }
  return portMap[selectedApp.value.slug] || '3000'
})

const filteredCatalog = computed(() => {
  let list = apps.catalog
  if (selectedCategory.value && selectedCategory.value !== 'All') {
    list = list.filter(a => a.category === selectedCategory.value)
  }
  if (search.value.trim()) {
    const q = search.value.toLowerCase().trim()
    list = list.filter(a =>
      a.name.toLowerCase().includes(q) ||
      a.description.toLowerCase().includes(q) ||
      a.category.toLowerCase().includes(q) ||
      a.slug.toLowerCase().includes(q)
    )
  }
  return list
})

// App icon mappings
const iconMap = {
  wordpress: 'W',
  joomla: 'J',
  drupal: 'D',
  prestashop: 'PS',
  opencart: 'OC',
  magento: 'M',
  laravel: 'L',
  nodejs: 'N',
  'python-django': 'Py',
  ghost: 'G',
  nextcloud: 'NC',
  phpmyadmin: 'PA',
  roundcube: 'RC',
  gitea: 'Gt',
  mattermost: 'MM',
  mediawiki: 'MW',
  bookstack: 'BS',
  phpbb: 'BB',
  discourse: 'Dc',
  invoiceninja: 'IN',
  uptimekuma: 'UK',
  grafana: 'Gr',
  portainer: 'Pt',
  minio: 'Mi',
  adminer: 'Ad'
}

const colorMap = {
  wordpress: { bg: 'rgba(33, 117, 155, 0.15)', color: '#21759b' },
  joomla: { bg: 'rgba(245, 130, 32, 0.15)', color: '#f58220' },
  drupal: { bg: 'rgba(0, 134, 200, 0.15)', color: '#0086c8' },
  prestashop: { bg: 'rgba(223, 0, 136, 0.15)', color: '#df0088' },
  opencart: { bg: 'rgba(35, 161, 209, 0.15)', color: '#23a1d1' },
  magento: { bg: 'rgba(243, 111, 33, 0.15)', color: '#f36f21' },
  laravel: { bg: 'rgba(255, 45, 32, 0.15)', color: '#ff2d20' },
  nodejs: { bg: 'rgba(104, 159, 56, 0.15)', color: '#689f38' },
  'python-django': { bg: 'rgba(12, 75, 51, 0.15)', color: '#0c4b33' },
  ghost: { bg: 'rgba(21, 23, 26, 0.15)', color: '#738a94' },
  nextcloud: { bg: 'rgba(0, 130, 201, 0.15)', color: '#0082c9' },
  phpmyadmin: { bg: 'rgba(111, 120, 141, 0.15)', color: '#6f788d' },
  roundcube: { bg: 'rgba(55, 123, 181, 0.15)', color: '#377bb5' },
  gitea: { bg: 'rgba(96, 154, 52, 0.15)', color: '#609a34' },
  mattermost: { bg: 'rgba(22, 99, 183, 0.15)', color: '#1663b7' },
  mediawiki: { bg: 'rgba(0, 96, 128, 0.15)', color: '#006080' },
  bookstack: { bg: 'rgba(2, 113, 173, 0.15)', color: '#0271ad' },
  phpbb: { bg: 'rgba(55, 109, 184, 0.15)', color: '#376db8' },
  discourse: { bg: 'rgba(0, 140, 226, 0.15)', color: '#008ce2' },
  invoiceninja: { bg: 'rgba(33, 150, 83, 0.15)', color: '#219653' },
  uptimekuma: { bg: 'rgba(90, 186, 71, 0.15)', color: '#5aba47' },
  grafana: { bg: 'rgba(240, 130, 12, 0.15)', color: '#f0820c' },
  portainer: { bg: 'rgba(19, 186, 226, 0.15)', color: '#13bae2' },
  minio: { bg: 'rgba(195, 40, 52, 0.15)', color: '#c32834' },
  adminer: { bg: 'rgba(0, 120, 183, 0.15)', color: '#0078b7' }
}

const categoryColorMap = {
  CMS: { bg: 'rgba(99, 102, 241, 0.12)', color: 'rgb(99, 102, 241)' },
  'E-Commerce': { bg: 'rgba(236, 72, 153, 0.12)', color: 'rgb(236, 72, 153)' },
  Framework: { bg: 'rgba(245, 158, 11, 0.12)', color: 'rgb(245, 158, 11)' },
  Runtime: { bg: 'rgba(16, 185, 129, 0.12)', color: 'rgb(16, 185, 129)' },
  Productivity: { bg: 'rgba(59, 130, 246, 0.12)', color: 'rgb(59, 130, 246)' },
  Tools: { bg: 'rgba(107, 114, 128, 0.12)', color: 'rgb(107, 114, 128)' },
  Email: { bg: 'rgba(168, 85, 247, 0.12)', color: 'rgb(168, 85, 247)' },
  DevOps: { bg: 'rgba(34, 197, 94, 0.12)', color: 'rgb(34, 197, 94)' },
  Communication: { bg: 'rgba(6, 182, 212, 0.12)', color: 'rgb(6, 182, 212)' },
  Forum: { bg: 'rgba(239, 68, 68, 0.12)', color: 'rgb(239, 68, 68)' },
  Monitoring: { bg: 'rgba(251, 146, 60, 0.12)', color: 'rgb(251, 146, 60)' }
}

function appIcon(slug) {
  return iconMap[slug] || slug.charAt(0).toUpperCase()
}

function appIconBg(slug) {
  return colorMap[slug]?.bg || 'rgba(var(--primary-rgb), 0.12)'
}

function appIconColor(slug) {
  return colorMap[slug]?.color || 'var(--primary)'
}

function categoryBg(cat) {
  return categoryColorMap[cat]?.bg || 'rgba(var(--primary-rgb), 0.1)'
}

function categoryColor(cat) {
  return categoryColorMap[cat]?.color || 'var(--primary)'
}

function runtimeIcon(runtime) {
  const map = { nodejs: 'N', python: 'Py', php: 'P' }
  return map[runtime] || '&#9679;'
}

function stepIndicatorStyle(idx) {
  const progress = apps.installProgress
  if (!progress) return {}

  if (idx < progress.currentStep) {
    // Completed
    return { background: 'var(--success)', color: '#fff' }
  }
  if (idx === progress.currentStep) {
    if (progress.status === 'error') {
      return { background: 'var(--error)', color: '#fff' }
    }
    if (progress.status === 'done') {
      return { background: 'var(--success)', color: '#fff' }
    }
    // In progress
    return { background: 'var(--primary)', color: '#fff' }
  }
  // Pending
  return {
    background: 'rgba(var(--border-rgb), 0.2)',
    color: 'var(--text-muted)'
  }
}

function openInstallModal(app) {
  selectedApp.value = app
  installForm.value = {
    domain: '',
    path: '',
    db_type: app.database_types?.[0] || 'mysql',
    port: null,
    version: ''
  }
  showInstallModal.value = true
}

async function doInstall() {
  if (!selectedApp.value || !installForm.value.domain) return

  const payload = {
    slug: selectedApp.value.slug,
    domain: installForm.value.domain,
    path: installForm.value.path || '',
    db_type: installForm.value.db_type || 'mysql'
  }

  if (installForm.value.port) {
    payload.port = installForm.value.port
  }
  if (installForm.value.version) {
    payload.version = installForm.value.version
  }

  showInstallModal.value = false
  showProgressModal.value = true

  try {
    await apps.installApp(payload)
  } catch {
    // Error is handled in the store; progress modal shows the error
  }
}

function closeProgress() {
  showProgressModal.value = false
  apps.clearProgress()
}

function confirmUninstall(domain) {
  uninstallDomain.value = domain
  showUninstallModal.value = true
}

async function doUninstall() {
  try {
    await apps.uninstallApp(uninstallDomain.value)
  } catch {
    // Error handled in store
  }
  showUninstallModal.value = false
}

async function refresh() {
  if (activeTab.value === 'Available') {
    await apps.fetchCatalog()
  } else {
    await apps.fetchInstalledApps()
  }
}

// Watch tab changes to refresh data
watch(activeTab, (tab) => {
  if (tab === 'Installed') {
    apps.fetchInstalledApps()
  }
})

onMounted(async () => {
  await Promise.all([
    apps.fetchCatalog(),
    apps.fetchInstalledApps(),
    domainsStore.fetchAll()
  ])
})
</script>

<style scoped>
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
