<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-semibold text-[var(--text-primary)]">Settings</h1>

    <!-- Tabs -->
    <div class="glass rounded-2xl">
      <div class="flex border-b border-[var(--border)]">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          class="px-5 py-3 text-sm font-medium transition-colors relative"
          :class="activeTab === tab.id
            ? 'text-primary'
            : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'"
          @click="activeTab = tab.id"
        >
          {{ tab.label }}
          <span
            v-if="activeTab === tab.id"
            class="absolute bottom-0 left-0 right-0 h-0.5 bg-primary rounded-t"
          ></span>
        </button>
      </div>

      <div class="p-6">
        <!-- Profile Tab -->
        <div v-if="activeTab === 'profile'" class="space-y-6 max-w-lg">
          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Display Name</label>
            <input
              v-model="profileForm.display_name"
              type="text"
              class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Email Address</label>
            <input
              v-model="profileForm.email"
              type="email"
              class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
          <div>
            <button
              class="btn-primary"
              :disabled="savingProfile"
              @click="saveProfile"
            >
              <span v-if="savingProfile" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
              {{ savingProfile ? 'Saving...' : 'Save Changes' }}
            </button>
          </div>
        </div>

        <!-- Security Tab -->
        <div v-else-if="activeTab === 'security'" class="space-y-8">
          <!-- Change Password -->
          <div class="max-w-lg">
            <h3 class="text-base font-semibold text-[var(--text-primary)] mb-4">Change Password</h3>
            <form class="space-y-4" @submit.prevent="changePassword">
              <div>
                <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Current Password</label>
                <input
                  v-model="passwordForm.current"
                  type="password"
                  required
                  class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
              </div>
              <div>
                <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">New Password</label>
                <input
                  v-model="passwordForm.new_password"
                  type="password"
                  required
                  minlength="8"
                  class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
              </div>
              <div>
                <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Confirm New Password</label>
                <input
                  v-model="passwordForm.confirm"
                  type="password"
                  required
                  class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                  :class="{ 'border-error': passwordForm.confirm && passwordForm.confirm !== passwordForm.new_password }"
                />
                <p v-if="passwordForm.confirm && passwordForm.confirm !== passwordForm.new_password" class="mt-1 text-xs text-error">
                  Passwords do not match.
                </p>
              </div>
              <button
                type="submit"
                class="btn-primary"
                :disabled="savingPassword || !passwordForm.current || !passwordForm.new_password || passwordForm.new_password !== passwordForm.confirm"
              >
                <span v-if="savingPassword" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
                {{ savingPassword ? 'Updating...' : 'Update Password' }}
              </button>
            </form>
          </div>

          <!-- 2FA -->
          <div class="border-t border-[var(--border)] pt-8 max-w-lg">
            <h3 class="text-base font-semibold text-[var(--text-primary)] mb-1">Two-Factor Authentication</h3>
            <p class="text-sm text-[var(--text-muted)] mb-4">
              {{ twoFA.enabled ? 'Two-factor authentication is enabled.' : 'Add an extra layer of security to your account.' }}
            </p>

            <div v-if="!twoFA.enabled && !twoFA.showSetup">
              <button class="btn-primary" @click="setup2FA">Enable 2FA</button>
            </div>

            <div v-else-if="twoFA.showSetup" class="space-y-4">
              <!-- QR Code placeholder -->
              <div class="flex justify-center">
                <div class="w-48 h-48 bg-white rounded-xl flex items-center justify-center border border-[var(--border)]">
                  <div v-if="twoFA.qrLoading" class="skeleton w-40 h-40 rounded"></div>
                  <img
                    v-else-if="twoFA.qrUrl"
                    :src="twoFA.qrUrl"
                    alt="2FA QR Code"
                    class="w-40 h-40"
                  />
                  <div v-else class="text-center text-sm text-[var(--text-muted)] p-4">
                    <div class="text-3xl mb-2">&#128274;</div>
                    <p>QR Code</p>
                  </div>
                </div>
              </div>

              <div v-if="twoFA.secret" class="text-center">
                <p class="text-xs text-[var(--text-muted)] mb-1">Or enter this code manually:</p>
                <code class="text-sm font-mono text-[var(--text-primary)] bg-[var(--surface)] px-3 py-1 rounded select-all">
                  {{ twoFA.secret }}
                </code>
              </div>

              <div>
                <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Verification Code</label>
                <input
                  v-model="twoFA.verifyCode"
                  type="text"
                  maxlength="6"
                  placeholder="000000"
                  class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] font-mono text-center text-lg tracking-[0.5em] focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
              </div>

              <div class="flex gap-3">
                <button class="btn-secondary" @click="twoFA.showSetup = false">Cancel</button>
                <button
                  class="btn-primary"
                  :disabled="twoFA.verifyCode.length !== 6 || twoFA.verifying"
                  @click="verify2FA"
                >
                  <span v-if="twoFA.verifying" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
                  {{ twoFA.verifying ? 'Verifying...' : 'Verify & Enable' }}
                </button>
              </div>
            </div>

            <div v-else-if="twoFA.enabled">
              <button class="btn-danger" @click="disable2FA">Disable 2FA</button>
            </div>
          </div>

          <!-- Active Sessions -->
          <div class="border-t border-[var(--border)] pt-8">
            <h3 class="text-base font-semibold text-[var(--text-primary)] mb-4">Active Sessions</h3>
            <div class="space-y-3">
              <div
                v-for="session in sessions"
                :key="session.id"
                class="flex items-center justify-between p-4 bg-[var(--surface)] rounded-xl border border-[var(--border)]"
              >
                <div class="flex items-center gap-3">
                  <span class="text-lg">{{ session.device === 'desktop' ? '&#128187;' : '&#128241;' }}</span>
                  <div>
                    <p class="text-sm font-medium text-[var(--text-primary)]">
                      {{ session.browser }} on {{ session.os }}
                      <span v-if="session.current" class="badge badge-success ml-2">Current</span>
                    </p>
                    <p class="text-xs text-[var(--text-muted)]">
                      {{ session.ip }} &middot; Last active {{ session.last_active }}
                    </p>
                  </div>
                </div>
                <button
                  v-if="!session.current"
                  class="btn-ghost text-xs px-2 py-1 text-error hover:text-error"
                  @click="revokeSession(session.id)"
                >
                  Revoke
                </button>
              </div>
              <div v-if="sessions.length === 0" class="text-center py-4">
                <p class="text-sm text-[var(--text-muted)]">No active sessions.</p>
              </div>
            </div>
          </div>
        </div>

        <!-- API Keys Tab -->
        <div v-else-if="activeTab === 'apikeys'" class="space-y-6">
          <!-- Show newly generated key -->
          <div v-if="newApiKey" class="p-4 rounded-xl bg-success/10 border border-success/20">
            <div class="flex items-start gap-3">
              <span class="text-success text-lg">&#9989;</span>
              <div class="flex-1 min-w-0">
                <p class="text-sm font-medium text-success">API Key Generated</p>
                <p class="text-xs text-[var(--text-muted)] mt-1 mb-2">
                  Copy this key now. You will not be able to see it again.
                </p>
                <div class="flex items-center gap-2">
                  <code class="flex-1 text-sm font-mono text-[var(--text-primary)] bg-[var(--surface)] px-3 py-2 rounded border border-[var(--border)] truncate select-all">
                    {{ newApiKey }}
                  </code>
                  <button class="btn-secondary text-xs px-3 py-2" @click="copyKey(newApiKey)">
                    {{ copied ? 'Copied!' : 'Copy' }}
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div class="flex items-center justify-between">
            <h3 class="text-base font-semibold text-[var(--text-primary)]">Your API Keys</h3>
            <button class="btn-primary text-sm" @click="generateApiKey">
              <span class="text-lg leading-none mr-1">+</span> Generate New Key
            </button>
          </div>

          <div class="space-y-3">
            <div
              v-for="key in apiKeys"
              :key="key.id"
              class="flex items-center justify-between p-4 bg-[var(--surface)] rounded-xl border border-[var(--border)]"
            >
              <div>
                <p class="text-sm font-medium text-[var(--text-primary)] font-mono">
                  {{ key.prefix }}...{{ key.suffix }}
                </p>
                <p class="text-xs text-[var(--text-muted)] mt-0.5">
                  Created {{ formatDate(key.created_at) }}
                  <span v-if="key.last_used"> &middot; Last used {{ formatDate(key.last_used) }}</span>
                  <span v-else> &middot; Never used</span>
                </p>
              </div>
              <button
                class="btn-ghost text-xs px-2 py-1 text-error hover:text-error"
                @click="revokeApiKey(key.id)"
              >
                Revoke
              </button>
            </div>
            <div v-if="apiKeys.length === 0 && !newApiKey" class="text-center py-8">
              <div class="text-3xl mb-2 text-[var(--text-muted)]">&#128273;</div>
              <p class="text-sm text-[var(--text-muted)]">No API keys yet.</p>
            </div>
          </div>
        </div>

        <!-- Notifications Tab -->
        <div v-else-if="activeTab === 'notifications'" class="space-y-6 max-w-lg">
          <h3 class="text-base font-semibold text-[var(--text-primary)]">Email Notifications</h3>
          <p class="text-sm text-[var(--text-muted)]">Choose which events trigger email notifications.</p>

          <div class="space-y-4">
            <div
              v-for="pref in notificationPrefs"
              :key="pref.key"
              class="flex items-center justify-between p-4 bg-[var(--surface)] rounded-xl border border-[var(--border)]"
            >
              <div>
                <p class="text-sm font-medium text-[var(--text-primary)]">{{ pref.label }}</p>
                <p class="text-xs text-[var(--text-muted)] mt-0.5">{{ pref.description }}</p>
              </div>
              <button
                class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
                :class="pref.enabled ? 'bg-primary' : 'bg-[var(--border)]'"
                @click="toggleNotification(pref)"
              >
                <span
                  class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
                  :class="pref.enabled ? 'translate-x-6' : 'translate-x-1'"
                />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import client from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'

