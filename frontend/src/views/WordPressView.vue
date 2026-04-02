<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">WordPress</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">Manage WordPress installations</p>
      </div>
    </div>

    <!-- Loading Skeleton -->
    <div v-if="wp.loading" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      <div v-for="i in 6" :key="i" class="glass rounded-2xl p-5">
        <div class="skeleton h-5 w-40 mb-3"></div>
        <div class="skeleton h-4 w-32 mb-2"></div>
        <div class="skeleton h-4 w-48 mb-2"></div>
        <div class="skeleton h-3 w-24 mb-4"></div>
        <div class="flex gap-2">
          <div class="skeleton h-8 w-20"></div>
          <div class="skeleton h-8 w-20"></div>
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-else-if="wp.installs.length === 0" class="glass rounded-2xl p-12 text-center">
      <div class="text-5xl mb-4">&#127760;</div>
      <h3 class="text-lg font-semibold mb-2" :style="{ color: 'var(--text-primary)' }">No WordPress Installations Detected</h3>
      <p class="text-sm" :style="{ color: 'var(--text-muted)' }">WordPress installations on your domains will appear here automatically.</p>
    </div>

    <!-- Installs Grid -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      <div
        v-for="install in wp.installs"
        :key="install.domain"
        class="glass rounded-2xl p-5"
      >
        <!-- Header -->
        <div class="flex items-start justify-between mb-3">
          <div class="min-w-0">
            <h3 class="font-semibold text-sm truncate" :style="{ color: 'var(--text-primary)' }">{{ install.domain }}</h3>
            <p class="text-xs mt-0.5" :style="{ color: 'var(--text-muted)' }">WordPress {{ install.version }}</p>
          </div>
          <div
            class="w-10 h-10 rounded-lg flex items-center justify-center text-lg font-bold flex-shrink-0"
            :style="{
              background: getScoreColor(install.security_score) + '20',
              color: getScoreColor(install.security_score)
            }"
          >
            {{ install.security_score || '?' }}
          </div>
        </div>

        <!-- Info -->
        <div class="space-y-1.5 mb-4">
          <div class="flex justify-between text-xs">
            <span :style="{ color: 'var(--text-muted)' }">Theme</span>
            <span :style="{ color: 'var(--text-primary)' }">{{ install.theme || 'Unknown' }}</span>
          </div>
          <div class="flex justify-between text-xs">
            <span :style="{ color: 'var(--text-muted)' }">Plugins</span>
            <span :style="{ color: 'var(--text-primary)' }">{{ install.plugins_count || 0 }}</span>
          </div>
          <div class="flex justify-between text-xs">
            <span :style="{ color: 'var(--text-muted)' }">PHP</span>
            <span :style="{ color: 'var(--text-primary)' }">{{ install.php_version || 'N/A' }}</span>
          </div>
        </div>

        <!-- Actions -->
        <div class="flex gap-1.5 flex-wrap">
          <button class="btn-ghost text-xs px-2 py-1" @click="handleUpdateCore(install.domain)">
            &#8593; Core
          </button>
          <button class="btn-ghost text-xs px-2 py-1" @click="handleUpdatePlugins(install.domain)">
            &#8593; Plugins
          </button>
          <button class="btn-ghost text-xs px-2 py-1" @click="handleBackup(install.domain)">
            &#9744; Backup
          </button>
          <button class="btn-ghost text-xs px-2 py-1" @click="openClone(install)">
            &#9901; Clone
          </button>
          <button class="btn-ghost text-xs px-2 py-1" @click="handleSecurityCheck(install.domain)">
            &#9919; Security
          </button>
        </div>
      </div>
    </div>

    <!-- Security Check Modal -->
    <Modal v-model="showSecurity" title="Security Check Results" size="lg">
      <div v-if="securityLoading" class="space-y-3 py-4">
        <div v-for="i in 4" :key="i" class="skeleton h-12 w-full"></div>
      </div>
      <div v-else-if="securityResults" class="space-y-3">
        <div class="flex items-center gap-3 mb-4">
          <GaugeChart :value="securityResults.score || 0" label="Score" :size="80" />
          <div>
            <h4 class="font-semibold" :style="{ color: 'var(--text-primary)' }">{{ securityDomain }}</h4>
            <p class="text-xs" :style="{ color: 'var(--text-muted)' }">{{ securityResults.issues?.length || 0 }} issues found</p>
          </div>
        </div>

        <div v-if="!securityResults.issues?.length" class="text-sm text-center py-4" :style="{ color: 'var(--success)' }">
          No security issues found!
        </div>

        <div
          v-for="(issue, i) in securityResults.issues"
          :key="i"
          class="glass rounded-xl p-4 flex items-start gap-3"
        >
          <span
            class="badge flex-shrink-0"
            :class="{
              'badge-error': issue.severity === 'critical' || issue.severity === 'high',
              'badge-warning': issue.severity === 'medium',
              'badge-info': issue.severity === 'low'
            }"
          >
            {{ issue.severity }}
          </span>
          <div>
            <p class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">{{ issue.title }}</p>
            <p class="text-xs mt-1" :style="{ color: 'var(--text-muted)' }">{{ issue.description }}</p>
          </div>
        </div>
      </div>
    </Modal>

    <!-- Clone Modal -->
    <Modal v-model="showClone" title="Clone WordPress" size="md">
      <div class="space-y-4">
        <div>
          <label class="input-label">Source Domain</label>
          <input :value="cloneSource" class="w-full" disabled />
        </div>
        <div class="flex items-center justify-center text-xl" :style="{ color: 'var(--text-muted)' }">&#8595;</div>
        <div>
          <label class="input-label">Target Domain</label>
          <input v-model="cloneTarget" class="w-full" placeholder="newsite.example.com" />
        </div>

        <div v-if="cloneProgress" class="mt-4">
          <div class="flex justify-between text-xs mb-1">
            <span :style="{ color: 'var(--text-muted)' }">Cloning...</span>
            <span :style="{ color: 'var(--primary)' }">{{ cloneProgress }}%</span>
          </div>
          <div class="h-2 rounded-full" :style="{ background: 'rgba(var(--border-rgb), 0.3)' }">
            <div
              class="h-full rounded-full transition-all duration-500"
              :style="{ width: cloneProgress + '%', background: 'var(--primary)' }"
            ></div>
          </div>
        </div>
      </div>

      <template #actions>
        <button class="btn-secondary" @click="showClone = false">Cancel</button>
        <button class="btn-primary" :disabled="!cloneTarget || cloneProgress > 0" @click="handleClone">Clone</button>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useWordPressStore } from '@/stores/wordpress'
