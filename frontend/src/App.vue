<template>
  <router-view />
</template>

<script setup>
import { useNotificationsStore } from '@/stores/notifications'
import { useThemeStore } from '@/stores/theme'

const notifications = useNotificationsStore()
// Initialize theme on app start so the class is applied to documentElement immediately
const theme = useThemeStore()
</script>
