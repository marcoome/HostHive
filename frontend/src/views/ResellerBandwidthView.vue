<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">
        {{ $t('nav.bandwidth', 'Bandwidth & Usage') }}
      </h1>
      <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">
        Aggregate bandwidth and disk usage across all your sub-users.
      </p>
    </div>

    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <div v-for="card in stats" :key="card.label" class="card py-4 px-4">
        <p class="text-xs" :style="{ color: 'var(--text-muted)' }">{{ card.label }}</p>
        <p class="text-2xl font-semibold mt-1" :style="{ color: 'var(--text-primary)' }">
          {{ card.value }}
        </p>
        <p class="text-xs mt-1" :style="{ color: 'var(--text-muted)' }">{{ card.hint }}</p>
      </div>
    </div>

    <div class="card p-6">
      <h2 class="text-lg font-semibold mb-4" :style="{ color: 'var(--text-primary)' }">
        Per-user usage
      </h2>
      <div v-if="loading" class="space-y-3">
        <div class="skeleton w-full h-10 rounded"></div>
        <div class="skeleton w-full h-10 rounded"></div>
      </div>
      <div v-else-if="users.length === 0" class="text-center py-8" :style="{ color: 'var(--text-muted)' }">
        No usage data available yet.
      </div>
      <table v-else class="w-full text-sm">
        <thead>
          <tr :style="{ color: 'var(--text-muted)' }" class="text-left">
            <th class="pb-3 font-medium">User</th>
            <th class="pb-3 font-medium">Bandwidth</th>
            <th class="pb-3 font-medium">Disk</th>
            <th class="pb-3 font-medium">Quota</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="u in users"
            :key="u.id"
            class="border-t"
            :style="{ borderColor: 'rgba(var(--border-rgb), 0.3)' }"
          >
            <td class="py-3" :style="{ color: 'var(--text-primary)' }">{{ u.username }}</td>
            <td class="py-3">{{ u.bandwidth_used }} GB</td>
            <td class="py-3">{{ u.disk_used }} MB</td>
            <td class="py-3">{{ u.quota_pct }}%</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import client from '@/api/client'

const loading = ref(true)
const users = ref([])
const stats = ref([
  { label: 'Total Bandwidth', value: '-', hint: 'this month' },
  { label: 'Total Disk', value: '-', hint: 'across users' },
  { label: 'Active Users', value: '-', hint: 'last 30 days' },
  { label: 'Quota Used', value: '-', hint: 'of plan' }
])

async function fetchUsage() {
  loading.value = true
  try {
    const { data } = await client.get('/reseller/usage')
    users.value = data?.users || []
    if (data?.stats) {
      stats.value[0].value = `${data.stats.bandwidth_total ?? 0} GB`
      stats.value[1].value = `${data.stats.disk_total ?? 0} MB`
      stats.value[2].value = data.stats.active_users ?? 0
      stats.value[3].value = `${data.stats.quota_pct ?? 0}%`
    }
  } catch {
    users.value = []
  } finally {
    loading.value = false
  }
}

onMounted(fetchUsage)
</script>