import Modal from '@/components/Modal.vue'
import GaugeChart from '@/components/GaugeChart.vue'

const wp = useWordPressStore()

const showSecurity = ref(false)
const showClone = ref(false)
const securityResults = ref(null)
const securityDomain = ref('')
const securityLoading = ref(false)
const cloneSource = ref('')
const cloneTarget = ref('')
const cloneProgress = ref(0)

function getScoreColor(score) {
  if (!score) return 'var(--text-muted)'
  if (score >= 80) return 'var(--success)'
  if (score >= 60) return 'var(--warning)'
  return 'var(--error)'
}

async function handleUpdateCore(domain) {
  try { await wp.updateCore(domain) } catch {}
}

async function handleUpdatePlugins(domain) {
  try { await wp.updatePlugins(domain) } catch {}
}

async function handleBackup(domain) {
  try { await wp.backupWp(domain) } catch {}
}

async function handleSecurityCheck(domain) {
  securityDomain.value = domain
  securityResults.value = null
  securityLoading.value = true
  showSecurity.value = true
  try {
    securityResults.value = await wp.securityCheck(domain)
  } catch {
    securityResults.value = { score: 0, issues: [{ severity: 'critical', title: 'Check failed', description: 'Unable to complete security check.' }] }
  } finally {
    securityLoading.value = false
  }
}

function openClone(install) {
  cloneSource.value = install.domain
  cloneTarget.value = ''
  cloneProgress.value = 0
  showClone.value = true
}

async function handleClone() {
  cloneProgress.value = 10
  const interval = setInterval(() => {
    if (cloneProgress.value < 90) cloneProgress.value += 10
  }, 500)
  try {
    await wp.cloneWp(cloneSource.value, cloneTarget.value)
    cloneProgress.value = 100
    setTimeout(() => { showClone.value = false }, 800)
  } catch {
    cloneProgress.value = 0
  } finally {
    clearInterval(interval)
  }
}

onMounted(async () => {
  try { await wp.fetchInstalls() } catch {}
})
</script>
