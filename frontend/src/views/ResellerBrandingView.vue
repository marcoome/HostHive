<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">White-Label Branding</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">Customize the look and feel for your users</p>
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- Settings Form -->
      <div class="glass rounded-2xl p-6">
        <h3 class="text-sm font-medium mb-5" :style="{ color: 'var(--text-primary)' }">Branding Settings</h3>

        <template v-if="loading">
          <div v-for="i in 4" :key="i" class="skeleton w-full h-10 mb-4 rounded-lg"></div>
        </template>

        <form v-else class="space-y-5" @submit.prevent="handleSave">
          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Logo URL</label>
            <input
              v-model="form.logo_url"
              type="url"
              placeholder="https://example.com/logo.png"
              class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
            <p class="mt-1 text-xs text-[var(--text-muted)]">Recommended: 200x50px, PNG or SVG</p>
          </div>

          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Primary Color</label>
            <div class="flex items-center gap-3">
              <input
                v-model="form.primary_color"
                type="color"
                class="w-10 h-10 rounded-lg border border-[var(--border)] cursor-pointer bg-transparent p-0.5"
              />
              <input
                v-model="form.primary_color"
                type="text"
                placeholder="#6366f1"
                class="flex-1 px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 font-mono"
              />
            </div>
          </div>

          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Custom Domain</label>
            <input
              v-model="form.custom_domain"
              type="text"
              placeholder="panel.yourdomain.com"
              class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
            <p class="mt-1 text-xs text-[var(--text-muted)]">Point a CNAME record to this server first</p>
          </div>

          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Custom CSS</label>
            <textarea
              v-model="form.custom_css"
              rows="6"
              placeholder="/* Custom CSS overrides */&#10;.sidebar { ... }"
              class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 font-mono resize-y"
            ></textarea>
          </div>

          <div class="flex justify-end">
            <button type="submit" class="btn-primary" :disabled="saving">
              <span v-if="saving" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
              {{ saving ? 'Saving...' : 'Save Branding' }}
            </button>
          </div>
        </form>
      </div>

      <!-- Live Preview Panel -->
      <div class="glass rounded-2xl p-6">
        <h3 class="text-sm font-medium mb-5" :style="{ color: 'var(--text-primary)' }">Live Preview</h3>

        <div
          class="rounded-xl overflow-hidden border border-[var(--border)]"
          :style="{ background: 'var(--bg-primary)' }"
        >
          <!-- Preview Header -->
          <div
            class="flex items-center gap-3 px-4 py-3"
            :style="{ borderBottom: '1px solid var(--border)', background: 'rgba(var(--border-rgb), 0.1)' }"
          >
            <div v-if="form.logo_url" class="h-6">
              <img :src="form.logo_url" alt="Logo preview" class="h-full object-contain" @error="logoError = true" />
            </div>
            <div v-else class="flex items-center gap-2">
              <div
                class="w-6 h-6 rounded flex items-center justify-center text-white text-xs font-bold"
                :style="{ background: form.primary_color || 'var(--primary)' }"
              >
                H
              </div>
              <span class="text-sm font-semibold" :style="{ color: 'var(--text-primary)' }">HostHive</span>
            </div>
          </div>

          <!-- Preview Sidebar + Content -->
          <div class="flex min-h-[280px]">
            <!-- Mini Sidebar -->
            <div
              class="w-36 py-3 px-2 space-y-1 flex-shrink-0"
              :style="{ borderRight: '1px solid var(--border)', background: 'rgba(var(--border-rgb), 0.05)' }"
            >
              <div
                v-for="item in ['Dashboard', 'Domains', 'Email', 'Files']"
                :key="item"
                class="px-2 py-1.5 rounded text-xs"
                :style="item === 'Dashboard'
                  ? { background: hexToRgba(form.primary_color || '#6366f1', 0.12), color: form.primary_color || 'var(--primary)' }
                  : { color: 'var(--text-muted)' }"
              >
                {{ item }}
              </div>
            </div>

            <!-- Mini Content -->
            <div class="flex-1 p-4 space-y-3">
              <div class="h-3 w-24 rounded" :style="{ background: 'rgba(var(--border-rgb), 0.3)' }"></div>
              <div class="grid grid-cols-2 gap-2">
                <div
                  v-for="i in 4"
                  :key="i"
                  class="h-14 rounded-lg"
                  :style="{ background: 'rgba(var(--border-rgb), 0.15)' }"
                ></div>
              </div>
              <div class="h-20 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }"></div>
            </div>
          </div>

          <!-- Preview Footer -->
          <div
            class="px-4 py-2 text-center"
            :style="{ borderTop: '1px solid var(--border)' }"
          >
            <span class="text-xs" :style="{ color: 'var(--text-muted)' }">
              {{ form.custom_domain || 'panel.example.com' }}
            </span>
          </div>
        </div>

        <!-- Color Swatch Info -->
        <div class="mt-4 flex items-center gap-3">
          <div
            class="w-8 h-8 rounded-lg border border-[var(--border)]"
            :style="{ background: form.primary_color || '#6366f1' }"
          ></div>
          <div>
            <p class="text-xs font-medium" :style="{ color: 'var(--text-primary)' }">Primary Color</p>
            <p class="text-xs font-mono" :style="{ color: 'var(--text-muted)' }">{{ form.primary_color || '#6366f1' }}</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useResellerStore } from '@/stores/reseller'
import { useNotificationsStore } from '@/stores/notifications'

const store = useResellerStore()
const notifications = useNotificationsStore()

const loading = ref(true)
const saving = ref(false)
const logoError = ref(false)

const form = ref({
  logo_url: '',
  primary_color: '#6366f1',
  custom_domain: '',
  custom_css: ''
})

function hexToRgba(hex, alpha) {
  const h = hex.replace('#', '')
  const r = parseInt(h.substring(0, 2), 16) || 0
  const g = parseInt(h.substring(2, 4), 16) || 0
  const b = parseInt(h.substring(4, 6), 16) || 0
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

async function handleSave() {
  saving.value = true
  try {
    const payload = {}
    if (form.value.logo_url) payload.logo_url = form.value.logo_url
    if (form.value.primary_color) payload.primary_color = form.value.primary_color
    if (form.value.custom_domain) payload.custom_domain = form.value.custom_domain
    if (form.value.custom_css) payload.custom_css = form.value.custom_css
    // Send all fields so the backend can clear them if empty
    payload.logo_url = form.value.logo_url || ''
    payload.primary_color = form.value.primary_color || '#6366f1'
    payload.custom_domain = form.value.custom_domain || ''
    payload.custom_css = form.value.custom_css || ''

    await store.updateBranding(payload)
    notifications.success('Branding settings saved.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to save branding.')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    await store.fetchBranding()
    if (store.branding) {
      form.value = {
        logo_url: store.branding.logo_url || '',
        primary_color: store.branding.primary_color || '#6366f1',
        custom_domain: store.branding.custom_domain || '',
        custom_css: store.branding.custom_css || ''
      }
    }
  } catch {
    // New reseller, no branding yet - use defaults
  } finally {
    loading.value = false
  }
})
</script>
