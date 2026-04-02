<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-bold" :style="{ color: 'var(--text-primary)' }">AI Assistant</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">Chat with AI and view intelligent insights</p>
      </div>
      <button class="btn-secondary" @click="showSettings = true">
        <span>&#9881;</span> Settings
      </button>
    </div>

    <div class="flex gap-6" style="height: calc(100vh - 180px);">
      <!-- Left Panel: Chat (60%) -->
      <div class="flex-[3] flex flex-col glass rounded-2xl overflow-hidden">
        <div class="flex h-full">
          <!-- Conversation Sidebar -->
          <Transition name="slide-sidebar">
            <div
              v-if="showSidebar"
              class="w-56 flex-shrink-0 flex flex-col"
              :style="{ borderRight: '1px solid rgba(var(--border-rgb), 0.3)' }"
            >
              <div class="p-3 flex items-center justify-between" :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
                <span class="text-xs font-semibold uppercase tracking-wider" :style="{ color: 'var(--text-muted)' }">History</span>
                <button class="btn-ghost text-xs px-2 py-1" @click="ai.startNewConversation()">+ New</button>
              </div>
              <div class="flex-1 overflow-y-auto p-2 space-y-1">
                <div
                  v-for="conv in ai.conversations"
                  :key="conv.id"
                  class="px-3 py-2 rounded-lg text-xs cursor-pointer transition-colors truncate"
                  :class="ai.currentConversation?.id === conv.id ? 'bg-primary/10 text-primary' : 'hover:bg-surface/50'"
                  :style="{ color: ai.currentConversation?.id === conv.id ? 'var(--primary)' : 'var(--text-muted)' }"
                  @click="ai.selectConversation(conv)"
                >
                  {{ conv.title || 'Untitled' }}
                </div>
                <div v-if="ai.conversations.length === 0" class="text-xs text-center py-4" :style="{ color: 'var(--text-muted)' }">
                  No conversations yet
                </div>
              </div>
            </div>
          </Transition>

          <!-- Chat Area -->
          <div class="flex-1 flex flex-col min-w-0">
            <!-- Chat Header -->
            <div class="px-4 py-3 flex items-center gap-3" :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
              <button class="btn-ghost text-xs px-2 py-1" @click="showSidebar = !showSidebar">
                &#9776;
              </button>
              <span class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">
                {{ ai.currentConversation?.title || 'New Conversation' }}
              </span>
            </div>

            <!-- Messages -->
            <div ref="messagesContainer" class="flex-1 overflow-y-auto p-4 space-y-4">
              <div v-if="!currentMessages.length" class="flex items-center justify-center h-full">
                <div class="text-center">
                  <div class="text-5xl mb-4">&#129302;</div>
                  <h3 class="text-lg font-semibold mb-2" :style="{ color: 'var(--text-primary)' }">How can I help?</h3>
                  <p class="text-sm" :style="{ color: 'var(--text-muted)' }">Ask about server configuration, troubleshoot issues, or optimize your setup.</p>
                </div>
              </div>

              <div
                v-for="(msg, i) in currentMessages"
                :key="i"
                class="flex"
                :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
              >
                <div
                  class="max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed"
                  :class="msg.role === 'user' ? 'bg-primary text-white rounded-br-sm' : 'glass-strong rounded-bl-sm'"
                >
                  <div v-if="msg.role === 'assistant'" class="ai-message" v-html="renderMarkdown(msg.content)"></div>
                  <div v-else>{{ msg.content }}</div>
                </div>
              </div>

              <!-- Streaming indicator -->
              <div v-if="ai.streaming" class="flex justify-start">
                <div class="max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed glass-strong rounded-bl-sm">
                  <div v-if="ai.streamingText" class="ai-message" v-html="renderMarkdown(ai.streamingText)"></div>
                  <div v-else class="typing-indicator">
                    <span></span><span></span><span></span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Input Bar -->
            <div class="p-4" :style="{ borderTop: '1px solid rgba(var(--border-rgb), 0.3)' }">
              <div class="flex gap-2">
                <textarea
                  v-model="messageInput"
                  placeholder="Ask anything about your server..."
                  class="flex-1 resize-none text-sm"
                  style="min-height: 44px; max-height: 120px; border-radius: 12px;"
                  rows="1"
                  @keydown.enter.exact.prevent="sendMessage"
                  @input="autoResize"
                ></textarea>
                <button
                  class="btn-primary self-end"
                  style="border-radius: 12px; height: 44px; width: 44px; padding: 0;"
                  :disabled="!messageInput.trim() || ai.streaming"
                  @click="sendMessage"
                >
                  &#9654;
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Right Panel (40%) -->
      <div class="flex-[2] flex flex-col gap-4 overflow-y-auto">
        <!-- AI Insights -->
        <div class="glass rounded-2xl p-5">
          <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">AI Insights</h3>
          <div class="space-y-3">
            <div v-if="ai.insights.length === 0" class="text-sm py-4 text-center" :style="{ color: 'var(--text-muted)' }">
              No insights available
            </div>
            <div
              v-for="insight in ai.insights"
              :key="insight.id"
              class="glass rounded-xl p-4"
            >
              <div class="flex items-start justify-between mb-2">
                <span
                  class="badge"
                  :class="{
                    'badge-error': insight.severity === 'critical',
                    'badge-warning': insight.severity === 'warning',
                    'badge-info': insight.severity === 'info',
                    'badge-success': insight.severity === 'low'
                  }"
                >
                  {{ insight.severity }}
                </span>
                <span class="text-xs" :style="{ color: 'var(--text-muted)' }">{{ insight.source }}</span>
              </div>
              <p class="text-sm mb-3" :style="{ color: 'var(--text-primary)' }">{{ insight.message }}</p>
              <div class="flex gap-2">
                <button class="btn-primary text-xs px-3 py-1" @click="ai.applyAutofix(insight.id)">
                  Auto-fix
                </button>
                <button class="btn-ghost text-xs px-3 py-1" @click="ai.resolveInsight(insight.id)">
                  Dismiss
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Security Score -->
        <div class="glass rounded-2xl p-5 flex items-center justify-center">
          <GaugeChart :value="securityScore" label="Security" :size="140" />
        </div>

        <!-- Quick Actions -->
        <div class="glass rounded-2xl p-5">
          <h3 class="text-sm font-semibold uppercase tracking-wider mb-4" :style="{ color: 'var(--text-muted)' }">Quick Actions</h3>
          <div class="grid grid-cols-1 gap-2">
            <button class="btn-secondary text-sm justify-start" @click="quickAction('Optimize my Nginx configuration')">
              <span>&#9889;</span> Optimize Nginx
            </button>
            <button class="btn-secondary text-sm justify-start" @click="quickAction('Run a full security scan on my server')">
              <span>&#9919;</span> Run Security Scan
            </button>
            <button class="btn-secondary text-sm justify-start" @click="quickAction('Help me install a new application')">
              <span>&#10010;</span> Install App
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Settings Modal -->
    <Modal v-model="showSettings" title="AI Settings" size="lg">
      <div class="space-y-5">
        <!-- Provider -->
        <div>
          <label class="input-label">AI Provider</label>
          <div class="grid grid-cols-3 gap-3">
            <button
              v-for="p in providers"
              :key="p.value"
              class="glass rounded-xl p-4 text-center cursor-pointer transition-all"
              :class="localSettings.provider === p.value ? 'ring-2 ring-primary' : ''"
              @click="localSettings.provider = p.value"
            >
              <div class="text-2xl mb-1">{{ p.icon }}</div>
              <div class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">{{ p.label }}</div>
            </button>
          </div>
        </div>

        <!-- Model -->
        <div>
          <label class="input-label">Model</label>
          <select v-model="localSettings.model" class="w-full">
            <option v-for="m in filteredModels" :key="m" :value="m">{{ m }}</option>
          </select>
        </div>

        <!-- API Key -->
        <div>
          <label class="input-label">API Key</label>
          <input v-model="localSettings.apiKey" :type="showApiKey ? 'text' : 'password'" class="w-full" placeholder="sk-..." />
          <button class="btn-ghost text-xs mt-1" @click="showApiKey = !showApiKey">
            {{ showApiKey ? 'Hide' : 'Show' }}
          </button>
        </div>

        <!-- Base URL (Ollama) -->
        <div v-if="localSettings.provider === 'ollama'">
          <label class="input-label">Base URL</label>
          <input v-model="localSettings.baseUrl" class="w-full" placeholder="http://localhost:11434" />
        </div>

        <!-- Auto-fix -->
        <div class="flex items-center justify-between">
          <div>
            <label class="input-label mb-0">Auto-fix</label>
            <p class="text-xs" :style="{ color: 'var(--text-muted)' }">Automatically apply AI-suggested fixes</p>
          </div>
          <button
            class="w-12 h-6 rounded-full transition-colors relative"
            :style="{ background: localSettings.autoFix ? 'var(--primary)' : 'var(--border)' }"
            @click="localSettings.autoFix = !localSettings.autoFix"
          >
            <span
              class="absolute top-1 w-4 h-4 rounded-full bg-white transition-transform"
              :style="{ left: localSettings.autoFix ? '28px' : '4px' }"
            ></span>
          </button>
        </div>
        <p v-if="localSettings.autoFix" class="text-xs" :style="{ color: 'var(--warning)' }">
          Warning: Auto-fix will make changes to your server configuration without confirmation.
        </p>

        <!-- Log Analysis Interval -->
        <div>
          <label class="input-label">Log Analysis Interval</label>
          <select v-model="localSettings.logAnalysisInterval" class="w-full">
            <option value="1h">Every hour</option>
            <option value="6h">Every 6 hours</option>
            <option value="daily">Daily</option>
            <option value="disabled">Disabled</option>
          </select>
        </div>

        <!-- Token Limit -->
        <div>
          <label class="input-label">Token Limit: {{ localSettings.tokenLimit }}</label>
          <input
            v-model.number="localSettings.tokenLimit"
            type="range"
            min="500"
            max="5000"
            step="100"
            class="w-full"
            style="border: none; padding: 0; box-shadow: none;"
          />
          <div class="flex justify-between text-xs" :style="{ color: 'var(--text-muted)' }">
            <span>500</span><span>5000</span>
          </div>
        </div>
      </div>

      <template #actions>
        <button class="btn-secondary" @click="showSettings = false">Cancel</button>
        <button class="btn-primary" @click="saveSettings">Save Settings</button>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useAiStore } from '@/stores/ai'
