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

            <!-- Enable 2FA button -->
            <div v-if="!twoFA.enabled && !twoFA.showSetup">
              <button class="btn-primary" @click="setup2FA">Enable 2FA</button>
            </div>

            <!-- 2FA Setup flow -->
            <div v-else-if="twoFA.showSetup" class="space-y-4">
              <!-- Step: QR code + verify -->
              <template v-if="!twoFA.showBackupCodes">
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
                    inputmode="numeric"
                    maxlength="6"
                    placeholder="000000"
                    class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] font-mono text-center text-lg tracking-[0.5em] focus:outline-none focus:ring-2 focus:ring-primary/50"
                    @input="twoFA.verifyCode = twoFA.verifyCode.replace(/\D/g, '')"
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
              </template>

              <!-- Step: Show backup codes (one-time view) -->
              <template v-else>
                <div class="p-4 rounded-xl bg-warning/10 border border-warning/20">
                  <div class="flex items-start gap-3">
                    <span class="text-warning text-lg">&#9888;</span>
                    <div>
                      <p class="text-sm font-medium text-[var(--text-primary)]">Save your backup codes</p>
                      <p class="text-xs text-[var(--text-muted)] mt-1">
                        These codes can be used to access your account if you lose your authenticator device. Each code can only be used once. Store them securely -- you will not be able to see them again.
                      </p>
                    </div>
                  </div>
                </div>

                <div class="grid grid-cols-2 gap-2 p-4 bg-[var(--surface)] border border-[var(--border)] rounded-xl">
                  <code
                    v-for="(code, idx) in twoFA.backupCodes"
                    :key="idx"
                    class="text-sm font-mono text-[var(--text-primary)] text-center py-1.5 px-2 bg-[var(--background)] rounded"
                  >
                    {{ code }}
                  </code>
                </div>

                <div class="flex gap-3">
                  <button
                    class="btn-secondary flex items-center gap-1.5"
                    @click="copyBackupCodes"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                    </svg>
                    {{ twoFA.copiedBackup ? 'Copied!' : 'Copy codes' }}
                  </button>
                  <button class="btn-primary" @click="finishSetup">Done</button>
                </div>
              </template>
            </div>

            <!-- 2FA is enabled: disable button -->
            <div v-else-if="twoFA.enabled">
              <button class="btn-danger" @click="showDisable2FAModal = true">Disable 2FA</button>
            </div>
          </div>

          <!-- Disable 2FA Modal -->
          <Modal v-model="showDisable2FAModal" title="Disable Two-Factor Authentication" size="sm">
            <p class="text-sm text-[var(--text-muted)] mb-4">
              Enter your current authenticator code to confirm disabling 2FA.
            </p>
            <input
              v-model="disable2FACode"
              type="text"
              inputmode="numeric"
              maxlength="6"
              placeholder="000000"
              class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] font-mono text-center text-lg tracking-[0.5em] focus:outline-none focus:ring-2 focus:ring-primary/50"
              @input="disable2FACode = disable2FACode.replace(/\D/g, '')"
            />
            <template #actions>
              <button class="btn-secondary" @click="showDisable2FAModal = false">Cancel</button>
              <button
                class="btn-danger"
                :disabled="disable2FACode.length !== 6 || disabling2FA"
                @click="disable2FA"
              >
                <span v-if="disabling2FA" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
                {{ disabling2FA ? 'Disabling...' : 'Disable 2FA' }}
              </button>
            </template>
          </Modal>

          <!-- WebAuthn / Passkeys -->
          <div class="border-t border-[var(--border)] pt-8">
            <div class="flex items-center justify-between mb-4">
              <div>
                <h3 class="text-base font-semibold text-[var(--text-primary)] mb-1">Passkeys</h3>
                <p class="text-sm text-[var(--text-muted)]">
                  Use biometrics, security keys, or your device to sign in without a password.
                </p>
              </div>
              <button class="btn-primary text-sm" @click="addPasskey">
                <span class="text-lg leading-none mr-1">+</span> Add Passkey
              </button>
            </div>

            <div class="space-y-3">
              <div
                v-for="credential in passkeys"
                :key="credential.id"
                class="flex items-center justify-between p-4 bg-[var(--surface)] rounded-xl border border-[var(--border)]"
              >
                <div class="flex items-center gap-3">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-[var(--text-muted)]">
                    <path d="M2 18v3c0 .6.4 1 1 1h4v-3h3v-3h2l1.4-1.4a6.5 6.5 0 1 0-4-4Z"/>
                    <circle cx="16.5" cy="7.5" r=".5" fill="currentColor"/>
                  </svg>
                  <div>
                    <p class="text-sm font-medium text-[var(--text-primary)]">{{ credential.name || 'Unnamed Passkey' }}</p>
                    <p class="text-xs text-[var(--text-muted)]">
                      Added {{ formatDate(credential.created_at) }}
                      <span v-if="credential.last_used"> &middot; Last used {{ formatDate(credential.last_used) }}</span>
                      <span v-else> &middot; Never used</span>
                    </p>
                  </div>
                </div>
                <button
                  class="btn-ghost text-xs px-2 py-1 text-error hover:text-error"
                  @click="deletePasskey(credential.id)"
                >
                  Remove
                </button>
              </div>

              <div v-if="passkeys.length === 0" class="text-center py-8">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="mx-auto mb-2 text-[var(--text-muted)]">
                  <path d="M2 18v3c0 .6.4 1 1 1h4v-3h3v-3h2l1.4-1.4a6.5 6.5 0 1 0-4-4Z"/>
                  <circle cx="16.5" cy="7.5" r=".5" fill="currentColor"/>
                </svg>
                <p class="text-sm text-[var(--text-muted)]">No passkeys registered yet.</p>
              </div>
            </div>
          </div>

          <!-- Add Passkey Modal -->
          <Modal v-model="showAddPasskeyModal" title="Register Passkey" size="sm">
            <div class="space-y-4">
              <div>
                <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Device Name</label>
                <input
                  v-model="passkeyName"
                  type="text"
                  placeholder='e.g. "MacBook Pro", "YubiKey"'
                  class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
              </div>
              <p v-if="passkeyRegistering" class="text-sm text-[var(--text-muted)] text-center py-2">
                Follow your browser's prompt to register your passkey...
              </p>
            </div>
            <template #actions>
              <button class="btn-secondary" @click="showAddPasskeyModal = false" :disabled="passkeyRegistering">Cancel</button>
              <button
                class="btn-primary"
                :disabled="!passkeyName.trim() || passkeyRegistering"
                @click="registerPasskey"
              >
                <span v-if="passkeyRegistering" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
                {{ passkeyRegistering ? 'Waiting...' : 'Register' }}
              </button>
            </template>
          </Modal>

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
import Modal from '@/components/Modal.vue'

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
  showBackupCodes: false,
  qrUrl: '',
  qrLoading: false,
  secret: '',
  verifyCode: '',
  verifying: false,
  backupCodes: [],
  copiedBackup: false
})

