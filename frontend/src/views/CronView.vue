<template>
  <div>
    <!-- Header -->
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold text-text-primary">Cron Jobs</h1>
        <p class="text-sm text-text-muted mt-1">Schedule automated tasks on your server</p>
      </div>
      <button class="btn-primary" @click="openAddModal">
        &#43; Add Cron Job
      </button>
    </div>

    <!-- Jobs Table -->
    <DataTable
      :columns="columns"
      :rows="cron.jobs"
      :loading="cron.loading"
      empty-text="No cron jobs configured. Create your first scheduled task."
    >
      <template #cell-schedule="{ row }">
        <div>
          <span class="text-sm text-text-primary">{{ humanReadable(row.schedule) }}</span>
          <span class="block font-mono text-xs text-text-muted mt-0.5">{{ row.schedule }}</span>
        </div>
      </template>
      <template #cell-command="{ row }">
        <span class="font-mono text-sm break-all">{{ row.command }}</span>
      </template>
      <template #cell-last_run="{ row }">
        <div v-if="row.last_run">
          <span class="text-sm text-text-primary">{{ formatDate(row.last_run) }}</span>
          <div class="flex items-center gap-1.5 mt-0.5">
            <span
              class="w-1.5 h-1.5 rounded-full"
              :class="row.last_exit_code === 0 ? 'bg-success' : 'bg-error'"
            ></span>
            <span class="text-xs text-text-muted">
              Exit code: {{ row.last_exit_code ?? 'N/A' }}
            </span>
          </div>
        </div>
        <span v-else class="text-sm text-text-muted">Never</span>
      </template>
      <template #cell-status="{ row }">
        <StatusBadge :status="row.status" :label="row.status" />
      </template>
      <template #actions="{ row }">
        <div class="flex items-center justify-end gap-1 flex-wrap">
          <button class="btn-ghost text-xs px-2 py-1.5 min-h-[36px]" @click="confirmRun(row)">
            &#9654; Run
          </button>
          <button class="btn-ghost text-xs px-2 py-1.5 min-h-[36px]" @click="openEditModal(row)">
            Edit
          </button>
          <button
            class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] text-error hover:text-error"
            @click="confirmDelete(row)"
          >
            Delete
          </button>
        </div>
      </template>
    </DataTable>

    <!-- Add/Edit Cron Job Modal -->
    <Modal v-model="showModal" :title="editingJob ? 'Edit Cron Job' : 'Add Cron Job'" size="lg">
      <div class="space-y-6">
        <!-- Quick Presets -->
        <div>
          <label class="input-label">Quick Presets</label>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="preset in presets"
              :key="preset.label"
              type="button"
              class="px-3 py-1.5 text-xs rounded-full border border-border transition-all"
              :class="cronExpression === preset.value
                ? 'bg-primary text-white border-primary'
                : 'bg-surface hover:bg-surface-elevated text-text-primary hover:border-primary/50'"
              @click="applyPreset(preset)"
            >
              {{ preset.label }}
            </button>
          </div>
        </div>

        <!-- Visual Cron Builder -->
        <div class="glass rounded-2xl p-5">
          <label class="input-label mb-4">Schedule Builder</label>
          <div class="grid grid-cols-5 gap-3">
            <!-- Minute -->
            <div>
              <label class="text-xs text-text-muted block mb-1.5 font-medium">Minute</label>
              <select v-model="cronParts.minute" class="w-full text-sm" @change="updateExpression">
                <option value="*">Every minute (*)</option>
                <option v-for="n in 60" :key="'m'+n" :value="String(n-1)">{{ String(n-1).padStart(2,'0') }}</option>
                <option value="*/5">Every 5 min</option>
                <option value="*/10">Every 10 min</option>
                <option value="*/15">Every 15 min</option>
                <option value="*/30">Every 30 min</option>
              </select>
            </div>
            <!-- Hour -->
            <div>
              <label class="text-xs text-text-muted block mb-1.5 font-medium">Hour</label>
              <select v-model="cronParts.hour" class="w-full text-sm" @change="updateExpression">
                <option value="*">Every hour (*)</option>
                <option v-for="n in 24" :key="'h'+n" :value="String(n-1)">{{ String(n-1).padStart(2,'0') }}:00</option>
                <option value="*/2">Every 2 hrs</option>
                <option value="*/6">Every 6 hrs</option>
                <option value="*/12">Every 12 hrs</option>
              </select>
            </div>
            <!-- Day of Month -->
            <div>
              <label class="text-xs text-text-muted block mb-1.5 font-medium">Day (Month)</label>
              <select v-model="cronParts.dayOfMonth" class="w-full text-sm" @change="updateExpression">
                <option value="*">Every day (*)</option>
                <option v-for="n in 31" :key="'d'+n" :value="String(n)">{{ n }}</option>
              </select>
            </div>
            <!-- Month -->
            <div>
              <label class="text-xs text-text-muted block mb-1.5 font-medium">Month</label>
              <select v-model="cronParts.month" class="w-full text-sm" @change="updateExpression">
                <option value="*">Every month (*)</option>
                <option v-for="(m, i) in months" :key="'mo'+i" :value="String(i+1)">{{ m }}</option>
              </select>
            </div>
            <!-- Day of Week -->
            <div>
              <label class="text-xs text-text-muted block mb-1.5 font-medium">Day (Week)</label>
              <select v-model="cronParts.dayOfWeek" class="w-full text-sm" @change="updateExpression">
                <option value="*">Any day (*)</option>
                <option v-for="(d, i) in weekdays" :key="'wd'+i" :value="String(i)">{{ d }}</option>
              </select>
            </div>
          </div>

          <!-- Live Expression Preview -->
          <div class="mt-5 p-4 rounded-xl bg-background/60 border border-border">
            <div class="flex items-center justify-between">
              <div>
                <label class="text-xs text-text-muted block mb-1">Cron Expression</label>
                <code class="text-lg font-mono font-semibold text-primary tracking-wider">{{ cronExpression }}</code>
              </div>
              <div class="text-right">
                <label class="text-xs text-text-muted block mb-1">Runs</label>
                <span class="text-sm text-text-primary font-medium">{{ humanReadable(cronExpression) }}</span>
              </div>
            </div>
          </div>

          <!-- Manual override -->
          <div class="mt-3">
            <label class="text-xs text-text-muted block mb-1">Or type expression directly</label>
            <input
              v-model="cronExpression"
              type="text"
              class="w-full font-mono text-sm"
              placeholder="* * * * *"
              @input="parseCronExpression"
            />
          </div>
        </div>

        <!-- Command -->
        <div>
          <label class="input-label">Command</label>
          <textarea
            v-model="form.command"
            class="w-full font-mono text-sm"
            rows="3"
            placeholder="/usr/bin/php /home/user/public_html/cron.php"
            required
          ></textarea>
          <p class="text-xs text-text-muted mt-1">Use absolute paths for reliability.</p>
        </div>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showModal = false">Cancel</button>
        <button class="btn-primary" :disabled="saving" @click="saveJob">
          <span v-if="saving" class="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full"></span>
          {{ saving ? 'Saving...' : (editingJob ? 'Save Changes' : 'Create Job') }}
        </button>
      </template>
    </Modal>

    <!-- Run Confirm -->
    <ConfirmDialog
      v-model="showRunConfirm"
      title="Run Cron Job Now"
      :message="`Run this job immediately?\n\nCommand: ${jobToRun?.command}`"
      confirm-text="Run Now"
      :destructive="false"
      @confirm="runJob"
    />

    <!-- Delete Confirm -->
    <ConfirmDialog
      v-model="showDeleteConfirm"
      title="Delete Cron Job"
      :message="`Are you sure you want to delete this cron job? This action cannot be undone.`"
      confirm-text="Delete Job"
      :destructive="true"
      @confirm="deleteJob"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useCronStore } from '@/stores/cron'
