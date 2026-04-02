<template>
  <div v-if="auth.impersonating" class="impersonation-banner">
    <div class="impersonation-content">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
        <circle cx="12" cy="12" r="3"/>
      </svg>
      <span>{{ $t('impersonation.viewing_as', { username: auth.impersonatedUser?.username || '...' }) }}</span>
    </div>
    <button class="impersonation-return" @click="auth.stopImpersonation()">
      {{ $t('impersonation.return_to_admin') }}
    </button>
  </div>
</template>

<script setup>
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
</script>

<style scoped>
.impersonation-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 24px;
  background: linear-gradient(135deg, #f59e0b, #d97706);
  color: #1a1a1a;
  font-size: 0.875rem;
  font-weight: 500;
  z-index: 9999;
  position: relative;
}

.impersonation-content {
  display: flex;
  align-items: center;
  gap: 8px;
}

.impersonation-return {
  padding: 4px 16px;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.15);
  color: #1a1a1a;
  font-size: 0.8rem;
  font-weight: 600;
  border: 1px solid rgba(0, 0, 0, 0.2);
  cursor: pointer;
  transition: all 0.15s ease;
}

.impersonation-return:hover {
  background: rgba(0, 0, 0, 0.25);
}
</style>
