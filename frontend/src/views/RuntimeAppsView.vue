<template>
  <div>
    <!-- Header -->
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">Runtime Apps</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">Manage Node.js and Python applications</p>
      </div>
      <button class="btn-primary" @click="openCreateModal">
        <span>&#10010;</span> Create App
      </button>
    </div>

    <!-- Loading Skeleton -->
    <div v-if="store.loading" class="space-y-4">
      <div v-for="i in 3" :key="i" class="glass rounded-2xl p-5">
        <div class="flex items-center gap-4">
          <div class="skeleton h-10 w-10 rounded-lg"></div>
          <div class="flex-1">
            <div class="skeleton h-5 w-48 mb-2"></div>
            <div class="skeleton h-3 w-32"></div>
          </div>
          <div class="skeleton h-8 w-20"></div>
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-else-if="store.apps.length === 0" class="glass rounded-2xl p-12 text-center">
      <div class="text-5xl mb-4">&#9881;</div>
      <h3 class="text-lg font-semibold mb-2" :style="{ color: 'var(--text-primary)' }">No Runtime Apps</h3>
      <p class="text-sm mb-4" :style="{ color: 'var(--text-muted)' }">
        Create your first Node.js or Python application to get started.
      </p>
      <button class="btn-primary" @click="openCreateModal">Create App</button>
    </div>

    <!-- Apps List -->
    <div v-else class="space-y-4">
      <div
        v-for="app in store.apps"
        :key="app.id"
        class="glass rounded-2xl p-5 transition-all hover:shadow-lg"
      >
        <div class="flex flex-col lg:flex-row lg:items-center gap-4">
          <!-- App Icon + Info -->
          <div class="flex items-center gap-4 flex-1 min-w-0">
            <div
              class="w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold text-sm flex-shrink-0"
              :style="{ background: app.app_type === 'node' ? '#68a063' : '#3776ab' }"
            >
              {{ app.app_type === 'node' ? 'JS' : 'PY' }}
            </div>
            <div class="min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <h3 class="font-semibold text-sm truncate" :style="{ color: 'var(--text-primary)' }">
                  {{ app.app_name || app.domain_name }}
                </h3>
                <span
                  class="badge flex-shrink-0"
                  :class="app.app_type === 'node' ? 'badge-success' : 'badge-info'"
                >
                  {{ app.app_type === 'node' ? 'Node.js' : 'Python' }} {{ app.runtime_version }}
                </span>
                <span
                  class="badge flex-shrink-0"
                  :class="app.is_running ? 'badge-success' : 'badge-error'"
                >
                  <span
                    class="w-1.5 h-1.5 rounded-full inline-block mr-1"
                    :style="{ background: app.is_running ? 'var(--success)' : 'var(--error)' }"
                  ></span>
                  {{ app.is_running ? 'Running' : 'Stopped' }}
                </span>
              </div>
              <p class="text-xs mt-1 truncate" :style="{ color: 'var(--text-muted)' }">
                {{ app.domain_name }} &middot; Port {{ app.port }} &middot; {{ app.app_root }}
              </p>
            </div>
          </div>

          <!-- Actions -->
          <div class="flex items-center gap-2 flex-shrink-0 flex-wrap">
            <button
              v-if="!app.is_running"
              class="btn-sm btn-success"
              :disabled="store.actionLoading"
              @click="store.startApp(app.id)"
              title="Start"
            >
              &#9654; Start
            </button>
            <button
              v-if="app.is_running"
              class="btn-sm btn-warning"
              :disabled="store.actionLoading"
              @click="store.stopApp(app.id)"
              title="Stop"
            >
              &#9632; Stop
            </button>
            <button
              class="btn-sm btn-secondary"
              :disabled="store.actionLoading"
              @click="store.restartApp(app.id)"
              title="Restart"
            >
              &#8635; Restart
            </button>
            <button
              class="btn-sm btn-secondary"
              @click="openLogs(app)"
              title="View Logs"
            >
              &#9783; Logs
            </button>
            <button
              class="btn-sm btn-secondary"
              :disabled="store.actionLoading"
              @click="installDeps(app)"
              title="Install Dependencies"
            >
              &#128230; Deps
            </button>
            <button
              class="btn-sm btn-secondary"
              @click="openEditModal(app)"
              title="Edit"
            >
              &#9998; Edit
            </button>
            <button
              class="btn-sm btn-error"
              @click="confirmDelete(app)"
              title="Delete"
            >
              &#128465;
            </button>
          </div>
        </div>

        <!-- Env Vars Preview (collapsed) -->
        <div v-if="app.env_vars && Object.keys(app.env_vars).length" class="mt-3 pt-3" :style="{ borderTop: '1px solid var(--border)' }">
          <button
            class="text-xs font-medium flex items-center gap-1"
            :style="{ color: 'var(--text-muted)' }"
            @click="toggleEnvPreview(app.id)"
          >
            <span :class="{ 'rotate-90': expandedEnv === app.id }" class="transition-transform inline-block">&#9654;</span>
            {{ Object.keys(app.env_vars).length }} environment variable{{ Object.keys(app.env_vars).length > 1 ? 's' : '' }}
          </button>
          <div v-if="expandedEnv === app.id" class="mt-2 space-y-1">
            <div
              v-for="(val, key) in app.env_vars"
              :key="key"
              class="flex items-center gap-2 text-xs font-mono"
            >
              <span :style="{ color: 'var(--primary)' }">{{ key }}</span>
              <span :style="{ color: 'var(--text-muted)' }">=</span>
              <span :style="{ color: 'var(--text-primary)' }">{{ val }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Create / Edit Modal -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="showModal"
          class="fixed inset-0 z-50 flex items-center justify-center p-4"
          @click.self="showModal = false"
        >
          <div class="fixed inset-0 bg-black/50 backdrop-blur-sm"></div>
          <div class="glass rounded-2xl p-6 w-full max-w-2xl relative z-10 max-h-[90vh] overflow-y-auto">
            <div class="flex items-center justify-between mb-6">
              <h2 class="text-lg font-semibold" :style="{ color: 'var(--text-primary)' }">
                {{ editingApp ? 'Edit App' : 'Create Runtime App' }}
              </h2>
              <button class="btn-ghost p-1 rounded-lg" @click="showModal = false">&#10005;</button>
            </div>

            <form @submit.prevent="submitForm" class="space-y-4">
              <!-- App Type -->
              <div v-if="!editingApp">
                <label class="block text-sm font-medium mb-2" :style="{ color: 'var(--text-primary)' }">App Type</label>
                <div class="flex gap-3">
                  <button
                    type="button"
                    class="flex-1 p-4 rounded-xl border-2 text-center transition-all"
                    :class="form.app_type === 'node' ? 'border-[#68a063]' : 'border-transparent'"
                    :style="{
                      background: form.app_type === 'node' ? 'rgba(104, 160, 99, 0.1)' : 'rgba(var(--border-rgb), 0.2)',
                      color: 'var(--text-primary)'
                    }"
                    @click="selectType('node')"
                  >
                    <div class="text-2xl mb-1">&#9881;</div>
                    <div class="font-semibold text-sm">Node.js</div>
                    <div class="text-xs mt-1" :style="{ color: 'var(--text-muted)' }">PM2 managed</div>
                  </button>
                  <button
                    type="button"
                    class="flex-1 p-4 rounded-xl border-2 text-center transition-all"
                    :class="form.app_type === 'python' ? 'border-[#3776ab]' : 'border-transparent'"
                    :style="{
                      background: form.app_type === 'python' ? 'rgba(55, 118, 171, 0.1)' : 'rgba(var(--border-rgb), 0.2)',
                      color: 'var(--text-primary)'
                    }"
                    @click="selectType('python')"
                  >
                    <div class="text-2xl mb-1">&#128013;</div>
                    <div class="font-semibold text-sm">Python</div>
                    <div class="text-xs mt-1" :style="{ color: 'var(--text-muted)' }">Gunicorn / Uvicorn</div>
                  </button>
                </div>
              </div>

              <!-- Domain -->
              <div v-if="!editingApp">
                <label class="block text-sm font-medium mb-1" :style="{ color: 'var(--text-primary)' }">Domain</label>
                <select
                  v-model="form.domain_id"
                  class="input w-full"
                  required
                >
                  <option value="" disabled>Select a domain...</option>
                  <option v-for="d in domains" :key="d.id" :value="d.id">{{ d.name || d.domain_name }}</option>
                </select>
              </div>

              <!-- App Name -->
              <div>
                <label class="block text-sm font-medium mb-1" :style="{ color: 'var(--text-primary)' }">App Name</label>
                <input
                  v-model="form.app_name"
                  type="text"
                  class="input w-full"
                  placeholder="My App"
                />
              </div>

              <!-- App Root Path -->
              <div>
                <label class="block text-sm font-medium mb-1" :style="{ color: 'var(--text-primary)' }">Application Root</label>
                <input
                  v-model="form.app_root"
                  type="text"
                  class="input w-full font-mono text-sm"
                  placeholder="/home/user/web/example.com/app"
                  required
                />
              </div>

              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <!-- Entry Point -->
                <div>
                  <label class="block text-sm font-medium mb-1" :style="{ color: 'var(--text-primary)' }">Entry Point</label>
                  <input
                    v-model="form.entry_point"
                    type="text"
                    class="input w-full font-mono text-sm"
                    :placeholder="form.app_type === 'node' ? 'app.js' : 'app.py'"
                  />
                </div>

                <!-- Runtime Version -->
                <div>
                  <label class="block text-sm font-medium mb-1" :style="{ color: 'var(--text-primary)' }">
                    {{ form.app_type === 'node' ? 'Node.js' : 'Python' }} Version
                  </label>
                  <select
                    v-model="form.runtime_version"
                    class="input w-full"
                  >
                    <option
                      v-for="v in (form.app_type === 'node' ? store.versions.node : store.versions.python)"
                      :key="v"
                      :value="v"
                    >
                      {{ form.app_type === 'node' ? `Node.js ${v}` : `Python ${v}` }}
                    </option>
                  </select>
                </div>
              </div>

              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <!-- Port -->
                <div>
                  <label class="block text-sm font-medium mb-1" :style="{ color: 'var(--text-primary)' }">Port</label>
                  <input
                    v-model.number="form.port"
                    type="number"
                    class="input w-full"
                    min="1024"
                    max="65535"
                    required
                  />
                </div>

                <!-- Startup Command (optional) -->
                <div>
                  <label class="block text-sm font-medium mb-1" :style="{ color: 'var(--text-primary)' }">
                    Startup Command
                    <span class="text-xs font-normal" :style="{ color: 'var(--text-muted)' }">(optional)</span>
                  </label>
                  <input
                    v-model="form.startup_command"
                    type="text"
                    class="input w-full font-mono text-sm"
                    :placeholder="form.app_type === 'node' ? 'npm start' : 'gunicorn app:app'"
                  />
                </div>
              </div>

              <!-- Environment Variables -->
              <div>
                <div class="flex items-center justify-between mb-2">
                  <label class="block text-sm font-medium" :style="{ color: 'var(--text-primary)' }">
                    Environment Variables
                  </label>
                  <button
                    type="button"
                    class="btn-sm btn-secondary"
                    @click="addEnvVar"
                  >
                    &#10010; Add Variable
                  </button>
                </div>
                <div class="space-y-2">
                  <div
                    v-for="(env, idx) in envVars"
                    :key="idx"
                    class="flex items-center gap-2"
                  >
                    <input
                      v-model="env.key"
                      type="text"
                      class="input flex-1 font-mono text-sm"
                      placeholder="KEY"
                    />
                    <span :style="{ color: 'var(--text-muted)' }">=</span>
                    <input
                      v-model="env.value"
                      type="text"
                      class="input flex-1 font-mono text-sm"
                      placeholder="value"
                    />
                    <button
                      type="button"
                      class="btn-ghost p-1 rounded text-sm"
                      :style="{ color: 'var(--error)' }"
                      @click="removeEnvVar(idx)"
                    >
                      &#10005;
                    </button>
                  </div>
                </div>
                <p v-if="envVars.length === 0" class="text-xs mt-1" :style="{ color: 'var(--text-muted)' }">
                  No environment variables defined.
                </p>
              </div>

              <!-- Submit -->
              <div class="flex justify-end gap-3 pt-4" :style="{ borderTop: '1px solid var(--border)' }">
                <button type="button" class="btn-secondary" @click="showModal = false">Cancel</button>
                <button
                  type="submit"
                  class="btn-primary"
                  :disabled="store.actionLoading"
                >
                  {{ store.actionLoading ? 'Saving...' : (editingApp ? 'Save Changes' : 'Create App') }}
                </button>
              </div>
            </form>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Logs Modal -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="showLogsModal"
          class="fixed inset-0 z-50 flex items-center justify-center p-4"
          @click.self="showLogsModal = false"
        >
          <div class="fixed inset-0 bg-black/50 backdrop-blur-sm"></div>
          <div class="glass rounded-2xl p-6 w-full max-w-4xl relative z-10 max-h-[90vh] flex flex-col">
            <div class="flex items-center justify-between mb-4">
              <div>
                <h2 class="text-lg font-semibold" :style="{ color: 'var(--text-primary)' }">
                  Application Logs
                </h2>
                <p class="text-xs" :style="{ color: 'var(--text-muted)' }">
                  {{ logsApp?.app_name || logsApp?.domain_name }}
                </p>
              </div>
              <div class="flex items-center gap-2">
                <select v-model="logsType" class="input text-sm" @change="refreshLogs">
                  <option value="all">All Logs</option>
                  <option value="stdout">Stdout</option>
                  <option value="stderr">Stderr</option>
                </select>
                <button class="btn-sm btn-secondary" @click="refreshLogs">&#8635; Refresh</button>
                <button class="btn-ghost p-1 rounded-lg" @click="showLogsModal = false">&#10005;</button>
              </div>
            </div>
            <div
              ref="logsContainer"
              class="flex-1 rounded-xl p-4 font-mono text-xs overflow-auto"
              :style="{
                background: 'var(--bg-primary)',
                color: 'var(--text-primary)',
                minHeight: '300px',
                maxHeight: '60vh'
              }"
            >
              <div v-if="logsLoading" class="text-center py-8" :style="{ color: 'var(--text-muted)' }">
                Loading logs...
              </div>
              <template v-else>
                <div v-if="logsContent.stdout && logsContent.stdout.length">
                  <div class="text-xs font-semibold mb-1" :style="{ color: 'var(--success)' }">--- stdout ---</div>
                  <div
                    v-for="(line, i) in logsContent.stdout"
                    :key="'stdout-' + i"
                    class="whitespace-pre-wrap break-all leading-relaxed"
                  >{{ line }}</div>
                </div>
                <div v-if="logsContent.stderr && logsContent.stderr.length" :class="{ 'mt-4': logsContent.stdout?.length }">
                  <div class="text-xs font-semibold mb-1" :style="{ color: 'var(--error)' }">--- stderr ---</div>
                  <div
                    v-for="(line, i) in logsContent.stderr"
                    :key="'stderr-' + i"
                    class="whitespace-pre-wrap break-all leading-relaxed"
                    :style="{ color: 'var(--error)' }"
                  >{{ line }}</div>
                </div>
                <div
                  v-if="(!logsContent.stdout || !logsContent.stdout.length) && (!logsContent.stderr || !logsContent.stderr.length)"
                  class="text-center py-8"
                  :style="{ color: 'var(--text-muted)' }"
                >
                  No logs available.
                </div>
              </template>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Delete Confirmation Modal -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="showDeleteModal"
          class="fixed inset-0 z-50 flex items-center justify-center p-4"
          @click.self="showDeleteModal = false"
        >
          <div class="fixed inset-0 bg-black/50 backdrop-blur-sm"></div>
          <div class="glass rounded-2xl p-6 w-full max-w-md relative z-10">
            <h2 class="text-lg font-semibold mb-2" :style="{ color: 'var(--text-primary)' }">Delete App</h2>
            <p class="text-sm mb-6" :style="{ color: 'var(--text-muted)' }">
              Are you sure you want to delete <strong>{{ deletingApp?.app_name || deletingApp?.domain_name }}</strong>?
              This will stop the app, remove the systemd service, and cannot be undone.
            </p>
            <div class="flex justify-end gap-3">
              <button class="btn-secondary" @click="showDeleteModal = false">Cancel</button>
              <button
                class="btn-error"
                :disabled="store.actionLoading"
                @click="doDelete"
              >
                {{ store.actionLoading ? 'Deleting...' : 'Delete App' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Install Deps Modal -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="showDepsModal"
          class="fixed inset-0 z-50 flex items-center justify-center p-4"
          @click.self="showDepsModal = false"
        >
          <div class="fixed inset-0 bg-black/50 backdrop-blur-sm"></div>
          <div class="glass rounded-2xl p-6 w-full max-w-2xl relative z-10">
            <div class="flex items-center justify-between mb-4">
              <h2 class="text-lg font-semibold" :style="{ color: 'var(--text-primary)' }">Install Dependencies</h2>
              <button class="btn-ghost p-1 rounded-lg" @click="showDepsModal = false">&#10005;</button>
            </div>
            <p class="text-sm mb-4" :style="{ color: 'var(--text-muted)' }">
              {{ depsApp?.app_type === 'node' ? 'Running npm install / yarn install...' : 'Running pip install -r requirements.txt...' }}
            </p>
            <div
              v-if="depsOutput"
              class="rounded-xl p-4 font-mono text-xs overflow-auto"
              :style="{
                background: 'var(--bg-primary)',
                color: 'var(--text-primary)',
                maxHeight: '300px'
              }"
            >
              <pre class="whitespace-pre-wrap">{{ depsOutput }}</pre>
            </div>
            <div v-else-if="store.actionLoading" class="text-center py-8" :style="{ color: 'var(--text-muted)' }">
              Installing dependencies...
            </div>
            <div class="flex justify-end mt-4">
              <button class="btn-secondary" @click="showDepsModal = false">Close</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick } from 'vue'
