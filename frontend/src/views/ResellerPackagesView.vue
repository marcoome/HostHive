<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">
          {{ $t('nav.my_packages', 'My Packages') }}
        </h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">
          Create and manage custom hosting packages for your sub-users.
        </p>
      </div>
      <button class="btn-primary text-sm" @click="createPackage">
        + New Package
      </button>
    </div>

    <div class="card p-6">
      <div v-if="loading" class="space-y-3">
        <div class="skeleton w-full h-12 rounded"></div>
        <div class="skeleton w-full h-12 rounded"></div>
        <div class="skeleton w-full h-12 rounded"></div>
      </div>
      <div v-else-if="packages.length === 0" class="text-center py-12">
        <p :style="{ color: 'var(--text-muted)' }">
          No packages yet. Create your first package to start onboarding sub-users.
        </p>
      </div>
      <table v-else class="w-full text-sm">
        <thead>
          <tr :style="{ color: 'var(--text-muted)' }" class="text-left">
            <th class="pb-3 font-medium">Name</th>
            <th class="pb-3 font-medium">Disk</th>
            <th class="pb-3 font-medium">Bandwidth</th>
            <th class="pb-3 font-medium">Domains</th>
            <th class="pb-3 font-medium">Price</th>
            <th class="pb-3 font-medium">Users</th>
            <th class="pb-3 font-medium"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="pkg in packages"
            :key="pkg.id"
            class="border-t"
            :style="{ borderColor: 'rgba(var(--border-rgb), 0.3)' }"
          >
            <td class="py-3" :style="{ color: 'var(--text-primary)' }">{{ pkg.name }}</td>
            <td class="py-3">{{ pkg.disk_quota }} MB</td>
            <td class="py-3">{{ pkg.bandwidth_quota }} GB</td>
            <td class="py-3">{{ pkg.max_domains }}</td>
            <td class="py-3">${{ pkg.price }}</td>
            <td class="py-3">{{ pkg.user_count }}</td>
            <td class="py-3 text-right">
              <button class="text-xs underline" :style="{ color: 'var(--primary)' }">Edit</button>
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
const packages = ref([])

async function fetchPackages() {
  loading.value = true
  try {
    const { data } = await client.get('/reseller/packages')
    packages.value = data?.items || data || []
  } catch {
    packages.value = []
  } finally {
    loading.value = false
  }
}

function createPackage() {
  // Open package creation modal/route
}

onMounted(fetchPackages)
</script>