const showDisable2FAModal = ref(false)
const disable2FACode = ref('')
const disabling2FA = ref(false)

async function setup2FA() {
  twoFA.showSetup = true
  twoFA.showBackupCodes = false
  twoFA.qrLoading = true
  twoFA.verifyCode = ''
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
    const { data } = await client.post('/auth/2fa/verify', { code: twoFA.verifyCode })
    twoFA.enabled = true
    twoFA.verifyCode = ''
    // Show backup codes if server returned them
    if (data.backup_codes && data.backup_codes.length > 0) {
      twoFA.backupCodes = data.backup_codes
      twoFA.showBackupCodes = true
    } else {
      twoFA.showSetup = false
      notifications.success('Two-factor authentication enabled.')
    }
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Invalid verification code.')
  } finally {
    twoFA.verifying = false
  }
}

function copyBackupCodes() {
  const text = twoFA.backupCodes.join('\n')
  navigator.clipboard.writeText(text)
  twoFA.copiedBackup = true
  setTimeout(() => { twoFA.copiedBackup = false }, 2000)
}

function finishSetup() {
  twoFA.showSetup = false
  twoFA.showBackupCodes = false
  twoFA.backupCodes = []
  notifications.success('Two-factor authentication enabled. Keep your backup codes safe!')
}