import { useRuntimeStore } from '@/stores/runtime'
import { useDomainsStore } from '@/stores/domains'

const store = useRuntimeStore()
const domainsStore = useDomainsStore()

const domains = ref([])
const showModal = ref(false)
const editingApp = ref(null)
const showLogsModal = ref(false)
const logsApp = ref(null)
const logsType = ref('all')
const logsContent = ref({})
const logsLoading = ref(false)
const logsContainer = ref(null)
const showDeleteModal = ref(false)
const deletingApp = ref(null)
const showDepsModal = ref(false)
const depsApp = ref(null)
const depsOutput = ref('')
const expandedEnv = ref(null)

const envVars = ref([])

const form = reactive({
  app_type: 'node',
  domain_id: '',
  app_name: '',
  app_root: '',
  entry_point: '',
  runtime_version: '',
  port: 3000,
  startup_command: ''
})

onMounted(async () => {
  await Promise.all([
    store.fetchApps(),
    store.fetchVersions(),
    domainsStore.fetch()
  ])
  domains.value = domainsStore.domains
})

function selectType(type) {
  form.app_type = type
  form.entry_point = type === 'node' ? 'app.js' : 'app.py'
  form.port = type === 'node' ? 3000 : 8000
  form.runtime_version = type === 'node'
    ? (store.versions.node[0] || '20')
    : (store.versions.python[0] || '3.11')
}

