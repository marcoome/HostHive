<template>
  <div class="space-y-6">
    <!-- Page Header -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">Integrations</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">
          Connect external services to extend HostHive functionality
        </p>
      </div>
    </div>

    <!-- Integration Cards Grid -->
    <div v-if="store.loading" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <div v-for="i in 9" :key="i" class="glass rounded-2xl p-6">
        <div class="flex items-start justify-between mb-4">
          <div class="flex items-center gap-3">
            <div class="skeleton w-10 h-10 rounded-lg"></div>
            <div>
              <div class="skeleton h-4 w-24 mb-2"></div>
              <div class="skeleton h-3 w-16"></div>
            </div>
          </div>
          <div class="skeleton h-6 w-10 rounded-full"></div>
        </div>
        <div class="flex gap-2 mt-4">
          <div class="skeleton h-8 w-24 rounded"></div>
          <div class="skeleton h-8 w-32 rounded"></div>
        </div>
      </div>
    </div>

    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <div
        v-for="intg in integrationCards"
        :key="intg.name"
        class="glass rounded-2xl p-6 relative overflow-hidden"
        :style="{ borderLeft: `4px solid ${intg.color}` }"
      >
        <!-- Card Header -->
        <div class="flex items-start justify-between mb-4">
          <div class="flex items-center gap-3">
            <!-- v-html safe: icon is a hardcoded HTML entity from trusted source, not user input -->
            <div
              class="w-10 h-10 rounded-lg flex items-center justify-center text-white text-lg"
              :style="{ background: intg.color }"
              v-html="intg.icon"
            ></div>
            <div>
              <h3 class="font-semibold text-sm" :style="{ color: 'var(--text-primary)' }">{{ intg.label }}</h3>
              <StatusBadge
                :status="getStatusKey(intg)"
                :label="getStatusLabel(intg)"
              />
            </div>
          </div>
          <!-- Toggle -->
          <label class="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              class="sr-only peer"
              :checked="intg.data?.enabled"
              @change="handleToggle(intg.name)"
            />
            <div class="w-9 h-5 bg-gray-600 peer-focus:ring-2 peer-focus:ring-primary/20 rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-[var(--success)]"></div>
          </label>
        </div>

        <!-- Actions -->
        <div class="flex gap-2 mt-4">
          <button class="btn-secondary text-xs px-3 py-1.5" @click="openConfig(intg)">
            Configure
          </button>
          <button
            class="btn-ghost text-xs px-3 py-1.5"
            :disabled="testingMap[intg.name]"
            @click="handleTest(intg.name)"
          >
            <span v-if="testingMap[intg.name]" class="inline-block w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin mr-1"></span>
            Test Connection
          </button>
        </div>
      </div>
    </div>

    <!-- Config Modal -->
    <Modal v-model="showConfigModal" :title="`Configure ${activeIntegration?.label || ''}`" size="lg">
      <div v-if="activeIntegration" class="space-y-4">
        <!-- Cloudflare -->
        <template v-if="activeIntegration.name === 'cloudflare'">
          <div>
            <label class="input-label">API Key</label>
            <div class="relative">
              <input
                :type="showFields.cloudflare_api_key ? 'text' : 'password'"
                v-model="configForm.api_key"
                class="w-full pr-10"
                placeholder="Enter Cloudflare API key"
              />
              <button class="absolute right-2 top-1/2 -translate-y-1/2 text-xs btn-ghost p-1" @click="showFields.cloudflare_api_key = !showFields.cloudflare_api_key">
                {{ showFields.cloudflare_api_key ? 'Hide' : 'Show' }}
              </button>
            </div>
          </div>
          <div>
            <label class="input-label">Email</label>
            <input type="email" v-model="configForm.email" class="w-full" placeholder="you@example.com" />
          </div>
          <div>
            <label class="input-label">Zone ID</label>
            <input type="text" v-model="configForm.zone_id" class="w-full" placeholder="Zone ID" />
          </div>
        </template>

        <!-- S3 Storage -->
        <template v-if="activeIntegration.name === 's3'">
          <div>
            <label class="input-label">Endpoint URL</label>
            <input type="url" v-model="configForm.endpoint_url" class="w-full" placeholder="https://s3.amazonaws.com" />
          </div>
          <div>
            <label class="input-label">Bucket</label>
            <input type="text" v-model="configForm.bucket" class="w-full" placeholder="my-bucket" />
          </div>
          <div>
            <label class="input-label">Access Key</label>
            <div class="relative">
              <input
                :type="showFields.s3_access_key ? 'text' : 'password'"
                v-model="configForm.access_key"
                class="w-full pr-10"
                placeholder="Access Key"
              />
              <button class="absolute right-2 top-1/2 -translate-y-1/2 text-xs btn-ghost p-1" @click="showFields.s3_access_key = !showFields.s3_access_key">
                {{ showFields.s3_access_key ? 'Hide' : 'Show' }}
              </button>
            </div>
          </div>
          <div>
            <label class="input-label">Secret Key</label>
            <div class="relative">
              <input
                :type="showFields.s3_secret_key ? 'text' : 'password'"
                v-model="configForm.secret_key"
                class="w-full pr-10"
                placeholder="Secret Key"
              />
              <button class="absolute right-2 top-1/2 -translate-y-1/2 text-xs btn-ghost p-1" @click="showFields.s3_secret_key = !showFields.s3_secret_key">
                {{ showFields.s3_secret_key ? 'Hide' : 'Show' }}
              </button>
            </div>
          </div>
          <div>
            <label class="input-label">Region</label>
            <input type="text" v-model="configForm.region" class="w-full" placeholder="us-east-1" />
          </div>
        </template>

        <!-- Telegram -->
        <template v-if="activeIntegration.name === 'telegram'">
          <div>
            <label class="input-label">Bot Token</label>
            <div class="relative">
              <input
                :type="showFields.telegram_token ? 'text' : 'password'"
                v-model="configForm.bot_token"
                class="w-full pr-10"
                placeholder="123456:ABC-DEF..."
              />
              <button class="absolute right-2 top-1/2 -translate-y-1/2 text-xs btn-ghost p-1" @click="showFields.telegram_token = !showFields.telegram_token">
                {{ showFields.telegram_token ? 'Hide' : 'Show' }}
              </button>
            </div>
          </div>
          <div>
            <label class="input-label">Chat ID</label>
            <input type="text" v-model="configForm.chat_id" class="w-full" placeholder="-1001234567890" />
          </div>
          <button class="btn-secondary text-sm" @click="handleTest('telegram')">
            Send Test Message
          </button>
        </template>

        <!-- Slack -->
        <template v-if="activeIntegration.name === 'slack'">
          <div>
            <label class="input-label">Webhook URL</label>
            <div class="relative">
              <input
                :type="showFields.slack_webhook ? 'text' : 'password'"
                v-model="configForm.webhook_url"
                class="w-full pr-10"
                placeholder="https://hooks.slack.com/services/..."
              />
              <button class="absolute right-2 top-1/2 -translate-y-1/2 text-xs btn-ghost p-1" @click="showFields.slack_webhook = !showFields.slack_webhook">
                {{ showFields.slack_webhook ? 'Hide' : 'Show' }}
              </button>
            </div>
          </div>
          <button class="btn-secondary text-sm" @click="handleTest('slack')">
            Send Test Message
          </button>
        </template>

        <!-- Discord -->
        <template v-if="activeIntegration.name === 'discord'">
          <div>
            <label class="input-label">Webhook URL</label>
            <div class="relative">
              <input
                :type="showFields.discord_webhook ? 'text' : 'password'"
                v-model="configForm.webhook_url"
                class="w-full pr-10"
                placeholder="https://discord.com/api/webhooks/..."
              />
              <button class="absolute right-2 top-1/2 -translate-y-1/2 text-xs btn-ghost p-1" @click="showFields.discord_webhook = !showFields.discord_webhook">
                {{ showFields.discord_webhook ? 'Hide' : 'Show' }}
              </button>
            </div>
          </div>
          <button class="btn-secondary text-sm" @click="handleTest('discord')">
            Send Test Message
          </button>
        </template>

        <!-- WHMCS / FossBilling -->
        <template v-if="activeIntegration.name === 'whmcs'">
          <div>
            <label class="input-label">API URL</label>
            <input type="url" v-model="configForm.api_url" class="w-full" placeholder="https://billing.example.com/api" />
          </div>
          <div>
            <label class="input-label">API Key</label>
            <div class="relative">
              <input
                :type="showFields.whmcs_key ? 'text' : 'password'"
                v-model="configForm.api_key"
                class="w-full pr-10"
                placeholder="API Key"
              />
              <button class="absolute right-2 top-1/2 -translate-y-1/2 text-xs btn-ghost p-1" @click="showFields.whmcs_key = !showFields.whmcs_key">
                {{ showFields.whmcs_key ? 'Hide' : 'Show' }}
              </button>
            </div>
          </div>
          <div>
            <label class="input-label">Allowed IPs (one per line)</label>
            <textarea v-model="configForm.allowed_ips" class="w-full h-24" placeholder="192.168.1.1&#10;10.0.0.1"></textarea>
          </div>
        </template>

        <!-- Stripe -->
        <template v-if="activeIntegration.name === 'stripe'">
          <div>
            <label class="input-label">Secret Key</label>
            <div class="relative">
              <input
                :type="showFields.stripe_secret ? 'text' : 'password'"
                v-model="configForm.secret_key"
                class="w-full pr-10"
                placeholder="sk_live_..."
              />
              <button class="absolute right-2 top-1/2 -translate-y-1/2 text-xs btn-ghost p-1" @click="showFields.stripe_secret = !showFields.stripe_secret">
                {{ showFields.stripe_secret ? 'Hide' : 'Show' }}
              </button>
            </div>
          </div>
          <div>
            <label class="input-label">Webhook Secret</label>
            <div class="relative">
              <input
                :type="showFields.stripe_webhook ? 'text' : 'password'"
                v-model="configForm.webhook_secret"
                class="w-full pr-10"
                placeholder="whsec_..."
              />
              <button class="absolute right-2 top-1/2 -translate-y-1/2 text-xs btn-ghost p-1" @click="showFields.stripe_webhook = !showFields.stripe_webhook">
                {{ showFields.stripe_webhook ? 'Hide' : 'Show' }}
              </button>
            </div>
          </div>
          <div>
            <label class="input-label">Currency</label>
            <select v-model="configForm.currency" class="w-full">
              <option value="USD">USD - US Dollar</option>
              <option value="EUR">EUR - Euro</option>
              <option value="GBP">GBP - British Pound</option>
              <option value="CAD">CAD - Canadian Dollar</option>
              <option value="AUD">AUD - Australian Dollar</option>
              <option value="JPY">JPY - Japanese Yen</option>
            </select>
          </div>
        </template>

        <!-- Grafana -->
        <template v-if="activeIntegration.name === 'grafana'">
          <p class="text-sm" :style="{ color: 'var(--text-muted)' }">
            Prometheus and Grafana integration is controlled via the toggle switch. When enabled, HostHive will expose metrics at <code class="px-1 py-0.5 rounded text-xs" :style="{ background: 'var(--surface-elevated)' }">/metrics</code> for Prometheus scraping.
          </p>
        </template>

        <!-- WireGuard -->
        <template v-if="activeIntegration.name === 'wireguard'">
          <div>
            <label class="input-label">Endpoint</label>
            <input type="text" v-model="configForm.endpoint" class="w-full" placeholder="vpn.example.com" />
          </div>
          <div>
            <label class="input-label">Listen Port</label>
            <input type="number" v-model="configForm.listen_port" class="w-full" placeholder="51820" />
          </div>
          <div>
            <label class="input-label">Address Range</label>
            <input type="text" v-model="configForm.address_range" class="w-full" placeholder="10.0.0.0/24" />
          </div>
        </template>
      </div>

      <template #actions>
        <button class="btn-secondary" @click="showConfigModal = false">Cancel</button>
        <button class="btn-primary" :disabled="saving" @click="saveConfig">
          <span v-if="saving" class="inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin mr-1"></span>
          Save Configuration
        </button>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useIntegrationsStore } from '@/stores/integrations'