async function disable2FA() {
  if (disable2FACode.value.length !== 6) return
  disabling2FA.value = true
  try {
    await client.post('/auth/2fa/disable', { code: disable2FACode.value })
    twoFA.enabled = false
    showDisable2FAModal.value = false
    disable2FACode.value = ''
    notifications.success('Two-factor authentication disabled.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Invalid code. Failed to disable 2FA.')
  } finally {
    disabling2FA.value = false
  }
}

// WebAuthn / Passkeys
const passkeys = ref([])
const showAddPasskeyModal = ref(false)
const passkeyName = ref('')
const passkeyRegistering = ref(false)

function base64UrlToBuffer(base64url) {
  const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/')
  const pad = base64.length % 4 === 0 ? '' : '='.repeat(4 - (base64.length % 4))
  const binary = atob(base64 + pad)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes.buffer
}

function bufferToBase64Url(buffer) {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (const byte of bytes) {
    binary += String.fromCharCode(byte)
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

async function fetchPasskeys() {
  try {
    const { data } = await client.get('/auth/webauthn/credentials')
    passkeys.value = data
  } catch {
    passkeys.value = []
  }
}

function addPasskey() {
  passkeyName.value = ''
  passkeyRegistering.value = false
  showAddPasskeyModal.value = true
}

async function registerPasskey() {
  if (!passkeyName.value.trim()) return
  passkeyRegistering.value = true

  try {
    // 1. Get registration options from server
    const { data: options } = await client.post('/auth/webauthn/register/options')

    // 2. Prepare creation options
    const publicKeyOptions = {
      challenge: base64UrlToBuffer(options.challenge),
      rp: {
        name: options.rp?.name || 'HostHive',
        id: options.rp?.id || window.location.hostname
      },
      user: {
        id: base64UrlToBuffer(options.user.id),
        name: options.user.name,
        displayName: options.user.displayName
      },
      pubKeyCredParams: options.pubKeyCredParams || [
        { type: 'public-key', alg: -7 },
        { type: 'public-key', alg: -257 }
      ],
      timeout: options.timeout || 60000,
      authenticatorSelection: options.authenticatorSelection || {
        authenticatorAttachment: 'platform',
        residentKey: 'preferred',
        userVerification: 'preferred'
      },
      attestation: options.attestation || 'none'
    }

    if (options.excludeCredentials && options.excludeCredentials.length > 0) {
      publicKeyOptions.excludeCredentials = options.excludeCredentials.map(cred => ({
        id: base64UrlToBuffer(cred.id),
        type: cred.type || 'public-key',
        transports: cred.transports
      }))
    }

    // 3. Call WebAuthn browser API
    const credential = await navigator.credentials.create({ publicKey: publicKeyOptions })

    // 4. Send attestation to server
    const attestationPayload = {
      id: credential.id,
      rawId: bufferToBase64Url(credential.rawId),
      type: credential.type,
      name: passkeyName.value.trim(),
      response: {
        attestationObject: bufferToBase64Url(credential.response.attestationObject),
        clientDataJSON: bufferToBase64Url(credential.response.clientDataJSON)
      }
    }

    const { data: saved } = await client.post('/auth/webauthn/register', attestationPayload)

    passkeys.value.unshift({
      id: saved.id,
      name: passkeyName.value.trim(),
      created_at: new Date().toISOString(),
      last_used: null,
      ...saved
    })

    showAddPasskeyModal.value = false
    passkeyName.value = ''
    notifications.success('Passkey registered successfully.')
  } catch (err) {
    if (err.name === 'NotAllowedError') {
      notifications.error('Passkey registration was cancelled.')
    } else if (err.name === 'InvalidStateError') {
      notifications.error('This device is already registered as a passkey.')
    } else {
      notifications.error(err.response?.data?.detail || 'Failed to register passkey.')
    }
  } finally {
    passkeyRegistering.value = false
  }
}

async function deletePasskey(id) {
  if (!id) return
  try {
    await client.delete(`/auth/webauthn/credentials/${id}`)
    passkeys.value = passkeys.value.filter(p => p.id !== id)
    notifications.success('Passkey removed.')
  } catch {
    notifications.error('Failed to remove passkey.')
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
  fetchPasskeys()
})
</script>