import { useNotificationsStore } from '@/stores/notifications'
import DataTable from '@/components/DataTable.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const cron = useCronStore()
const notifications = useNotificationsStore()

const columns = [
  { key: 'schedule', label: 'Schedule' },
  { key: 'command', label: 'Command' },
  { key: 'last_run', label: 'Last Run' },
  { key: 'status', label: 'Status' }
]

const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const weekdays = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

const presets = [
  { label: 'Every minute', value: '* * * * *' },
  { label: 'Every 5 min', value: '*/5 * * * *' },
  { label: 'Every hour', value: '0 * * * *' },
  { label: 'Every 6 hours', value: '0 */6 * * *' },
  { label: 'Daily at midnight', value: '0 0 * * *' },
  { label: 'Daily at 3 AM', value: '0 3 * * *' },
  { label: 'Weekly (Sun)', value: '0 0 * * 0' },
  { label: 'Monthly (1st)', value: '0 0 1 * *' }
]

const showModal = ref(false)
const showRunConfirm = ref(false)
const showDeleteConfirm = ref(false)
const saving = ref(false)
const editingJob = ref(null)
const jobToRun = ref(null)
const jobToDelete = ref(null)

const cronExpression = ref('0 0 * * *')
const cronParts = ref({
  minute: '0',
  hour: '0',
  dayOfMonth: '*',
  month: '*',
  dayOfWeek: '*'
})

