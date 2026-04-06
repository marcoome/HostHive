<template>
  <div class="min-h-screen flex items-center justify-center relative overflow-hidden">
    <!-- Animated gradient background -->
    <div class="absolute inset-0 animated-bg"></div>
    <div class="absolute inset-0" :style="{ background: 'rgba(var(--bg-rgb), 0.75)', backdropFilter: 'blur(2px)' }"></div>

    <!-- Parallax shapes -->
    <ParallaxBackground />

    <!-- Theme toggle corner -->
    <button
      class="fixed top-5 right-5 z-50 p-2.5 rounded-xl glass"
      @click="themeStore.toggleTheme()"
      :title="themeStore.isDark ? 'Switch to light mode' : 'Switch to dark mode'"
    >
      <template v-if="themeStore.isDark">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" :style="{ color: 'var(--warning)' }">
          <circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
        </svg>
      </template>
      <template v-else>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" :style="{ color: 'var(--primary)' }">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
        </svg>
      </template>
    </button>

    <!-- Login card -->
    <div class="relative z-10 w-full max-w-md mx-4">
      <div class="glass-strong rounded-2xl shadow-2xl p-8">
        <!-- Logo -->
        <div class="text-center mb-8">
          <div class="flex justify-center mb-4">
            <LogoText class="h-12" />
          </div>
          <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">
            {{ step === '2fa' ? 'Two-factor authentication' : 'Sign in to your control panel' }}
          </p>
        </div>

        <!-- Error message -->
        <div
          v-if="errorMessage"
          class="mb-6 px-4 py-3 rounded-lg text-sm"
          :style="{
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            color: 'var(--error)'
          }"
        >
          {{ errorMessage }}
        </div>

        <!-- Step 1: Credentials -->
        <template v-if="step === 'credentials'">
          <form @submit.prevent="handleLogin" class="space-y-5">
            <div>
              <label for="username" class="input-label">Username</label>
              <input
                id="username"
                v-model="username"
                type="text"
                placeholder="Enter your username"
                autocomplete="username"
                required
                class="w-full"
                :disabled="loading"
              />
            </div>

            <div>
              <label for="password" class="input-label">Password</label>
              <input
                id="password"
                v-model="password"
                type="password"
                placeholder="Enter your password"
                autocomplete="current-password"
                required
                class="w-full"
                :disabled="loading"
              />
            </div>

            <div class="flex items-center justify-between">
              <label class="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  v-model="remember"
                  class="w-4 h-4 rounded"
                />
                <span class="text-sm" :style="{ color: 'var(--text-muted)' }">Remember me</span>
              </label>
              <router-link to="/forgot-password" class="text-sm link">
                Forgot password?
              </router-link>
            </div>

            <button
              type="submit"
              class="btn-primary w-full py-2.5"
              :disabled="loading || !username || !password"
            >
              <span v-if="loading" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
              <span v-else>Sign in</span>
            </button>
          </form>

          <!-- Divider -->
          <div class="relative my-6">
            <div class="absolute inset-0 flex items-center">
              <div class="w-full border-t" :style="{ borderColor: 'var(--border)' }"></div>
            </div>
            <div class="relative flex justify-center text-xs">
              <span class="px-3" :style="{ background: 'var(--surface)', color: 'var(--text-muted)' }">or</span>
            </div>
          </div>

          <!-- Passkey button -->
          <button
            type="button"
            class="btn-secondary w-full py-2.5 flex items-center justify-center gap-2"
            :disabled="loading"
            @click="handlePasskeyLogin"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M2 18v3c0 .6.4 1 1 1h4v-3h3v-3h2l1.4-1.4a6.5 6.5 0 1 0-4-4Z"/>
              <circle cx="16.5" cy="7.5" r=".5" fill="currentColor"/>
            </svg>
            <span>Sign in with Passkey</span>
          </button>
        </template>

        <!-- Step 2: Two-Factor Authentication -->
        <template v-if="step === '2fa'">
          <form @submit.prevent="handle2FA" class="space-y-5">
            <template v-if="!useBackupCode">
              <div>
                <label for="totp-code" class="input-label">Authentication Code</label>
                <p class="text-xs mb-2" :style="{ color: 'var(--text-muted)' }">
                  Enter the 6-digit code from your authenticator app.
                </p>
                <input
                  id="totp-code"
                  ref="totpInput"
                  v-model="totpCode"
                  type="text"
                  inputmode="numeric"
                  maxlength="6"
                  placeholder="000000"
                  autocomplete="one-time-code"
                  required
                  class="w-full text-center text-lg tracking-[0.5em] font-mono"
                  :disabled="loading"
                  @input="onTotpInput"
                />
              </div>
            </template>

            <template v-else>
              <div>
                <label for="backup-code" class="input-label">Backup Code</label>
                <p class="text-xs mb-2" :style="{ color: 'var(--text-muted)' }">
                  Enter one of your backup recovery codes.
                </p>
                <input
                  id="backup-code"
                  ref="backupInput"
                  v-model="backupCode"
                  type="text"
                  placeholder="xxxx-xxxx-xxxx"
                  autocomplete="off"
                  required
                  class="w-full text-center font-mono"
                  :disabled="loading"
                />
              </div>
            </template>

            <button
              type="submit"
              class="btn-primary w-full py-2.5"
              :disabled="loading || (!useBackupCode && totpCode.length !== 6) || (useBackupCode && !backupCode)"
            >
              <span v-if="loading" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
              <span v-else>Verify</span>
            </button>

            <div class="text-center">
              <button
                type="button"
                class="text-sm link"
                @click="toggleBackupCode"
              >
                {{ useBackupCode ? 'Use authenticator code' : 'Use backup code' }}
              </button>
            </div>

            <div class="text-center">
              <button
                type="button"
                class="text-sm link"
                @click="backToCredentials"
              >
                Back to sign in
              </button>
            </div>
          </form>
        </template>
      </div>

      <p class="text-center text-xs mt-6" :style="{ color: 'var(--text-muted)' }">
        HostHive Control Panel &middot; Secure Server Management
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'
import { useThemeStore } from '@/stores/theme'
import ParallaxBackground from '@/components/ParallaxBackground.vue'
import LogoText from '@/components/LogoText.vue'
import client from '@/api/client'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const notifications = useNotificationsStore()
const themeStore = useThemeStore()

