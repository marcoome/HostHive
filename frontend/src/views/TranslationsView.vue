<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <h1 class="text-2xl font-semibold text-[var(--text-primary)]">Translation Manager</h1>
      <div class="flex items-center gap-3">
        <button class="btn-secondary" @click="showImportModal = true">Import JSON</button>
        <button class="btn-secondary" @click="exportLanguage">Export JSON</button>
        <button class="btn-primary" @click="showAddLangModal = true">Add Language</button>
      </div>
    </div>

    <!-- Language selector + progress -->
    <div class="glass rounded-2xl p-6">
      <div class="flex items-center gap-4 flex-wrap">
        <div class="flex-1 min-w-[200px]">
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Language</label>
          <select
            v-model="selectedLang"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
            @change="loadLanguage"
          >
            <option v-for="lang in languages" :key="lang.code" :value="lang.code">
              {{ lang.flag }} {{ lang.name }} ({{ lang.code }})
            </option>
          </select>
        </div>

        <div class="flex-1 min-w-[300px]">
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
            Progress: {{ translatedCount }} / {{ totalCount }} ({{ progressPercent }}%)
          </label>
          <div class="w-full h-3 bg-[var(--surface)] rounded-full overflow-hidden">
            <div
              class="h-full rounded-full transition-all duration-500"
              :class="progressPercent >= 90 ? 'bg-green-500' : progressPercent >= 50 ? 'bg-yellow-500' : 'bg-red-500'"
              :style="{ width: progressPercent + '%' }"
            ></div>
          </div>
        </div>

        <div v-if="selectedLang !== 'en'" class="flex items-center gap-2 pt-5">
          <button
            class="btn-secondary text-sm"
            @click="showMissing = !showMissing"
          >
            {{ showMissing ? 'Show All' : 'Show Missing Only' }}
          </button>
          <button
            class="btn-danger text-sm"
            @click="confirmDeleteLanguage"
          >
            Delete Language
          </button>
        </div>
      </div>
    </div>

    <!-- Search / Filter -->
    <div class="glass rounded-2xl p-4">
      <div class="flex items-center gap-4">
        <div class="flex-1 relative">
          <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
          </svg>
          <input
            v-model="searchQuery"
            type="text"
            placeholder="Search translation keys or values..."
            class="w-full pl-10 pr-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
        <div>
          <select
            v-model="sectionFilter"
            class="px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          >
            <option value="">All Sections</option>
            <option v-for="section in sections" :key="section" :value="section">
              {{ section }}
            </option>
          </select>
        </div>
      </div>
    </div>

    <!-- Translation table -->
    <div v-if="loading" class="glass rounded-2xl p-12 text-center">
      <div class="inline-block w-8 h-8 border-4 border-primary/30 border-t-primary rounded-full animate-spin"></div>
      <p class="mt-3 text-[var(--text-muted)]">Loading translations...</p>
    </div>

    <div v-else>
      <div
        v-for="section in filteredSections"
        :key="section"
        class="glass rounded-2xl mb-4 overflow-hidden"
      >
        <div
          class="flex items-center justify-between px-6 py-3 border-b border-[var(--border)] cursor-pointer"
          @click="toggleSection(section)"
        >
          <div class="flex items-center gap-3">
            <svg
              class="w-4 h-4 transition-transform text-[var(--text-muted)]"
              :class="{ 'rotate-90': expandedSections.has(section) }"
              fill="none" stroke="currentColor" viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
            </svg>
            <h3 class="text-sm font-semibold text-[var(--text-primary)] uppercase tracking-wide">{{ section }}</h3>
            <span class="text-xs text-[var(--text-muted)]">
              {{ getSectionProgress(section) }}
            </span>
          </div>
          <button
            class="btn-primary text-xs px-3 py-1"
            @click.stop="saveSection(section)"
            :disabled="saving"
          >
            Save Section
          </button>
        </div>

        <div v-if="expandedSections.has(section)">
          <table class="w-full">
            <thead>
              <tr class="border-b border-[var(--border)]">
                <th class="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-6 py-2 w-1/4">Key</th>
                <th class="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-6 py-2 w-[37.5%]">English (Reference)</th>
                <th class="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-6 py-2 w-[37.5%]">Translation</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="key in getFilteredKeys(section)"
                :key="key"
                class="border-b border-[var(--border)] last:border-0"
                :class="isMissing(section, key) ? 'bg-red-500/5' : ''"
              >
                <td class="px-6 py-2">
                  <code class="text-xs font-mono text-[var(--text-muted)]">{{ section }}.{{ key }}</code>
                </td>
                <td class="px-6 py-2">
                  <span class="text-sm text-[var(--text-muted)]">{{ enData[section]?.[key] || '' }}</span>
                </td>
                <td class="px-6 py-2">
                  <input
                    v-if="selectedLang !== 'en'"
                    v-model="langData[section][key]"
                    type="text"
                    class="w-full px-3 py-1.5 bg-[var(--surface)] border rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                    :class="isMissing(section, key) ? 'border-red-500/50' : 'border-[var(--border)]'"
                    :placeholder="enData[section]?.[key] || ''"
                  />
                  <span v-else class="text-sm text-[var(--text-primary)]">{{ enData[section]?.[key] || '' }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Save All button -->
    <div v-if="!loading && selectedLang !== 'en'" class="flex justify-end gap-3">
      <button
        class="btn-secondary"
        @click="autoTranslate"
        :disabled="autoTranslating"
      >
        <span v-if="autoTranslating" class="inline-block w-4 h-4 border-2 border-primary/30 border-t-primary rounded-full animate-spin mr-2"></span>
        {{ autoTranslating ? 'Translating...' : 'Auto-Translate Missing' }}
      </button>
      <button
        class="btn-primary"
        @click="saveAll"
        :disabled="saving"
      >
        <span v-if="saving" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
        {{ saving ? 'Saving...' : 'Save All' }}
      </button>
    </div>

    <!-- Add Language Modal -->
    <div
      v-if="showAddLangModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      @click.self="showAddLangModal = false"
    >
      <div class="glass rounded-2xl p-6 w-full max-w-md mx-4">
        <h2 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Add New Language</h2>
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Language Code</label>
            <input
              v-model="newLang.code"
              type="text"
              placeholder="e.g. de, ja, pt-BR"
              class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Display Name</label>
            <input
              v-model="newLang.name"
              type="text"
              placeholder="e.g. Deutsch, Japanese"
              class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Flag Emoji (optional)</label>
            <input
              v-model="newLang.flag"
              type="text"
              placeholder="e.g. flag emoji or code"
              class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
        </div>
        <div class="flex justify-end gap-3 mt-6">
          <button class="btn-secondary" @click="showAddLangModal = false">Cancel</button>
          <button class="btn-primary" @click="addLanguage" :disabled="!newLang.code || !newLang.name">Create</button>
        </div>
      </div>
    </div>

    <!-- Import Modal -->
    <div
      v-if="showImportModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      @click.self="showImportModal = false"
    >
      <div class="glass rounded-2xl p-6 w-full max-w-md mx-4">
        <h2 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Import Translation File</h2>
        <p class="text-sm text-[var(--text-muted)] mb-4">
          Upload a JSON file. The filename determines the language code (e.g. <code>de.json</code> for German).
        </p>
        <div class="space-y-4">
          <input
            ref="importFileInput"
            type="file"
            accept=".json"
            class="w-full text-sm text-[var(--text-primary)]"
            @change="handleFileSelect"
          />
        </div>
        <div class="flex justify-end gap-3 mt-6">
          <button class="btn-secondary" @click="showImportModal = false">Cancel</button>
          <button class="btn-primary" @click="importFile" :disabled="!importSelectedFile">Import</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import client from '@/api/client'

const loading = ref(true)
const saving = ref(false)
const autoTranslating = ref(false)
const languages = ref([])
const selectedLang = ref('en')
const enData = ref({})
const langData = ref({})
const searchQuery = ref('')
const sectionFilter = ref('')
const showMissing = ref(false)
const expandedSections = ref(new Set())
const showAddLangModal = ref(false)
const showImportModal = ref(false)
const importSelectedFile = ref(null)
const importFileInput = ref(null)

const newLang = reactive({ code: '', name: '', flag: '' })

// Computed
const sections = computed(() => Object.keys(enData.value).sort())

const filteredSections = computed(() => {
  let result = sections.value
  if (sectionFilter.value) {
    result = result.filter(s => s === sectionFilter.value)
  }
  return result
})

const totalCount = computed(() => {
  let count = 0
  for (const section of sections.value) {
    if (enData.value[section]) {
      count += Object.keys(enData.value[section]).length
    }
  }
  return count
})

const translatedCount = computed(() => {
  let count = 0
  for (const section of sections.value) {
    if (langData.value[section] && enData.value[section]) {
      for (const key of Object.keys(enData.value[section])) {
        const val = langData.value[section]?.[key]
        if (val && val !== '') {
          count++
        }
      }
    }
  }
  return count
})

const progressPercent = computed(() => {
  if (!totalCount.value) return 0
  return Math.round((translatedCount.value / totalCount.value) * 100)
})

// Methods
async function fetchLanguages() {
  try {
    const { data } = await client.get('/translations/languages')
    languages.value = data
  } catch {
    languages.value = [
      { code: 'en', name: 'English', flag: '' }
    ]
  }
}

async function loadLanguage() {
  loading.value = true
  try {
    const { data: en } = await client.get('/translations/en')
    enData.value = en

    if (selectedLang.value === 'en') {
      langData.value = JSON.parse(JSON.stringify(en))
    } else {
      const { data: lang } = await client.get(`/translations/${selectedLang.value}`)
      // Ensure all sections/keys from en exist in langData
      const merged = {}
      for (const section of Object.keys(en)) {
        merged[section] = {}
        for (const key of Object.keys(en[section])) {
          merged[section][key] = lang[section]?.[key] || ''
        }
      }
      langData.value = merged
    }
    // Auto-expand first section
    if (sections.value.length && !expandedSections.value.size) {
      expandedSections.value.add(sections.value[0])
    }
  } catch (err) {
    console.error('Failed to load translations:', err)
  } finally {
    loading.value = false
  }
}

function toggleSection(section) {
  if (expandedSections.value.has(section)) {
    expandedSections.value.delete(section)
  } else {
    expandedSections.value.add(section)
  }
}

function isMissing(section, key) {
  const val = langData.value[section]?.[key]
  return !val || val === ''
}

function getSectionProgress(section) {
  const enKeys = Object.keys(enData.value[section] || {})
  if (!enKeys.length) return '0/0'
  let done = 0
  for (const key of enKeys) {
    const val = langData.value[section]?.[key]
    if (val && val !== '') done++
  }
  return `${done}/${enKeys.length}`
}

function getFilteredKeys(section) {
  const allKeys = Object.keys(enData.value[section] || {})
  let keys = allKeys

  if (showMissing.value) {
    keys = keys.filter(key => isMissing(section, key))
  }

  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    keys = keys.filter(key => {
      const fullKey = `${section}.${key}`.toLowerCase()
      const enVal = (enData.value[section]?.[key] || '').toLowerCase()
      const langVal = (langData.value[section]?.[key] || '').toLowerCase()
      return fullKey.includes(q) || enVal.includes(q) || langVal.includes(q)
    })
  }

  return keys
}