const form = ref({ command: '' })

onMounted(() => {
  cron.fetchJobs()
})

function updateExpression() {
  cronExpression.value = `${cronParts.value.minute} ${cronParts.value.hour} ${cronParts.value.dayOfMonth} ${cronParts.value.month} ${cronParts.value.dayOfWeek}`
}

function parseCronExpression() {
  const parts = cronExpression.value.trim().split(/\s+/)
  if (parts.length === 5) {
    cronParts.value = {
      minute: parts[0],
      hour: parts[1],
      dayOfMonth: parts[2],
      month: parts[3],
      dayOfWeek: parts[4]
    }
  }
}

function applyPreset(preset) {
  cronExpression.value = preset.value
  parseCronExpression()
}

function humanReadable(expr) {
  if (!expr) return ''
  const parts = expr.trim().split(/\s+/)
  if (parts.length !== 5) return expr

  const [min, hour, dom, mon, dow] = parts

  if (expr === '* * * * *') return 'Every minute'
  if (min.startsWith('*/') && hour === '*' && dom === '*' && mon === '*' && dow === '*') {
    return `Every ${min.slice(2)} minutes`
  }
  if (hour.startsWith('*/') && dom === '*' && mon === '*' && dow === '*') {
    return `Every ${hour.slice(2)} hours at minute ${min}`
  }

  let description = ''

  // Time
  if (min !== '*' && hour !== '*' && !hour.includes('/')) {
    const h = parseInt(hour)
    const m = parseInt(min)
    const ampm = h >= 12 ? 'PM' : 'AM'
    const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h
    description += `At ${h12}:${String(m).padStart(2, '0')} ${ampm}`
  } else if (min !== '*' && hour === '*') {
    description += `At minute ${min} of every hour`
  } else if (min === '*' && hour !== '*') {
    description += `Every minute during hour ${hour}`
  }

  // Day of month
  if (dom !== '*') {
    const suffix = dom === '1' || dom === '21' || dom === '31' ? 'st' :
                   dom === '2' || dom === '22' ? 'nd' :
                   dom === '3' || dom === '23' ? 'rd' : 'th'
    description += ` on the ${dom}${suffix}`
  }

  // Month
  if (mon !== '*') {
    const monthIdx = parseInt(mon) - 1
    if (monthIdx >= 0 && monthIdx < 12) {
      description += ` of ${months[monthIdx]}`
    }
  }

  // Day of week
  if (dow !== '*') {
    const dayIdx = parseInt(dow)
    if (dayIdx >= 0 && dayIdx < 7) {
      description += (dom === '*' ? ' every ' : ', ') + weekdays[dayIdx]
    }
  }

  // Frequency
  if (dom === '*' && mon === '*' && dow === '*') {
    if (description) description += ', daily'
  }

  return description || expr
}

function formatDate(dateStr) {
  if (!dateStr) return 'N/A'
  const d = new Date(dateStr)
  return d.toLocaleString()
}

function openAddModal() {
  editingJob.value = null
  form.value = { command: '' }
  cronExpression.value = '0 0 * * *'
  parseCronExpression()
  showModal.value = true
}

function openEditModal(job) {
  editingJob.value = job
  form.value = { command: job.command }
  cronExpression.value = job.schedule
  parseCronExpression()
  showModal.value = true
}

async function saveJob() {
  if (!form.value.command.trim()) {
    notifications.error('Command is required')
    return
  }
  saving.value = true
  try {
    const payload = {
      schedule: cronExpression.value,
      command: form.value.command
    }
    if (editingJob.value) {
      await cron.updateJob(editingJob.value.id, payload)
      notifications.success('Cron job updated')
    } else {
      await cron.createJob(payload)
      notifications.success('Cron job created')
    }
    showModal.value = false
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to save cron job')
  } finally {
    saving.value = false
  }
}

function confirmRun(job) {
  jobToRun.value = job
  showRunConfirm.value = true
}

async function runJob() {
  if (!jobToRun.value) return
  try {
    await cron.runJob(jobToRun.value.id)
    notifications.success('Job execution started')
    jobToRun.value = null
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to run job')
  }
}

function confirmDelete(job) {
  jobToDelete.value = job
  showDeleteConfirm.value = true
}

async function deleteJob() {
  if (!jobToDelete.value) return
  try {
    await cron.removeJob(jobToDelete.value.id)
    notifications.success('Cron job deleted')
    jobToDelete.value = null
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to delete cron job')
  }
}
</script>