const username = ref('')
const password = ref('')
const remember = ref(false)
const loading = ref(false)
const errorMessage = ref('')

// 2FA state
const step = ref('credentials') // 'credentials' | '2fa'
const totpCode = ref('')
const backupCode = ref('')
const useBackupCode = ref(false)
const totpInput = ref(null)
const backupInput = ref(null)

function navigateAfterLogin() {
  notifications.success('Welcome back!')
  const redirect = route.query.redirect || '/dashboard'
  router.push(redirect)
}

async function handleLogin() {
  if (!username.value || !password.value) return

  loading.value = true
  errorMessage.value = ''

  try {
    const data = await auth.login(username.value, password.value)
    if (data.requires_2fa) {
      step.value = '2fa'
      await nextTick()
      totpInput.value?.focus()
    } else {
      navigateAfterLogin()
    }
  } catch (err) {
    const msg = err.response?.data?.detail || err.response?.data?.message || 'Invalid credentials. Please try again.'
    errorMessage.value = msg
  } finally {
    loading.value = false
  }
}

function onTotpInput() {
  // Strip non-digits
  totpCode.value = totpCode.value.replace(/\D/g, '')
}

async function handle2FA() {
  const code = useBackupCode.value ? backupCode.value.trim() : totpCode.value.trim()
  if (!code) return

  loading.value = true
  errorMessage.value = ''

  try {
    await auth.verify2FA(code, useBackupCode.value)
    navigateAfterLogin()
  } catch (err) {
    const msg = err.response?.data?.detail || err.response?.data?.message || 'Invalid verification code. Please try again.'
    errorMessage.value = msg
  } finally {
    loading.value = false
  }
}

function toggleBackupCode() {
  useBackupCode.value = !useBackupCode.value
  errorMessage.value = ''
  nextTick(() => {
    if (useBackupCode.value) {
      backupInput.value?.focus()
    } else {
      totpInput.value?.focus()
    }
  })
}

function backToCredentials() {
  step.value = 'credentials'
  totpCode.value = ''
  backupCode.value = ''
  useBackupCode.value = false
  errorMessage.value = ''
  auth.clear2FAState()
}

// --- WebAuthn / Passkey Login ---

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

async function handlePasskeyLogin() {
  loading.value = true
  errorMessage.value = ''

  try {
    // 1. Get challenge options from the server
    const { data: options } = await client.post('/auth/webauthn/authenticate/options')

    // 2. Prepare the credential request
    const publicKeyOptions = {
      challenge: base64UrlToBuffer(options.challenge),
      timeout: options.timeout || 60000,
      rpId: options.rpId || window.location.hostname,
      userVerification: options.userVerification || 'preferred'
    }

    if (options.allowCredentials && options.allowCredentials.length > 0) {
      publicKeyOptions.allowCredentials = options.allowCredentials.map(cred => ({
        id: base64UrlToBuffer(cred.id),
        type: cred.type || 'public-key',
        transports: cred.transports
      }))
    }

    // 3. Call WebAuthn browser API
    const credential = await navigator.credentials.get({ publicKey: publicKeyOptions })

    // 4. Send assertion to server
    const assertionPayload = {
      id: credential.id,
      rawId: bufferToBase64Url(credential.rawId),
      type: credential.type,
      response: {
        authenticatorData: bufferToBase64Url(credential.response.authenticatorData),
        clientDataJSON: bufferToBase64Url(credential.response.clientDataJSON),
        signature: bufferToBase64Url(credential.response.signature),
        userHandle: credential.response.userHandle
          ? bufferToBase64Url(credential.response.userHandle)
          : null
      }
    }

    const data = await auth.webauthnLogin(assertionPayload)

    if (data.requires_2fa) {
      step.value = '2fa'
      await nextTick()
      totpInput.value?.focus()
    } else {
      navigateAfterLogin()
    }
  } catch (err) {
    if (err.name === 'NotAllowedError') {
      errorMessage.value = 'Passkey authentication was cancelled or not allowed.'
    } else if (err.name === 'SecurityError') {
      errorMessage.value = 'Passkey authentication is not available on this connection.'
    } else {
      const msg = err.response?.data?.detail || err.response?.data?.message || 'Passkey authentication failed. Please try again.'
      errorMessage.value = msg
    }
  } finally {
    loading.value = false
  }
}
</script>