function openCreateModal() {
  editingApp.value = null
  form.app_type = 'node'
  form.domain_id = ''
  form.app_name = ''
  form.app_root = ''
  form.entry_point = 'app.js'
  form.runtime_version = store.versions.node[0] || '20'
  form.port = 3000
  form.startup_command = ''
  envVars.value = []
  showModal.value = true
}

function openEditModal(app) {
  editingApp.value = app
  form.app_type = app.app_type
  form.domain_id = app.domain_id
  form.app_name = app.app_name || ''
  form.app_root = app.app_root
  form.entry_point = app.entry_point
  form.runtime_version = app.runtime_version
  form.port = app.port
  form.startup_command = app.startup_command || ''
  envVars.value = app.env_vars
    ? Object.entries(app.env_vars).map(([key, value]) => ({ key, value }))
    : []
  showModal.value = true
}

function addEnvVar() {
  envVars.value.push({ key: '', value: '' })
}

function removeEnvVar(idx) {
  envVars.value.splice(idx, 1)
}

function buildEnvVarsObject() {
  const obj = {}
  for (const env of envVars.value) {
    if (env.key.trim()) {
      obj[env.key.trim()] = env.value
    }
  }
  return Object.keys(obj).length > 0 ? obj : null
}

async function submitForm() {
  const payload = {
    app_name: form.app_name,
    app_root: form.app_root,
    entry_point: form.entry_point,
    runtime_version: form.runtime_version,
    port: form.port,
    startup_command: form.startup_command || null,
    env_vars: buildEnvVarsObject()
  }

  if (editingApp.value) {
    await store.updateApp(editingApp.value.id, payload)
  } else {
    payload.app_type = form.app_type
    payload.domain_id = form.domain_id
    await store.createApp(payload)
  }
  showModal.value = false
}

