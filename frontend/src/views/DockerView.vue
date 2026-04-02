<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">Docker</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">Manage containers and deploy stacks</p>
      </div>
      <div class="flex gap-2">
        <button class="btn-secondary" @click="showCompose = true">
          <span>&#9783;</span> Compose Deploy
        </button>
        <button class="btn-primary" @click="showDeploy = true">
          <span>&#10010;</span> Deploy Container
        </button>
      </div>
    </div>

    <!-- Docker Not Available Banner -->
    <div v-if="!docker.dockerAvailable" class="glass rounded-2xl p-6 mb-6 flex items-center gap-4" :style="{ borderColor: 'var(--warning)' }">
      <span class="text-3xl">&#9888;</span>
      <div>
        <h3 class="font-semibold" :style="{ color: 'var(--warning)' }">Docker Not Available</h3>
        <p class="text-sm" :style="{ color: 'var(--text-muted)' }">Docker is not installed or the daemon is not running on this server.</p>
      </div>
    </div>

    <!-- Loading Skeleton -->
    <div v-if="docker.loading" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      <div v-for="i in 6" :key="i" class="glass rounded-2xl p-5">
        <div class="skeleton h-5 w-32 mb-3"></div>
        <div class="skeleton h-4 w-48 mb-2"></div>
        <div class="skeleton h-3 w-24 mb-4"></div>
        <div class="flex gap-2">
          <div class="skeleton h-8 w-16"></div>
          <div class="skeleton h-8 w-16"></div>
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-else-if="docker.containers.length === 0 && docker.dockerAvailable" class="glass rounded-2xl p-12 text-center">
      <div class="text-5xl mb-4">&#128230;</div>
      <h3 class="text-lg font-semibold mb-2" :style="{ color: 'var(--text-primary)' }">No Containers</h3>
      <p class="text-sm mb-4" :style="{ color: 'var(--text-muted)' }">Deploy your first container to get started.</p>
      <button class="btn-primary" @click="showDeploy = true">Deploy Container</button>
    </div>

    <!-- Containers Grid -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      <div
        v-for="container in docker.containers"
        :key="container.id"
        class="glass rounded-2xl p-5 transition-all"
      >
        <!-- Header -->
        <div class="flex items-start justify-between mb-3">
          <div class="min-w-0">
            <h3 class="font-semibold text-sm truncate" :style="{ color: 'var(--text-primary)' }">{{ container.name }}</h3>
            <p class="text-xs truncate" :style="{ color: 'var(--text-muted)' }">{{ container.image }}</p>
          </div>
          <span
            class="badge flex-shrink-0"
            :class="{
              'badge-success': container.status === 'running',
              'badge-error': container.status === 'exited' || container.status === 'error',
              'badge-warning': container.status === 'paused' || container.status === 'restarting'
            }"
          >
            <span class="w-1.5 h-1.5 rounded-full" :style="{
              background: container.status === 'running' ? 'var(--success)' :
                          container.status === 'exited' || container.status === 'error' ? 'var(--error)' : 'var(--warning)'
            }"></span>
            {{ container.status }}
          </span>
        </div>

        <!-- Ports -->
        <div v-if="container.ports && container.ports.length" class="mb-3">
          <div class="flex flex-wrap gap-1">
            <span
              v-for="port in container.ports"
              :key="port"
              class="text-xs px-2 py-0.5 rounded"
              :style="{ background: 'rgba(var(--primary-rgb), 0.1)', color: 'var(--primary)' }"
            >
              {{ port }}
            </span>
          </div>
        </div>

        <!-- Resource Bars -->
        <div class="space-y-2 mb-4">
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span :style="{ color: 'var(--text-muted)' }">CPU</span>
              <span :style="{ color: 'var(--text-primary)' }">{{ container.cpu_percent || 0 }}%</span>
            </div>
            <div class="h-1.5 rounded-full" :style="{ background: 'rgba(var(--border-rgb), 0.3)' }">
              <div
                class="h-full rounded-full transition-all duration-500"
                :style="{
                  width: (container.cpu_percent || 0) + '%',
                  background: (container.cpu_percent || 0) > 80 ? 'var(--error)' : 'var(--primary)'
                }"
              ></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between text-xs mb-1">
              <span :style="{ color: 'var(--text-muted)' }">RAM</span>
              <span :style="{ color: 'var(--text-primary)' }">{{ container.mem_percent || 0 }}%</span>
            </div>
            <div class="h-1.5 rounded-full" :style="{ background: 'rgba(var(--border-rgb), 0.3)' }">
              <div
                class="h-full rounded-full transition-all duration-500"
                :style="{
                  width: (container.mem_percent || 0) + '%',
                  background: (container.mem_percent || 0) > 80 ? 'var(--error)' : 'var(--success)'
                }"
              ></div>
            </div>
          </div>
        </div>

        <!-- Actions -->
        <div class="flex gap-1.5 flex-wrap">
          <button
            v-if="container.status !== 'running'"
            class="btn-ghost text-xs px-2 py-1"
            @click="docker.startContainer(container.id)"
          >&#9654; Start</button>
          <button
            v-if="container.status === 'running'"
            class="btn-ghost text-xs px-2 py-1"
            @click="docker.stopContainer(container.id)"
          >&#9632; Stop</button>
          <button class="btn-ghost text-xs px-2 py-1" @click="docker.restartContainer(container.id)">&#8635; Restart</button>
          <button class="btn-ghost text-xs px-2 py-1" @click="openDetail(container)">&#9783; Logs</button>
          <button class="btn-ghost text-xs px-2 py-1" :style="{ color: 'var(--error)' }" @click="docker.removeContainer(container.id)">&#10005; Remove</button>
        </div>
      </div>
    </div>

    <!-- Deploy Modal -->
    <Modal v-model="showDeploy" title="Deploy Container" size="lg">
      <div class="space-y-4">
        <div>
          <label class="input-label">Image</label>
          <input v-model="deployForm.image" class="w-full" placeholder="nginx:latest" />
        </div>
        <div>
          <label class="input-label">Container Name</label>
          <input v-model="deployForm.name" class="w-full" placeholder="my-container" />
        </div>

        <!-- Port Mappings -->
        <div>
          <label class="input-label">Port Mappings</label>
          <div v-for="(port, i) in deployForm.ports" :key="i" class="flex gap-2 mb-2">
            <input v-model="port.host" class="w-24" placeholder="Host" />
            <span class="self-center" :style="{ color: 'var(--text-muted)' }">:</span>
            <input v-model="port.container" class="w-24" placeholder="Container" />
            <button class="btn-ghost text-xs px-2" @click="deployForm.ports.splice(i, 1)">&#10005;</button>
          </div>
          <button class="btn-ghost text-xs" @click="deployForm.ports.push({ host: '', container: '' })">+ Add Port</button>
        </div>

        <!-- Env Vars -->
        <div>
          <label class="input-label">Environment Variables</label>
          <div v-for="(env, i) in deployForm.envVars" :key="i" class="flex gap-2 mb-2">
            <input v-model="env.key" class="flex-1" placeholder="KEY" />
            <span class="self-center" :style="{ color: 'var(--text-muted)' }">=</span>
            <input v-model="env.value" class="flex-1" placeholder="value" />
            <button class="btn-ghost text-xs px-2" @click="deployForm.envVars.splice(i, 1)">&#10005;</button>
          </div>
          <button class="btn-ghost text-xs" @click="deployForm.envVars.push({ key: '', value: '' })">+ Add Variable</button>
        </div>

        <!-- Volumes -->
        <div>
          <label class="input-label">Volumes</label>
          <input v-model="deployForm.volumes" class="w-full" placeholder="/host/path:/container/path (comma separated)" />
        </div>
      </div>

      <template #actions>
        <button class="btn-secondary" @click="showDeploy = false">Cancel</button>
        <button class="btn-primary" :disabled="!deployForm.image" @click="deploy">Deploy</button>
      </template>
    </Modal>

    <!-- Compose Modal -->
    <Modal v-model="showCompose" title="Deploy Compose Stack" size="xl">
      <div class="space-y-4">
        <div>
          <label class="input-label">docker-compose.yml</label>
          <textarea
            v-model="composeYaml"
            class="w-full font-mono text-sm"
            style="min-height: 300px; background: rgba(var(--bg-rgb), 0.5); font-family: 'JetBrains Mono', 'Fira Code', monospace;"
            placeholder="version: '3.8'&#10;services:&#10;  web:&#10;    image: nginx:latest&#10;    ports:&#10;      - '80:80'"
          ></textarea>
        </div>
      </div>

      <template #actions>
        <button class="btn-secondary" @click="showCompose = false">Cancel</button>
        <button class="btn-primary" :disabled="!composeYaml.trim()" @click="deployComposeStack">Deploy Stack</button>
      </template>
    </Modal>

    <!-- Container Detail Modal -->
    <Modal v-model="showDetail" :title="detailContainer?.name || 'Container'" size="xl">
      <div v-if="detailContainer">
        <!-- Tabs -->
        <div class="flex gap-1 mb-4" :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
          <button
            v-for="tab in ['logs', 'stats']"
            :key="tab"
            class="px-4 py-2 text-sm font-medium capitalize transition-colors"
            :class="detailTab === tab ? 'border-b-2' : ''"
            :style="{
              color: detailTab === tab ? 'var(--primary)' : 'var(--text-muted)',
              borderColor: detailTab === tab ? 'var(--primary)' : 'transparent'
            }"
            @click="detailTab = tab"
          >
            {{ tab }}
          </button>
        </div>

        <!-- Logs -->
        <div v-if="detailTab === 'logs'">
          <div
            ref="logsContainer"
            class="rounded-lg p-4 overflow-auto font-mono text-xs leading-relaxed"
            style="height: 400px; background: rgba(var(--bg-rgb), 0.8); font-family: 'JetBrains Mono', 'Fira Code', monospace;"
          >
            <div v-if="containerLogs" style="white-space: pre-wrap;">{{ containerLogs }}</div>
            <div v-else :style="{ color: 'var(--text-muted)' }">Loading logs...</div>
          </div>
        </div>

        <!-- Stats -->
        <div v-if="detailTab === 'stats'" class="space-y-4">
          <div class="grid grid-cols-2 gap-4">
            <div class="glass rounded-xl p-4 text-center">
              <GaugeChart :value="containerStats.cpu || 0" label="CPU" :size="100" />
            </div>
            <div class="glass rounded-xl p-4 text-center">
              <GaugeChart :value="containerStats.memory || 0" label="Memory" :size="100" />
            </div>
          </div>
          <div class="glass rounded-xl p-4">
            <div class="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span :style="{ color: 'var(--text-muted)' }">Network I/O:</span>
                <span class="ml-2" :style="{ color: 'var(--text-primary)' }">{{ containerStats.net_io || 'N/A' }}</span>
              </div>
              <div>
                <span :style="{ color: 'var(--text-muted)' }">Block I/O:</span>
                <span class="ml-2" :style="{ color: 'var(--text-primary)' }">{{ containerStats.block_io || 'N/A' }}</span>
              </div>
              <div>
                <span :style="{ color: 'var(--text-muted)' }">PIDs:</span>
                <span class="ml-2" :style="{ color: 'var(--text-primary)' }">{{ containerStats.pids || 'N/A' }}</span>
              </div>
              <div>
                <span :style="{ color: 'var(--text-muted)' }">Uptime:</span>
                <span class="ml-2" :style="{ color: 'var(--text-primary)' }">{{ containerStats.uptime || 'N/A' }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useDockerStore } from '@/stores/docker'
