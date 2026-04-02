<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">AI Settings</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">Configure AI provider and behavior</p>
      </div>
    </div>

    <div class="grid grid-cols-1 xl:grid-cols-3 gap-6">
      <!-- Main Settings -->
      <div class="xl:col-span-2 space-y-6">
        <!-- Provider -->
        <div class="glass rounded-2xl p-6">
          <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">AI Provider</h3>
          <div class="grid grid-cols-3 gap-4">
            <button
              v-for="p in providers"
              :key="p.value"
              class="glass rounded-xl p-5 text-center cursor-pointer transition-all"
              :class="form.provider === p.value ? 'ring-2 ring-primary' : ''"
              @click="form.provider = p.value"
            >
              <div class="text-3xl mb-2" v-html="p.icon"></div>
              <div class="text-sm font-semibold" :style="{ color: 'var(--text-primary)' }">{{ p.label }}</div>
              <div class="text-xs mt-1" :style="{ color: 'var(--text-muted)' }">{{ p.description }}</div>
            </button>
          </div>
        </div>

        <!-- Model & Connection -->
        <div class="glass rounded-2xl p-6">
          <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">Connection</h3>
          <div class="space-y-4">
            <!-- Model -->
            <div>
              <label class="input-label">Model</label>
              <select v-model="form.model" class="w-full">
                <option v-for="m in filteredModels" :key="m" :value="m">{{ m }}</option>
              </select>
            </div>

            <!-- API Key -->
            <div v-if="form.provider !== 'ollama'">
              <label class="input-label">API Key</label>
              <div class="flex gap-2">
                <input
                  v-model="form.apiKey"
                  :type="showApiKey ? 'text' : 'password'"
                  class="flex-1"
                  :placeholder="form.provider === 'openai' ? 'sk-...' : 'sk-ant-...'"
                />
                <button class="btn-ghost text-xs px-3" @click="showApiKey = !showApiKey">
                  {{ showApiKey ? 'Hide' : 'Show' }}
                </button>
              </div>
            </div>

            <!-- Base URL (Ollama) -->
            <div v-if="form.provider === 'ollama'">
              <label class="input-label">Base URL</label>
              <input v-model="form.baseUrl" class="w-full" placeholder="http://localhost:11434" />
            </div>

            <!-- Test Connection -->
            <div class="flex items-center gap-3">
              <button class="btn-secondary" :disabled="testingConnection" @click="testConnection">
                <span v-if="testingConnection" class="animate-spin">&#8635;</span>
                {{ testingConnection ? 'Testing...' : 'Test Connection' }}
              </button>
              <span v-if="connectionResult" class="text-sm" :style="{ color: connectionResult.success ? 'var(--success)' : 'var(--error)' }">
                {{ connectionResult.message }}
              </span>
            </div>
          </div>
        </div>

        <!-- Behavior -->
        <div class="glass rounded-2xl p-6">
          <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">Behavior</h3>
          <div class="space-y-5">
            <!-- Auto-fix -->
            <div class="flex items-center justify-between">
              <div>
                <label class="input-label mb-0">Auto-fix</label>
                <p class="text-xs" :style="{ color: 'var(--text-muted)' }">Automatically apply AI-suggested fixes to your server</p>
              </div>
              <button
                class="w-12 h-6 rounded-full transition-colors relative"
                :style="{ background: form.autoFix ? 'var(--primary)' : 'var(--border)' }"
                @click="form.autoFix = !form.autoFix"
              >
                <span
                  class="absolute top-1 w-4 h-4 rounded-full bg-white transition-transform"
                  :style="{ left: form.autoFix ? '28px' : '4px' }"
                ></span>
              </button>
            </div>
            <div v-if="form.autoFix" class="glass rounded-lg p-3 flex items-start gap-2" :style="{ borderColor: 'var(--warning)' }">
              <span :style="{ color: 'var(--warning)' }">&#9888;</span>
              <p class="text-xs" :style="{ color: 'var(--warning)' }">
                Auto-fix will apply changes to your server configuration without manual confirmation. Use with caution.
              </p>
            </div>

            <!-- Log Analysis Interval -->
            <div>
              <label class="input-label">Log Analysis Interval</label>
              <select v-model="form.logAnalysisInterval" class="w-full">
                <option value="1h">Every hour</option>
                <option value="6h">Every 6 hours</option>
                <option value="daily">Daily</option>
                <option value="disabled">Disabled</option>
              </select>
              <p class="text-xs mt-1" :style="{ color: 'var(--text-muted)' }">How often the AI analyzes server logs for insights</p>
            </div>

            <!-- Token Limit -->
            <div>
              <label class="input-label">Token Limit per Request: {{ form.tokenLimit }}</label>
              <input
                v-model.number="form.tokenLimit"
                type="range"
                min="500"
                max="5000"
                step="100"
                class="w-full"
                style="border: none; padding: 0; box-shadow: none;"
              />
              <div class="flex justify-between text-xs" :style="{ color: 'var(--text-muted)' }">
                <span>500</span><span>2500</span><span>5000</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Save -->
        <div class="flex justify-end gap-3">
          <button class="btn-secondary" @click="resetForm">Reset</button>
          <button class="btn-primary" @click="save">Save Settings</button>
        </div>
      </div>

      <!-- Token Usage Sidebar -->
      <div>
        <div class="glass rounded-2xl p-6">
          <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">Token Usage (30 Days)</h3>
          <div class="h-64 flex items-end gap-1">
            <div
              v-for="(bar, i) in tokenUsage"
              :key="i"
              class="flex-1 rounded-t transition-all duration-300 cursor-pointer relative group"
              :style="{
                height: (bar.tokens / maxTokenUsage * 100) + '%',
                background: 'var(--primary)',
                opacity: 0.3 + (bar.tokens / maxTokenUsage) * 0.7,
                minHeight: '2px'
              }"
            >
              <div class="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block z-10">
                <div class="glass-strong rounded px-2 py-1 text-[10px] whitespace-nowrap" :style="{ color: 'var(--text-primary)' }">
                  {{ bar.date }}: {{ bar.tokens.toLocaleString() }} tokens
                </div>
              </div>
            </div>
          </div>
          <div class="flex justify-between text-xs mt-2" :style="{ color: 'var(--text-muted)' }">
            <span>30d ago</span>
            <span>Today</span>
          </div>

          <!-- Summary -->
          <div class="mt-6 space-y-3">
            <div class="flex justify-between text-sm">
              <span :style="{ color: 'var(--text-muted)' }">Total tokens</span>
              <span class="font-medium" :style="{ color: 'var(--text-primary)' }">{{ totalTokens.toLocaleString() }}</span>
            </div>
            <div class="flex justify-between text-sm">
              <span :style="{ color: 'var(--text-muted)' }">Avg/day</span>
              <span class="font-medium" :style="{ color: 'var(--text-primary)' }">{{ avgTokensPerDay.toLocaleString() }}</span>
            </div>
            <div class="flex justify-between text-sm">
              <span :style="{ color: 'var(--text-muted)' }">Conversations</span>
              <span class="font-medium" :style="{ color: 'var(--text-primary)' }">{{ conversationCount }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useAiStore } from '@/stores/ai'