async function openLogs(app) {
  logsApp.value = app
  logsType.value = 'all'
  logsContent.value = {}
  showLogsModal.value = true
  await refreshLogs()
}

async function refreshLogs() {
  if (!logsApp.value) return
  logsLoading.value = true
  try {
    logsContent.value = await store.getAppLogs(logsApp.value.id, logsType.value)
  } finally {
    logsLoading.value = false
  }
  // Auto-scroll to bottom
  await nextTick()
  if (logsContainer.value) {
    logsContainer.value.scrollTop = logsContainer.value.scrollHeight
  }
}

function confirmDelete(app) {
  deletingApp.value = app
  showDeleteModal.value = true
}

async function doDelete() {
  if (!deletingApp.value) return
  await store.deleteApp(deletingApp.value.id)
  showDeleteModal.value = false
  deletingApp.value = null
}

async function installDeps(app) {
  depsApp.value = app
  depsOutput.value = ''
  showDepsModal.value = true
  try {
    const result = await store.installDeps(app.id)
    depsOutput.value = result.output || 'Done.'
  } catch {
    depsOutput.value = 'Installation failed. Check logs for details.'
  }
}

function toggleEnvPreview(id) {
  expandedEnv.value = expandedEnv.value === id ? null : id
}
</script>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.125rem 0.5rem;
  border-radius: 9999px;
  font-size: 0.7rem;
  font-weight: 500;
}
.badge-success {
  background: rgba(var(--success-rgb, 34, 197, 94), 0.15);
  color: var(--success);
}
.badge-error {
  background: rgba(var(--error-rgb, 239, 68, 68), 0.15);
  color: var(--error);
}
.badge-warning {
  background: rgba(var(--warning-rgb, 234, 179, 8), 0.15);
  color: var(--warning);
}
.badge-info {
  background: rgba(55, 118, 171, 0.15);
  color: #3776ab;
}
.btn-sm {
  padding: 0.375rem 0.75rem;
  font-size: 0.75rem;
  border-radius: 0.5rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  white-space: nowrap;
}
.btn-success {
  background: rgba(var(--success-rgb, 34, 197, 94), 0.15);
  color: var(--success);
  border: 1px solid rgba(var(--success-rgb, 34, 197, 94), 0.3);
}
.btn-success:hover {
  background: rgba(var(--success-rgb, 34, 197, 94), 0.25);
}
.btn-warning {
  background: rgba(var(--warning-rgb, 234, 179, 8), 0.15);
  color: var(--warning);
  border: 1px solid rgba(var(--warning-rgb, 234, 179, 8), 0.3);
}
.btn-warning:hover {
  background: rgba(var(--warning-rgb, 234, 179, 8), 0.25);
}
.btn-error {
  background: rgba(var(--error-rgb, 239, 68, 68), 0.15);
  color: var(--error);
  border: 1px solid rgba(var(--error-rgb, 239, 68, 68), 0.3);
}
.btn-error:hover {
  background: rgba(var(--error-rgb, 239, 68, 68), 0.25);
}
.skeleton {
  background: linear-gradient(90deg, rgba(var(--border-rgb), 0.3) 25%, rgba(var(--border-rgb), 0.1) 50%, rgba(var(--border-rgb), 0.3) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
  border-radius: 0.5rem;
}
@keyframes skeleton-loading {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
.rotate-90 {
  transform: rotate(90deg);
}
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