import Modal from '@/components/Modal.vue'
import GaugeChart from '@/components/GaugeChart.vue'

const ai = useAiStore()

const messageInput = ref('')
const showSidebar = ref(true)
const showSettings = ref(false)
const showApiKey = ref(false)
const messagesContainer = ref(null)
const securityScore = ref(72)

const localSettings = ref({ ...ai.settings })

const providers = [
  { value: 'openai', label: 'OpenAI', icon: '&#9679;' },
  { value: 'anthropic', label: 'Anthropic', icon: '&#9830;' },
  { value: 'ollama', label: 'Ollama', icon: '&#9881;' }
]

const modelsByProvider = {
  openai: ['gpt-4', 'gpt-4-turbo', 'gpt-3.5-turbo'],
  anthropic: ['claude-3-opus', 'claude-3-sonnet', 'claude-3-haiku'],
  ollama: ['llama3', 'mistral', 'codellama', 'phi3']
}

const filteredModels = computed(() => modelsByProvider[localSettings.value.provider] || [])

const currentMessages = computed(() => ai.currentConversation?.messages || [])

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function renderMarkdown(text) {
  if (!text) return ''
  // Escape ALL HTML first to prevent XSS, then apply markdown formatting
  let html = escapeHtml(text)
    .replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
      return `<div class="code-block-wrapper"><div class="code-block-header"><span class="code-lang">${lang || 'code'}</span><button class="code-copy-btn" onclick="navigator.clipboard.writeText(this.parentElement.nextElementSibling.textContent)">Copy</button></div><pre class="code-block"><code>${code.trim()}</code></pre></div>`
    })
    .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/\n/g, '<br>')
  return html
}