import Modal from '@/components/Modal.vue'
import StatusBadge from '@/components/StatusBadge.vue'

const store = useIntegrationsStore()

const showConfigModal = ref(false)
const activeIntegration = ref(null)
const configForm = reactive({})
const saving = ref(false)
const testingMap = reactive({})
const showFields = reactive({})

const integrationDefs = [
  { name: 'cloudflare', label: 'Cloudflare', icon: '&#9729;', color: '#f38020' },
  { name: 's3', label: 'S3 Storage', icon: '&#9641;', color: '#e47911' },
  { name: 'telegram', label: 'Telegram', icon: '&#9993;', color: '#229ED9' },
  { name: 'slack', label: 'Slack', icon: '&#35;', color: '#7C3AED' },
  { name: 'discord', label: 'Discord', icon: '&#127918;', color: '#5865F2' },
  { name: 'whmcs', label: 'WHMCS / FossBilling', icon: '&#9783;', color: '#22c55e' },
  { name: 'stripe', label: 'Stripe', icon: '&#9902;', color: '#635BFF' },
  { name: 'grafana', label: 'Prometheus / Grafana', icon: '&#9636;', color: '#e47911' },
  { name: 'wireguard', label: 'WireGuard VPN', icon: '&#9961;', color: '#22c55e' }
]

