<template>
  <div class="card p-0 overflow-hidden">
    <!-- Header -->
    <div v-if="$slots.header" class="px-4 sm:px-6 py-4 border-b border-border">
      <slot name="header" />
    </div>

    <!-- Table -->
    <div class="overflow-x-auto -webkit-overflow-scrolling-touch">
      <table class="w-full min-w-[540px]">
        <thead>
          <tr class="border-b border-border">
            <th
              v-for="col in columns"
              :key="col.key"
              class="px-4 sm:px-6 py-3 text-left text-xs font-semibold text-text-muted uppercase tracking-wider whitespace-nowrap"
            >
              {{ col.label }}
            </th>
            <th v-if="$slots.actions" class="px-4 sm:px-6 py-3 text-right text-xs font-semibold text-text-muted uppercase tracking-wider whitespace-nowrap">
              Actions
            </th>
          </tr>
        </thead>
        <tbody v-if="loading">
          <tr v-for="i in skeletonRows" :key="i" class="border-b border-border last:border-0">
            <td v-for="col in columns" :key="col.key" class="px-4 sm:px-6 py-4">
              <LoadingSkeleton class="h-4 w-3/4" />
            </td>
            <td v-if="$slots.actions" class="px-4 sm:px-6 py-4">
              <LoadingSkeleton class="h-4 w-16 ml-auto" />
            </td>
          </tr>
        </tbody>
        <tbody v-else-if="rows.length === 0">
          <tr>
            <td :colspan="columns.length + ($slots.actions ? 1 : 0)" class="px-4 sm:px-6 py-12 text-center">
              <div class="text-text-muted">
                <div class="text-3xl mb-2">&#9744;</div>
                <p class="text-sm">{{ emptyText }}</p>
              </div>
            </td>
          </tr>
        </tbody>
        <tbody v-else>
          <tr
            v-for="(row, index) in rows"
            :key="row.id || index"
            class="border-b border-border last:border-0 hover:bg-background/50 transition-colors"
          >
            <td v-for="col in columns" :key="col.key" class="px-4 sm:px-6 py-4 text-sm">
              <slot :name="'cell-' + col.key" :row="row" :value="row[col.key]">
                {{ row[col.key] }}
              </slot>
            </td>
            <td v-if="$slots.actions" class="px-4 sm:px-6 py-4 text-right">
              <slot name="actions" :row="row" />
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Pagination -->
    <div v-if="totalPages > 1" class="px-4 sm:px-6 py-3 border-t border-border flex flex-col sm:flex-row items-center justify-between gap-2">
      <span class="text-sm text-text-muted">
        Page {{ currentPage }} of {{ totalPages }}
      </span>
      <div class="flex gap-1">
        <button
          class="btn-ghost text-xs px-3 py-2 min-h-[44px]"
          :disabled="currentPage <= 1"
          @click="$emit('page-change', currentPage - 1)"
        >
          Previous
        </button>
        <button
          class="btn-ghost text-xs px-3 py-2 min-h-[44px]"
          :disabled="currentPage >= totalPages"
          @click="$emit('page-change', currentPage + 1)"
        >
          Next
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import LoadingSkeleton from './LoadingSkeleton.vue'

defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  emptyText: { type: String, default: 'No data found.' },
  currentPage: { type: Number, default: 1 },
  totalPages: { type: Number, default: 1 },
  skeletonRows: { type: Number, default: 5 }
})

defineEmits(['page-change'])
</script>
