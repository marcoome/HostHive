<template>
  <div class="min-h-screen flex items-center justify-center bg-background">
    <div class="w-full max-w-md mx-4">
      <div class="card">
        <h1 class="text-xl font-semibold text-text-primary mb-2">Reset Password</h1>
        <p class="text-sm text-text-muted mb-6">Enter your email to receive a new password.</p>

        <div v-if="success" class="p-4 rounded-lg bg-green-500/10 border border-green-500/30 mb-4">
          <p class="text-sm text-green-400">If an account exists with that email, a new password has been sent.</p>
        </div>

        <form v-if="!success" @submit.prevent="handleReset" class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-text-muted mb-1">Email</label>
            <input
              v-model="email"
              type="email"
              required
              class="input w-full"
              placeholder="admin@example.com"
              :disabled="loading"
            />
          </div>

          <div v-if="error" class="text-sm text-red-400">{{ error }}</div>

          <button type="submit" class="btn-primary w-full" :disabled="loading">
            {{ loading ? 'Sending...' : 'Reset Password' }}
          </button>
        </form>

        <router-link to="/login" class="link text-sm mt-4 inline-block">Back to login</router-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import api from '@/api/client'

const email = ref('')
const loading = ref(false)
const error = ref('')
const success = ref(false)

async function handleReset() {
  loading.value = true
  error.value = ''
  try {
    await api.post('/api/v1/auth/forgot-password', { email: email.value })
    success.value = true
  } catch (err) {
    // Always show success to prevent email enumeration
    success.value = true
  } finally {
    loading.value = false
  }
}
</script>
