<template>
  <div class="ai-assistant-widget">
    <!-- Floating Button -->
    <Transition name="fab">
      <button
        v-if="!isOpen"
        class="ai-fab"
        @click="isOpen = true"
      >
        <span class="ai-fab-icon">&#129424;</span>
        <span v-if="unreadCount > 0" class="ai-fab-badge">{{ unreadCount }}</span>
      </button>
    </Transition>

    <!-- Drawer -->
    <Transition name="drawer">
      <div v-if="isOpen" class="ai-drawer glass-strong">
        <!-- Header -->
        <div class="ai-drawer-header">
          <div class="flex items-center gap-2">
            <span class="text-lg">&#129424;</span>
            <span class="font-semibold text-sm" :style="{ color: 'var(--text-primary)' }">AI Assistant</span>
          </div>
          <div class="flex items-center gap-1">
            <span
              class="text-[10px] px-2 py-0.5 rounded-full"
              :style="{ background: 'rgba(var(--primary-rgb), 0.1)', color: 'var(--primary)' }"
            >
              {{ currentPage }}
            </span>
            <button
              class="p-1 rounded hover:bg-background text-text-muted hover:text-text-primary transition-colors"
              @click="isOpen = false"
            >
              &#10005;
            </button>
          </div>
        </div>

        <!-- Quick Actions -->
        <div class="px-4 py-2 flex gap-2 overflow-x-auto" :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
          <button
            v-for="action in quickActions"
            :key="action.label"
            class="text-[11px] px-3 py-1.5 rounded-full whitespace-nowrap flex-shrink-0 transition-colors"
            :style="{ background: 'rgba(var(--primary-rgb), 0.1)', color: 'var(--primary)' }"
            @click="sendQuickAction(action.prompt)"
          >
            {{ action.label }}
          </button>
        </div>

        <!-- Messages -->
        <div ref="drawerMessages" class="ai-drawer-messages">
          <div v-if="!messages.length" class="flex items-center justify-center h-full">
            <div class="text-center px-6">
              <div class="text-4xl mb-3">&#129302;</div>
              <p class="text-sm" :style="{ color: 'var(--text-muted)' }">Ask me anything about your server, or use a quick action above.</p>
            </div>
          </div>

          <div
            v-for="(msg, i) in messages"
            :key="i"
            class="flex px-4 py-1.5"
            :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
          >
            <div
              class="max-w-[85%] rounded-2xl px-3 py-2 text-xs leading-relaxed"
              :class="msg.role === 'user' ? 'bg-primary text-white rounded-br-sm' : 'glass rounded-bl-sm'"
            >
              <div v-if="msg.role === 'assistant'" v-html="renderMarkdown(msg.content)"></div>
              <div v-else>{{ msg.content }}</div>
            </div>
          </div>

          <!-- Streaming -->
          <div v-if="streaming" class="flex px-4 py-1.5 justify-start">
            <div class="max-w-[85%] rounded-2xl px-3 py-2 text-xs leading-relaxed glass rounded-bl-sm">
              <div v-if="streamingText" v-html="renderMarkdown(streamingText)"></div>
              <div v-else class="typing-dots">
                <span></span><span></span><span></span>
              </div>
            </div>
          </div>
        </div>

        <!-- Input -->
        <div class="ai-drawer-input">
          <div class="flex gap-2">
            <input
              v-model="input"
              class="flex-1 text-xs"
              style="border-radius: 20px; padding: 8px 14px;"
              placeholder="Type a message..."
              @keydown.enter.exact.prevent="send"
            />
            <button
              class="btn-primary"
              style="border-radius: 50%; width: 36px; height: 36px; padding: 0; font-size: 14px;"
              :disabled="!input.trim() || streaming"
              @click="send"
            >
              &#9654;
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const isOpen = ref(false)
const input = ref('')
const messages = ref([])
const streaming = ref(false)
const streamingText = ref('')
const unreadCount = ref(0)
const drawerMessages = ref(null)

const currentPage = computed(() => {
  const name = route.name || route.path
  return typeof name === 'string' ? name.replace(/-/g, ' ') : 'page'
})

