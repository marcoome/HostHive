<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">
        {{ $t('nav.rate_limits', 'Rate Limits') }}
      </h1>
      <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">
        Configure API and resource rate limits applied to your sub-users.
      </p>
    </div>

    <form class="card p-6 space-y-4" @submit.prevent="save">
      <div>
        <label class="block text-sm font-medium mb-1" :style="{ color: 'var(--text-primary)' }">
          API requests per minute
        </label>
        <input
          v-model.number="form.api_per_minute"
          type="number"
          min="0"
          class="input w-full"
        />
      </div>

      <div>
        <label class="block text-sm font-medium mb-1" :style="{ color: 'var(--text-primary)' }">
          Max concurrent connections
        </label>
        <input
          v-model.number="form.max_connections"
          type="number"
          min="0"
          class="input w-full"
        />
      </div>

      <div>
        <label class="block text-sm font-medium mb-1" :style="{ color: 'var(--text-primary)' }">
          Email send limit (per hour)
        </label>
        <input
          v-model.number="form.email_per_hour"
          type="number"
          min="0"
          class="input w-full"
        />
      </div>

      <div>
        <label class="block text-sm font-medium mb-1" :style="{ color: 'var(--text-primary)' }">
          CPU burst limit (%)
        </label>
        <input
          v-model.number="form.cpu_burst"
          type="number"
          min="0"
          max="100"
          class="input w-full"
        />
      </div>

      <div class="flex justify-end gap-2 pt-2">
        <button type="button" class="btn-secondary text-sm" @click="reset">Reset</button>
        <button type="submit" class="btn-primary text-sm" :disabled="saving">
          {{ saving ? 'Saving...' : 'Save Limits' }}
        </button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import client from '@/api/client'

const saving = ref(false)
const form = ref({
  api_per_minute: 60,
  max_connections: 100,
  email_per_hour: 200,
  cpu_burst: 50
})

async function fetchLimits() {
  try {
    const { data } = await client.get('/reseller/rate-limits')
    if (data) form.value = { ...form.value, ...data }
  } catch {
    // Use defaults
  }
}

async function save() {
  saving.value = true
  try {
    await client.put('/reseller/rate-limits', form.value)
  } finally {
    saving.value = false
  }
}

function reset() {
  fetchLimits()
}

onMounted(fetchLimits)
</script>
