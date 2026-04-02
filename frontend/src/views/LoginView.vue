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
          <div class="inline-flex items-center justify-center w-14 h-14 rounded-xl mb-4" style="background: var(--primary);">
            <span class="text-white font-bold text-2xl">H</span>
          </div>
          <h1 class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">HostHive</h1>
          <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">Sign in to your control panel</p>
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

        <!-- Form -->
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
      </div>

      <p class="text-center text-xs mt-6" :style="{ color: 'var(--text-muted)' }">
        HostHive Control Panel &middot; Secure Server Management
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'
import { useThemeStore } from '@/stores/theme'
import ParallaxBackground from '@/components/ParallaxBackground.vue'

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

async function handleLogin() {
  if (!username.value || !password.value) return

  loading.value = true
  errorMessage.value = ''

  try {
    await auth.login(username.value, password.value)
    notifications.success('Welcome back!')
    const redirect = route.query.redirect || '/dashboard'
    router.push(redirect)
  } catch (err) {
    const msg = err.response?.data?.detail || err.response?.data?.message || 'Invalid credentials. Please try again.'
    errorMessage.value = msg
  } finally {
    loading.value = false
  }
}
</script>