const quickActions = [
  { label: 'Diagnose domain', prompt: 'Diagnose issues with my domains' },
  { label: 'Optimize server', prompt: 'Suggest server optimizations' },
  { label: 'Check security', prompt: 'Run a security check on my server' }
]

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function renderMarkdown(text) {
  if (!text) return ''
  // Escape ALL HTML first to prevent XSS, then apply markdown formatting
  return escapeHtml(text)
    .replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
      `<pre style="background:rgba(var(--bg-rgb),0.5);padding:8px;border-radius:6px;overflow-x:auto;font-size:10px;margin:4px 0;font-family:monospace;"><code>${code.trim()}</code></pre>`)
    .replace(/`([^`]+)`/g, '<code style="background:rgba(var(--border-rgb),0.3);padding:1px 4px;border-radius:3px;font-size:0.9em;font-family:monospace;">$1</code>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/\n/g, '<br>')
}

async function send() {
  const text = input.value.trim()
  if (!text || streaming.value) return
  input.value = ''
  messages.value.push({ role: 'user', content: text })

  streaming.value = true
  streamingText.value = ''

  try {
    const tokens = JSON.parse(localStorage.getItem('hosthive_tokens') || '{}')
    const response = await fetch('/api/v1/ai/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${tokens.access}`
      },
      body: JSON.stringify({
        message: text,
        context: currentPage.value
      })
    })

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const payload = line.slice(6)
          if (payload === '[DONE]') break
          try {
            const parsed = JSON.parse(payload)
            if (parsed.content) streamingText.value += parsed.content
          } catch {
            streamingText.value += payload
          }
        }
      }
    }

    messages.value.push({ role: 'assistant', content: streamingText.value })
  } catch {
    messages.value.push({ role: 'assistant', content: 'Sorry, I encountered an error.' })
  } finally {
    streaming.value = false
    streamingText.value = ''
  }
}

function sendQuickAction(prompt) {
  input.value = prompt
  send()
}

function scrollToBottom() {
  if (drawerMessages.value) {
    drawerMessages.value.scrollTop = drawerMessages.value.scrollHeight
  }
}

watch(() => messages.value.length, () => nextTick(scrollToBottom))
watch(streamingText, () => nextTick(scrollToBottom))

watch(isOpen, (val) => {
  if (val) unreadCount.value = 0
})
</script>

<style scoped>
.ai-assistant-widget {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 999;
}

.ai-fab {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  background: var(--primary);
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 20px rgba(var(--primary-rgb), 0.4);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  position: relative;
}

.ai-fab:hover {
  transform: scale(1.08);
  box-shadow: 0 6px 30px rgba(var(--primary-rgb), 0.5);
}

.ai-fab-icon {
  font-size: 28px;
  line-height: 1;
}

.ai-fab-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--error);
  color: white;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ai-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 420px;
  max-width: 100vw;
  display: flex;
  flex-direction: column;
  z-index: 1000;
}

.ai-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(var(--border-rgb), 0.3);
}

.ai-drawer-messages {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.ai-drawer-input {
  padding: 12px 16px;
  border-top: 1px solid rgba(var(--border-rgb), 0.3);
}

.typing-dots {
  display: flex;
  gap: 3px;
  padding: 2px 0;
}
.typing-dots span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary);
  animation: dot-bounce 1.4s infinite ease-in-out both;
}
.typing-dots span:nth-child(1) { animation-delay: -0.32s; }
.typing-dots span:nth-child(2) { animation-delay: -0.16s; }

@keyframes dot-bounce {
  0%, 80%, 100% { transform: scale(0); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

/* Transitions */
.fab-enter-active,
.fab-leave-active {
  transition: all 0.3s ease;
}
.fab-enter-from,
.fab-leave-to {
  transform: scale(0);
  opacity: 0;
}

.drawer-enter-active,
.drawer-leave-active {
  transition: transform 0.3s ease;
}
.drawer-enter-from,
.drawer-leave-to {
  transform: translateX(100%);
}
</style>
