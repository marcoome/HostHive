<template>
  <div class="fixed top-4 right-4 z-[100] flex flex-col gap-2">
    <TransitionGroup name="toast">
      <Toast
        v-for="toast in notifications.toasts"
        :key="toast.id"
        :type="toast.type"
        :message="toast.message"
        @dismiss="notifications.remove(toast.id)"
      />
    </TransitionGroup>
  </div>
</template>

<script setup>
import { useNotificationsStore } from '@/stores/notifications'
import Toast from './Toast.vue'

const notifications = useNotificationsStore()
</script>

<style scoped>
.toast-enter-active {
  transition: all 0.3s ease-out;
}
.toast-leave-active {
  transition: all 0.2s ease-in;
}
.toast-enter-from {
  opacity: 0;
  transform: translateX(100%);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(100%);
}
.toast-move {
  transition: transform 0.2s ease;
}
</style>