import { useNotificationsStore } from '@/stores/notifications'
import client from '@/api/client'

const ai = useAiStore()
const notify = useNotificationsStore()

const showApiKey = ref(false)
const testingConnection = ref(false)
const connectionResult = ref(null)
const tokenUsage = ref([])
const conversationCount = ref(0)

const form = ref({
  provider: 'openai',
  model: 'gpt-4o',
  apiKey: '',
  baseUrl: 'http://localhost:11434',
  autoFix: false,
  logAnalysisInterval: 'daily',
  tokenLimit: 2000
})

const providers = [
  { value: 'openai', label: 'OpenAI', icon: '&#9679;', description: 'GPT-4, GPT-3.5' },
  { value: 'anthropic', label: 'Anthropic', icon: '&#9830;', description: 'Claude 3 family' },
  { value: 'ollama', label: 'Ollama', icon: '&#9881;', description: 'Local models' }
]

const modelsByProvider = {
  openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo'],
  anthropic: ['claude-sonnet-4-20250514', 'claude-haiku-4-5-20251001', 'claude-opus-4-20250514'],
  ollama: ['llama3', 'llama3.1', 'mistral', 'codellama', 'phi3', 'gemma2']
}

const fetchedModels = ref([])
const fetchingModels = ref(false)

const filteredModels = computed(() => {
  if (fetchedModels.value.length > 0) return fetchedModels.value
  return modelsByProvider[form.value.provider] || []
})

async function fetchModels() {
  fetchingModels.value = true
  try {
    const { data } = await client.get('/ai/models')
    if (data.models && data.models.length > 0) {
      fetchedModels.value = data.models.map(m => m.id || m)
    }
  } catch {
    // Fall back to hardcoded list
    fetchedModels.value = []
  } finally {
    fetchingModels.value = false
  }
}

const totalTokens = computed(() => tokenUsage.value.reduce((sum, d) => sum + d.tokens, 0))
const avgTokensPerDay = computed(() => {
  if (!tokenUsage.value.length) return 0
  return Math.round(totalTokens.value / tokenUsage.value.length)
})
const maxTokenUsage = computed(() => Math.max(...tokenUsage.value.map(d => d.tokens), 1))

async function testConnection() {
  testingConnection.value = true
  connectionResult.value = null
  try {
    const { data } = await client.post('/ai/test-connection', {
      provider: form.value.provider,
      api_key: form.value.apiKey,
      base_url: form.value.baseUrl,
      model: form.value.model
    })
    connectionResult.value = { success: true, message: data.message || 'Connection successful' }
  } catch (err) {
    connectionResult.value = { success: false, message: err.response?.data?.detail || 'Connection failed' }
  } finally {
    testingConnection.value = false
  }
}

function resetForm() {
  form.value = { ...ai.settings }
  connectionResult.value = null
}

async function save() {
  await ai.updateSettings(form.value)
}

// When the provider changes, clear fetched models and reset model selection
watch(() => form.value.provider, (newProvider) => {
  fetchedModels.value = []
  const defaults = modelsByProvider[newProvider]
  if (defaults && defaults.length > 0) {
    form.value.model = defaults[0]
  }
  // Try to fetch fresh models from the backend
  fetchModels()
})

onMounted(async () => {
  try {
    await ai.fetchSettings()
    form.value = { ...ai.settings }
  } catch {}

  // Try to auto-fetch models from backend
  fetchModels()

  try {
    const { data } = await client.get('/ai/usage')
    tokenUsage.value = data.daily || []
    conversationCount.value = data.conversations || 0
  } catch {}
})
</script>