const auth = useAuthStore()
const notifications = useNotificationsStore()

const activeTab = ref('profile')

const tabs = [
  { id: 'profile', label: 'Profile' },
  { id: 'security', label: 'Security' },
  { id: 'apikeys', label: 'API Keys' },
  { id: 'notifications', label: 'Notifications' }
]

// Profile
const profileForm = ref({
  display_name: auth.user?.display_name || auth.user?.username || '',
  email: auth.user?.email || ''
})
const savingProfile = ref(false)

async function saveProfile() {
  savingProfile.value = true
  try {
    // NOTE: PUT /auth/me not implemented in backend yet; fails silently
    const { data } = await client.put('/auth/me', profileForm.value)
    auth.user = { ...auth.user, ...data }
    localStorage.setItem('hosthive_user', JSON.stringify(auth.user))
    notifications.success('Profile updated.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Profile update not available yet.')
  } finally {
    savingProfile.value = false
  }
}

// Password
const passwordForm = ref({ current: '', new_password: '', confirm: '' })
const savingPassword = ref(false)

async function changePassword() {
  if (passwordForm.value.new_password !== passwordForm.value.confirm) return
  savingPassword.value = true
  try {
    await client.post('/auth/change-password', {
      current_password: passwordForm.value.current,
      new_password: passwordForm.value.new_password
    })
    notifications.success('Password changed successfully.')
    passwordForm.value = { current: '', new_password: '', confirm: '' }
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to change password.')
  } finally {
    savingPassword.value = false
  }
}