async function sendMessage() {
  const text = messageInput.value.trim()
  if (!text || ai.streaming) return
  messageInput.value = ''
  await ai.sendMessage(text)
  await nextTick()
  scrollToBottom()
}

function quickAction(prompt) {
  messageInput.value = prompt
  sendMessage()
}

function scrollToBottom() {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

function autoResize(e) {
  e.target.style.height = 'auto'
  e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px'
}

async function saveSettings() {
  await ai.updateSettings(localSettings.value)
  showSettings.value = false
}

watch(() => ai.streamingText, () => {
  nextTick(scrollToBottom)
})

watch(currentMessages, () => {
  nextTick(scrollToBottom)
}, { deep: true })

onMounted(async () => {
  try {
    await Promise.all([
      ai.fetchConversations(),
      ai.fetchInsights(),
      ai.fetchSettings()
    ])
    localSettings.value = { ...ai.settings }
  } catch {}
})
</script>

<style scoped>
.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}
.typing-indicator span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--primary);
  animation: typing-bounce 1.4s infinite ease-in-out both;
}
.typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
.typing-indicator span:nth-child(2) { animation-delay: -0.16s; }

@keyframes typing-bounce {
  0%, 80%, 100% { transform: scale(0); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

.slide-sidebar-enter-active,
.slide-sidebar-leave-active {
  transition: all 0.2s ease;
}
.slide-sidebar-enter-from,
.slide-sidebar-leave-to {
  width: 0;
  opacity: 0;
}

:deep(.code-block-wrapper) {
  margin: 8px 0;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid rgba(var(--border-rgb), 0.3);
}
:deep(.code-block-header) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 12px;
  background: rgba(var(--border-rgb), 0.2);
  font-size: 0.7rem;
}
:deep(.code-lang) {
  color: var(--text-muted);
  text-transform: uppercase;
  font-weight: 600;
}
:deep(.code-copy-btn) {
  background: none;
  border: none;
  color: var(--primary);
  cursor: pointer;
  font-size: 0.7rem;
  font-weight: 500;
}
:deep(.code-block) {
  margin: 0;
  padding: 12px;
  background: rgba(var(--bg-rgb), 0.5);
  overflow-x: auto;
  font-size: 0.8rem;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  line-height: 1.5;
}
:deep(.inline-code) {
  background: rgba(var(--border-rgb), 0.3);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.85em;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}
</style>