async function saveSection(section) {
  saving.value = true
  try {
    // Build the full translation object to save
    const full = JSON.parse(JSON.stringify(langData.value))
    await client.put(`/translations/${selectedLang.value}`, { translations: full })
    alert('Section saved successfully!')
  } catch (err) {
    alert('Failed to save: ' + (err.response?.data?.detail || err.message))
  } finally {
    saving.value = false
  }
}

async function saveAll() {
  saving.value = true
  try {
    await client.put(`/translations/${selectedLang.value}`, { translations: langData.value })
    alert('All translations saved successfully!')
  } catch (err) {
    alert('Failed to save: ' + (err.response?.data?.detail || err.message))
  } finally {
    saving.value = false
  }
}

async function addLanguage() {
  try {
    await client.post('/translations/languages', {
      code: newLang.code.toLowerCase().trim(),
      name: newLang.name,
      flag: newLang.flag
    })
    showAddLangModal.value = false
    newLang.code = ''
    newLang.name = ''
    newLang.flag = ''
    await fetchLanguages()
    selectedLang.value = newLang.code || selectedLang.value
  } catch (err) {
    alert('Failed to add language: ' + (err.response?.data?.detail || err.message))
  }
}

async function confirmDeleteLanguage() {
  if (!confirm(`Are you sure you want to delete the "${selectedLang.value}" language? This cannot be undone.`)) return
  try {
    await client.delete(`/translations/languages/${selectedLang.value}`)
    selectedLang.value = 'en'
    await fetchLanguages()
    await loadLanguage()
  } catch (err) {
    alert('Failed to delete: ' + (err.response?.data?.detail || err.message))
  }
}