import Modal from '@/components/Modal.vue'
import GaugeChart from '@/components/GaugeChart.vue'

const docker = useDockerStore()

const showDeploy = ref(false)
const showCompose = ref(false)
const showDetail = ref(false)
const detailTab = ref('logs')
const detailContainer = ref(null)
const containerLogs = ref('')
const containerStats = ref({})
const composeYaml = ref('')
const logsContainer = ref(null)

const deployForm = ref({
  image: '',
  name: '',
  ports: [{ host: '', container: '' }],
  envVars: [{ key: '', value: '' }],
  volumes: ''
})

async function deploy() {
  const payload = {
    image: deployForm.value.image,
    name: deployForm.value.name,
    ports: deployForm.value.ports.filter(p => p.host && p.container).map(p => `${p.host}:${p.container}`),
    environment: Object.fromEntries(
      deployForm.value.envVars.filter(e => e.key).map(e => [e.key, e.value])
    ),
    volumes: deployForm.value.volumes ? deployForm.value.volumes.split(',').map(v => v.trim()) : []
  }
  await docker.deployContainer(payload)
  showDeploy.value = false
  resetDeployForm()
}

function resetDeployForm() {
  deployForm.value = {
    image: '',
    name: '',
    ports: [{ host: '', container: '' }],
    envVars: [{ key: '', value: '' }],
    volumes: ''
  }
}

async function deployComposeStack() {
  await docker.deployCompose(composeYaml.value)
  showCompose.value = false
  composeYaml.value = ''
}

async function openDetail(container) {
  detailContainer.value = container
  detailTab.value = 'logs'
  showDetail.value = true
  try {
    const [logs, stats] = await Promise.all([
      docker.getContainerLogs(container.id),
      docker.getContainerStats(container.id)
    ])
    containerLogs.value = typeof logs === 'string' ? logs : logs.logs || JSON.stringify(logs)
    containerStats.value = stats
  } catch {
    containerLogs.value = 'Failed to fetch logs.'
    containerStats.value = {}
  }
}

onMounted(async () => {
  try {
    await docker.fetchContainers()
  } catch {}
})
</script>