// 2FA
const twoFA = reactive({
  enabled: false,
  showSetup: false,
  qrUrl: '',
  qrLoading: false,
  secret: '',
  verifyCode: '',
  verifying: false
})

async function setup2FA() {
  twoFA.showSetup = true
  twoFA.qrLoading = true
  try {
    const { data } = await client.post('/auth/2fa/setup')
    twoFA.qrUrl = data.qr_url || ''
    twoFA.secret = data.secret || ''
  } catch {
    notifications.error('Failed to setup 2FA.')
    twoFA.showSetup = false
  } finally {
    twoFA.qrLoading = false
  }
}

async function verify2FA() {
  if (twoFA.verifyCode.length !== 6) return
  twoFA.verifying = true
  try {
    await client.post('/auth/2fa/verify', { code: twoFA.verifyCode })
    twoFA.enabled = true
    twoFA.showSetup = false
    twoFA.verifyCode = ''
    notifications.success('Two-factor authentication enabled.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Invalid verification code.')
  } finally {
    twoFA.verifying = false
  }
}

async function disable2FA() {
  try {
    await client.post('/auth/2fa/disable')
    twoFA.enabled = false
    notifications.success('Two-factor authentication disabled.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to disable 2FA.')
  }
}

// Sessions
const sessions = ref([])