async function exportLanguage() {
  try {
    const { data } = await client.post(`/translations/export/${selectedLang.value}`, null, {
      responseType: 'blob'
    })
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${selectedLang.value}.json`
    a.click()
    URL.revokeObjectURL(url)
  } catch (err) {
    // Fallback: download from langData
    const blob = new Blob([JSON.stringify(langData.value, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${selectedLang.value}.json`
    a.click()
    URL.revokeObjectURL(url)
  }
}

function handleFileSelect(event) {
  importSelectedFile.value = event.target.files[0] || null
}

async function importFile() {
  if (!importSelectedFile.value) return
  const formData = new FormData()
  formData.append('file', importSelectedFile.value)
  try {
    await client.post('/translations/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    showImportModal.value = false
    importSelectedFile.value = null
    await fetchLanguages()
    await loadLanguage()
    alert('Translation file imported successfully!')
  } catch (err) {
    alert('Failed to import: ' + (err.response?.data?.detail || err.message))
  }
}

async function autoTranslate() {
  autoTranslating.value = true
  try {
    // Collect all missing keys
    const missing = []
    for (const section of sections.value) {
      for (const key of Object.keys(enData.value[section] || {})) {
        if (isMissing(section, key)) {
          missing.push({ section, key, english: enData.value[section][key] })
        }
      }
    }

    if (!missing.length) {
      alert('No missing translations to auto-translate!')
      autoTranslating.value = false
      return
    }

    // Find the language name for the selected language
    const langInfo = languages.value.find(l => l.code === selectedLang.value)
    const langName = langInfo?.name || selectedLang.value

    // Use the AI endpoint to translate in batches
    const batchSize = 30
    for (let i = 0; i < missing.length; i += batchSize) {
      const batch = missing.slice(i, i + batchSize)
      const keysObj = {}
      for (const item of batch) {
        keysObj[`${item.section}.${item.key}`] = item.english
      }

      const prompt = `Translate the following UI strings from English to ${langName}. Return ONLY a valid JSON object with the same keys and translated values. Do not add any explanation or markdown. Keep placeholder tokens like {username} unchanged.\n\n${JSON.stringify(keysObj, null, 2)}`

      try {
        const { data } = await client.post('/ai/chat', { message: prompt })
        // Parse AI response -- try to extract JSON from the response
        const responseText = data.response || data.message || data.content || ''
        const jsonMatch = responseText.match(/\{[\s\S]*\}/)
        if (jsonMatch) {
          const translated = JSON.parse(jsonMatch[0])
          for (const [fullKey, value] of Object.entries(translated)) {
            const [section, ...keyParts] = fullKey.split('.')
            const key = keyParts.join('.')
            if (langData.value[section] && value) {
              langData.value[section][key] = value
            }
          }
        }
      } catch {
        console.warn('AI translation batch failed, skipping...')
      }
    }

    alert('Auto-translation complete! Review the results and save.')
  } catch (err) {
    alert('Auto-translate failed: ' + (err.message || err))
  } finally {
    autoTranslating.value = false
  }
}

// Lifecycle
onMounted(async () => {
  await fetchLanguages()
  // Default to first non-en language if available
  if (languages.value.length > 1) {
    const nonEn = languages.value.find(l => l.code !== 'en')
    if (nonEn) selectedLang.value = nonEn.code
  }
  await loadLanguage()
})
</script>

<style scoped>
.btn-primary {
  padding: 0.5rem 1rem;
  border-radius: 0.5rem;
  font-size: 0.875rem;
  font-weight: 500;
  background: var(--primary);
  color: white;
  transition: opacity 0.2s;
}
.btn-primary:hover:not(:disabled) { opacity: 0.9; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-secondary {
  padding: 0.5rem 1rem;
  border-radius: 0.5rem;
  font-size: 0.875rem;
  font-weight: 500;
  background: var(--surface);
  color: var(--text-primary);
  border: 1px solid var(--border);
  transition: background 0.2s;
}
.btn-secondary:hover { background: var(--surface-hover, var(--surface)); }

.btn-danger {
  padding: 0.5rem 1rem;
  border-radius: 0.5rem;
  font-size: 0.875rem;
  font-weight: 500;
  background: var(--error, #ef4444);
  color: white;
  transition: opacity 0.2s;
}
.btn-danger:hover { opacity: 0.9; }
</style>
