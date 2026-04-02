<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">MCP Server</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">Model Context Protocol server configuration</p>
      </div>
    </div>

    <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
      <!-- Left Column -->
      <div class="space-y-6">
        <!-- Status & Token -->
        <div class="glass rounded-2xl p-6">
          <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">Server Status</h3>

          <!-- Status Indicator -->
          <div class="flex items-center gap-3 mb-6">
            <span
              class="w-3 h-3 rounded-full"
              :style="{
                background: mcpOnline ? 'var(--success)' : 'var(--error)',
                boxShadow: mcpOnline ? '0 0 8px var(--success)' : '0 0 8px var(--error)'
              }"
            ></span>
            <span class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">
              {{ mcpOnline ? 'Online' : 'Offline' }}
            </span>
          </div>

          <!-- MCP Token -->
          <div>
            <label class="input-label">MCP Token</label>
            <div class="flex gap-2">
              <input
                :value="showToken ? mcpToken : maskedToken"
                class="flex-1 font-mono text-sm"
                readonly
              />
              <button class="btn-ghost text-xs px-3" @click="showToken = !showToken">
                {{ showToken ? 'Hide' : 'Show' }}
              </button>
              <button class="btn-ghost text-xs px-3" @click="copyToken">Copy</button>
              <button class="btn-secondary text-xs px-3" @click="regenerateToken">Regenerate</button>
            </div>
          </div>
        </div>

        <!-- Config Blocks -->
        <div class="glass rounded-2xl p-6">
          <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">Client Configuration</h3>

          <!-- Claude Desktop -->
          <div class="mb-5">
            <div class="flex items-center justify-between mb-2">
              <span class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">Claude Desktop</span>
              <button class="btn-ghost text-xs px-2 py-1" @click="copyConfig('claude')">Copy</button>
            </div>
            <pre class="rounded-lg p-4 text-xs overflow-x-auto font-mono" :style="{ background: 'rgba(var(--bg-rgb), 0.6)', color: 'var(--text-primary)', fontFamily: '\'JetBrains Mono\', \'Fira Code\', monospace' }">{{ claudeConfig }}</pre>
          </div>

          <!-- Cursor -->
          <div class="mb-5">
            <div class="flex items-center justify-between mb-2">
              <span class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">Cursor</span>
              <button class="btn-ghost text-xs px-2 py-1" @click="copyConfig('cursor')">Copy</button>
            </div>
            <pre class="rounded-lg p-4 text-xs overflow-x-auto font-mono" :style="{ background: 'rgba(var(--bg-rgb), 0.6)', color: 'var(--text-primary)', fontFamily: '\'JetBrains Mono\', \'Fira Code\', monospace' }">{{ cursorConfig }}</pre>
          </div>

          <!-- Generic -->
          <div>
            <div class="flex items-center justify-between mb-2">
              <span class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">Generic MCP Client</span>
              <button class="btn-ghost text-xs px-2 py-1" @click="copyConfig('generic')">Copy</button>
            </div>
            <pre class="rounded-lg p-4 text-xs overflow-x-auto font-mono" :style="{ background: 'rgba(var(--bg-rgb), 0.6)', color: 'var(--text-primary)', fontFamily: '\'JetBrains Mono\', \'Fira Code\', monospace' }">{{ genericConfig }}</pre>
          </div>
        </div>
      </div>

      <!-- Right Column -->
      <div class="space-y-6">
        <!-- Available Tools -->
        <div class="glass rounded-2xl p-6">
          <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">Available Tools</h3>
          <div class="space-y-2">
            <div
              v-for="tool in mcpTools"
              :key="tool.name"
              class="glass rounded-xl overflow-hidden"
            >
              <button
                class="w-full flex items-center justify-between px-4 py-3 text-left"
                @click="tool.expanded = !tool.expanded"
              >
                <div class="flex items-center gap-2">
                  <span class="text-xs font-mono font-medium" :style="{ color: 'var(--primary)' }">{{ tool.name }}</span>
                </div>
                <span class="text-xs transition-transform" :class="tool.expanded ? 'rotate-180' : ''" :style="{ color: 'var(--text-muted)' }">&#9660;</span>
              </button>
              <Transition name="expand">
                <div v-if="tool.expanded" class="px-4 pb-3">
                  <p class="text-xs mb-2" :style="{ color: 'var(--text-muted)' }">{{ tool.description }}</p>
                  <div v-if="tool.parameters?.length" class="space-y-1">
                    <div class="text-[10px] font-semibold uppercase tracking-wider mb-1" :style="{ color: 'var(--text-muted)' }">Parameters</div>
                    <div
                      v-for="param in tool.parameters"
                      :key="param.name"
                      class="flex items-start gap-2 text-xs"
                    >
                      <span class="font-mono" :style="{ color: 'var(--primary)' }">{{ param.name }}</span>
                      <span :style="{ color: 'var(--text-muted)' }">{{ param.type }}</span>
                      <span v-if="param.required" class="badge badge-warning text-[10px]">required</span>
                      <span class="text-xs" :style="{ color: 'var(--text-muted)' }">{{ param.description }}</span>
                    </div>
                  </div>
                </div>
              </Transition>
            </div>
          </div>
        </div>

        <!-- Recent MCP Calls -->
        <div class="glass rounded-2xl p-6">
          <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">Recent MCP Calls</h3>
          <div class="overflow-x-auto">
            <table class="w-full">
              <thead>
                <tr :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
                  <th class="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider" :style="{ color: 'var(--text-muted)' }">Time</th>
                  <th class="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider" :style="{ color: 'var(--text-muted)' }">Tool</th>
                  <th class="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider" :style="{ color: 'var(--text-muted)' }">Result</th>
                  <th class="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider" :style="{ color: 'var(--text-muted)' }">Caller</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="mcpCalls.length === 0">
                  <td colspan="4" class="px-3 py-8 text-center text-xs" :style="{ color: 'var(--text-muted)' }">No recent calls</td>
                </tr>
                <tr
                  v-for="call in mcpCalls"
                  :key="call.id"
                  :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.2)' }"
                >
                  <td class="px-3 py-2 text-xs" :style="{ color: 'var(--text-muted)' }">{{ call.timestamp }}</td>
                  <td class="px-3 py-2 text-xs font-mono" :style="{ color: 'var(--primary)' }">{{ call.tool }}</td>
                  <td class="px-3 py-2">
                    <span class="badge" :class="call.success ? 'badge-success' : 'badge-error'">
                      {{ call.success ? 'OK' : 'Error' }}
                    </span>
                  </td>
                  <td class="px-3 py-2 text-xs" :style="{ color: 'var(--text-muted)' }">{{ call.caller }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'

const notify = useNotificationsStore()

const mcpOnline = ref(false)
const mcpToken = ref('')
const showToken = ref(false)
const mcpCalls = ref([])
const mcpTools = reactive([])

const maskedToken = computed(() => {
  if (!mcpToken.value) return ''
  return mcpToken.value.slice(0, 8) + '...' + mcpToken.value.slice(-4)
})

const serverUrl = computed(() => window.location.origin)

const claudeConfig = computed(() => JSON.stringify({
  mcpServers: {
    hosthive: {
      url: `${serverUrl.value}/api/v1/mcp`,
      headers: {
        Authorization: `Bearer ${mcpToken.value || '<YOUR_MCP_TOKEN>'}`
      }
    }
  }
}, null, 2))

const cursorConfig = computed(() => JSON.stringify({
  "mcp.servers": {
    hosthive: {
      type: "http",
      url: `${serverUrl.value}/api/v1/mcp`,
      token: mcpToken.value || '<YOUR_MCP_TOKEN>'
    }
  }
}, null, 2))

const genericConfig = computed(() => JSON.stringify({
  server: {
    name: "hosthive",
    type: "streamable-http",
    url: `${serverUrl.value}/api/v1/mcp`,
    auth: {
      type: "bearer",
      token: mcpToken.value || '<YOUR_MCP_TOKEN>'
    }
  }
}, null, 2))

async function copyToken() {
  try {
    await navigator.clipboard.writeText(mcpToken.value)
    notify.success('Token copied to clipboard')
  } catch {
    notify.error('Failed to copy')
  }
}

async function copyConfig(type) {
  const configs = { claude: claudeConfig.value, cursor: cursorConfig.value, generic: genericConfig.value }
  try {
    await navigator.clipboard.writeText(configs[type])
    notify.success('Configuration copied')
  } catch {
    notify.error('Failed to copy')
  }
}

async function regenerateToken() {
  try {
    const { data } = await client.post('/mcp/token/regenerate')
    mcpToken.value = data.token
    notify.success('MCP token regenerated')
  } catch {
    notify.error('Failed to regenerate token')
  }
}

onMounted(async () => {
  try {
    const { data } = await client.get('/mcp/status')
    mcpOnline.value = data.online
    mcpToken.value = data.token || ''

    if (data.tools) {
      data.tools.forEach(t => mcpTools.push({ ...t, expanded: false }))
    }

    if (data.recent_calls) {
      mcpCalls.value = data.recent_calls
    }
  } catch {}
})
</script>

<style scoped>
.expand-enter-active,
.expand-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}
.expand-enter-from,
.expand-leave-to {
  max-height: 0;
  opacity: 0;
}
.expand-enter-to,
.expand-leave-from {
  max-height: 300px;
  opacity: 1;
}
</style>