const integrationCards = computed(() => {
  return integrationDefs.map(def => {
    const data = store.integrations.find(i => i.name === def.name) || null
    return { ...def, data }
  })
})

function getStatusKey(intg) {
  if (!intg.data || !intg.data.configured) return 'disabled'
  if (intg.data.enabled && intg.data.connected) return 'active'
  if (intg.data.enabled && !intg.data.connected) return 'error'
  return 'disabled'
}

function getStatusLabel(intg) {
  if (!intg.data || !intg.data.configured) return 'Not configured'
  if (intg.data.enabled && intg.data.connected) return 'Connected'
  if (intg.data.enabled && !intg.data.connected) return 'Disconnected'
  return 'Disabled'
}

async function handleToggle(name) {
  await store.toggleIntegration(name)
}

async function handleTest(name) {
  testingMap[name] = true
  try {
    await store.testConnection(name)
  } finally {
    testingMap[name] = false
  }
}

function openConfig(intg) {
  activeIntegration.value = intg
  // Pre-fill form with existing config
  Object.keys(configForm).forEach(k => delete configForm[k])
  if (intg.data?.config) {
    Object.assign(configForm, intg.data.config)
  }
  showConfigModal.value = true
}

async function saveConfig() {
  saving.value = true
  try {
    await store.updateIntegration(activeIntegration.value.name, { ...configForm })
    showConfigModal.value = false
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  store.fetchIntegrations()
})
</script>
