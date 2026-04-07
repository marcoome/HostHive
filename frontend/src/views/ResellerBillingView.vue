<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">
        {{ $t('nav.billing', 'Billing') }}
      </h1>
      <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">
        Your reseller plan, invoices and payment methods.
      </p>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div class="card p-6 lg:col-span-2">
        <h2 class="text-lg font-semibold mb-4" :style="{ color: 'var(--text-primary)' }">Current Plan</h2>
        <div v-if="loading" class="skeleton h-20 w-full rounded"></div>
        <div v-else>
          <p class="text-3xl font-semibold" :style="{ color: 'var(--text-primary)' }">
            {{ plan.name || 'Reseller Pro' }}
          </p>
          <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">
            ${{ plan.price || 0 }} / month
          </p>
          <p class="text-xs mt-2" :style="{ color: 'var(--text-muted)' }">
            Renews on {{ plan.next_renewal || '-' }}
          </p>
        </div>
      </div>

      <div class="card p-6">
        <h2 class="text-lg font-semibold mb-4" :style="{ color: 'var(--text-primary)' }">Balance</h2>
        <p class="text-3xl font-semibold" :style="{ color: 'var(--text-primary)' }">
          ${{ balance }}
        </p>
        <button class="btn-primary text-sm mt-4 w-full">Add Funds</button>
      </div>
    </div>

    <div class="card p-6">
      <h2 class="text-lg font-semibold mb-4" :style="{ color: 'var(--text-primary)' }">Invoices</h2>
      <div v-if="loading" class="space-y-3">
        <div class="skeleton h-10 w-full rounded"></div>
        <div class="skeleton h-10 w-full rounded"></div>
      </div>
      <div v-else-if="invoices.length === 0" class="text-center py-8" :style="{ color: 'var(--text-muted)' }">
        No invoices yet.
      </div>
      <table v-else class="w-full text-sm">
        <thead>
          <tr :style="{ color: 'var(--text-muted)' }" class="text-left">
            <th class="pb-3 font-medium">Invoice</th>
            <th class="pb-3 font-medium">Date</th>
            <th class="pb-3 font-medium">Amount</th>
            <th class="pb-3 font-medium">Status</th>
            <th class="pb-3 font-medium"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="inv in invoices"
            :key="inv.id"
            class="border-t"
            :style="{ borderColor: 'rgba(var(--border-rgb), 0.3)' }"
          >
            <td class="py-3" :style="{ color: 'var(--text-primary)' }">#{{ inv.number }}</td>
            <td class="py-3">{{ inv.date }}</td>
            <td class="py-3">${{ inv.amount }}</td>
            <td class="py-3">{{ inv.status }}</td>
            <td class="py-3 text-right">
              <a :href="inv.pdf_url" class="text-xs underline" :style="{ color: 'var(--primary)' }">PDF</a>
            </td>
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
const plan = ref({})
const balance = ref(0)
const invoices = ref([])

async function fetchBilling() {
  loading.value = true
  try {
    const { data } = await client.get('/reseller/billing')
    plan.value = data?.plan || {}
    balance.value = data?.balance ?? 0
    invoices.value = data?.invoices || []
  } catch {
    invoices.value = []
  } finally {
    loading.value = false
  }
}

onMounted(fetchBilling)
</script>