async function fetchSessions() {
  try {
    const { data } = await client.get('/auth/sessions')
    sessions.value = data
  } catch {
    sessions.value = []
  }
}

async function revokeSession(id) {
  if (!id) return
  try {
    await client.delete(`/auth/sessions/${id}`)
    sessions.value = sessions.value.filter(s => s.id !== id)
    notifications.success('Session revoked.')
  } catch {
    notifications.error('Failed to revoke session.')
  }
}

// API Keys
const apiKeys = ref([])
const newApiKey = ref('')
const copied = ref(false)

async function fetchApiKeys() {
  try {
    const { data } = await client.get('/api-keys')
    apiKeys.value = data
  } catch {
    apiKeys.value = []
  }
}

async function generateApiKey() {
  try {
    const { data } = await client.post('/api-keys', { name: 'Default API Key', scope: 'read_only' })
    newApiKey.value = data.key
    if (data.id) {
      apiKeys.value.unshift({
        id: data.id,
        prefix: data.key.substring(0, 8),
        suffix: data.key.substring(data.key.length - 4),
        created_at: new Date().toISOString(),
        last_used: null
      })
    }
    notifications.success('API key generated.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to generate API key.')
  }
}

async function revokeApiKey(id) {
  if (!id) return
  try {
    await client.delete(`/api-keys/${id}`)
    apiKeys.value = apiKeys.value.filter(k => k.id !== id)
    notifications.success('API key revoked.')
  } catch {
    notifications.error('Failed to revoke API key.')
  }
}

function copyKey(key) {
  navigator.clipboard.writeText(key)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}

// Notifications
const notificationPrefs = ref([
  { key: 'ssl_expiry', label: 'SSL Certificate Expiry', description: 'Get notified when an SSL certificate is about to expire.', enabled: true },
  { key: 'backup_complete', label: 'Backup Complete', description: 'Get notified when a backup finishes successfully.', enabled: true },
  { key: 'service_down', label: 'Service Down', description: 'Get notified when a monitored service goes offline.', enabled: true }
])

async function toggleNotification(pref) {
  pref.enabled = !pref.enabled
  try {
    await client.put('/settings/notifications', {
      [pref.key]: pref.enabled
    })
  } catch {
    pref.enabled = !pref.enabled
    notifications.error('Failed to update notification preferences.')
  }
}

async function fetchNotificationPrefs() {
  try {
    const { data } = await client.get('/settings/notifications')
    if (data) {
      for (const pref of notificationPrefs.value) {
        if (data[pref.key] !== undefined) {
          pref.enabled = data[pref.key]
        }
      }
    }
  } catch {
    // Use defaults
  }
}

async function fetch2FAStatus() {
  try {
    const { data } = await client.get('/auth/2fa/status')
    twoFA.enabled = data.enabled || false
  } catch {
    // Assume disabled
  }
}

function formatDate(dateStr) {
  if (!dateStr) return '--'
  return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

onMounted(() => {
  fetchSessions()
  fetchApiKeys()
  fetchNotificationPrefs()
  fetch2FAStatus()
})
</script>
