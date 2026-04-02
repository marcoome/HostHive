<template>
  <div class="space-y-4 h-[calc(100vh-8rem)]">
    <!-- Toolbar -->
    <div class="glass rounded-2xl p-3">
      <div class="flex items-center gap-2 flex-wrap">
        <!-- Breadcrumb -->
        <div class="flex items-center gap-1 flex-1 min-w-0 text-sm">
          <button
            class="text-[var(--text-muted)] hover:text-primary transition-colors px-1"
            @click="navigateTo('/')"
          >
            &#127968;
          </button>
          <template v-for="(segment, idx) in pathSegments" :key="idx">
            <span class="text-[var(--text-muted)]">/</span>
            <button
              class="hover:text-primary transition-colors truncate max-w-[150px] px-1"
              :class="idx === pathSegments.length - 1 ? 'text-[var(--text-primary)] font-medium' : 'text-[var(--text-muted)]'"
              @click="navigateTo(buildPath(idx))"
            >
              {{ segment }}
            </button>
          </template>
        </div>

        <!-- Actions -->
        <div class="flex items-center gap-1">
          <button class="btn-ghost text-xs px-2 py-1.5" title="Upload" @click="triggerUpload">
            &#8593; Upload
          </button>
          <button class="btn-ghost text-xs px-2 py-1.5" title="New Folder" @click="showNewFolderModal = true">
            &#128193; New Folder
          </button>
          <button class="btn-ghost text-xs px-2 py-1.5" title="New File" @click="showNewFileModal = true">
            &#128196; New File
          </button>
          <template v-if="selectedFiles.length > 0">
            <div class="w-px h-5 bg-[var(--border)] mx-1"></div>
            <button class="btn-ghost text-xs px-2 py-1.5" @click="handleRenameSelected">Rename</button>
            <button class="btn-ghost text-xs px-2 py-1.5" @click="handleChmodSelected">Chmod</button>
            <button class="btn-ghost text-xs px-2 py-1.5" @click="handleCompressSelected">Compress</button>
            <button class="btn-ghost text-xs px-2 py-1.5 text-error hover:text-error" @click="handleDeleteSelected">Delete</button>
          </template>
          <div class="w-px h-5 bg-[var(--border)] mx-1"></div>
          <button
            class="btn-ghost text-xs px-2 py-1.5"
            :class="viewMode === 'list' ? 'bg-[var(--surface)]' : ''"
            @click="viewMode = 'list'"
            title="List view"
          >
            &#9776;
          </button>
          <button
            class="btn-ghost text-xs px-2 py-1.5"
            :class="viewMode === 'grid' ? 'bg-[var(--surface)]' : ''"
            @click="viewMode = 'grid'"
            title="Grid view"
          >
            &#9638;
          </button>
        </div>
      </div>
    </div>

    <!-- Upload Drop Zone (shown when dragging) -->
    <Transition name="fade">
      <div
        v-if="isDragging"
        class="fixed inset-0 z-40 flex items-center justify-center bg-black/40 backdrop-blur-sm"
        @drop.prevent="handleDrop"
        @dragover.prevent
        @dragleave.prevent="isDragging = false"
      >
        <div class="glass rounded-2xl p-12 text-center border-2 border-dashed border-primary">
          <div class="text-4xl mb-4 text-primary">&#128229;</div>
          <p class="text-lg font-semibold text-[var(--text-primary)]">Drop files here to upload</p>
          <p class="text-sm text-[var(--text-muted)] mt-1">Files will be uploaded to {{ currentPath }}</p>
        </div>
      </div>
    </Transition>

    <!-- Upload Progress -->
    <div v-if="uploads.length > 0" class="glass rounded-2xl p-4 space-y-2">
      <div v-for="upload in uploads" :key="upload.name" class="flex items-center gap-3">
        <span class="text-xs text-[var(--text-muted)] truncate w-32">{{ upload.name }}</span>
        <div class="flex-1 h-2 bg-[var(--border)] rounded-full overflow-hidden">
          <div
            class="h-full bg-primary rounded-full transition-all duration-300"
            :style="{ width: upload.progress + '%' }"
          />
        </div>
        <span class="text-xs text-[var(--text-muted)] w-10 text-right">{{ upload.progress }}%</span>
      </div>
    </div>

    <!-- Main Content: Split Pane -->
    <div class="flex gap-4 flex-1 min-h-0" style="height: calc(100% - 80px)">
      <!-- Directory Tree (Left Pane) -->
      <div class="glass rounded-2xl p-3 overflow-y-auto hidden md:block" style="width: 250px; min-width: 250px">
        <div class="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3 px-2">
          Directory Tree
        </div>
        <DirectoryTreeNode
          :node="directoryTree"
          :current-path="currentPath"
          :depth="0"
          @navigate="navigateTo"
        />
      </div>

      <!-- File List (Right Pane) -->
      <div
        class="glass rounded-2xl flex-1 flex flex-col overflow-hidden"
        @dragenter.prevent="isDragging = true"
        @contextmenu.prevent="showContextMenuOnBackground"
      >
        <!-- Sort Header (List View) -->
        <div v-if="viewMode === 'list'" class="flex items-center px-4 py-2 border-b border-[var(--border)] text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider">
          <div class="w-8"></div>
          <div class="flex-1 cursor-pointer hover:text-primary transition-colors" @click="toggleSort('name')">
            Name {{ sortIcon('name') }}
          </div>
          <div class="w-24 text-right cursor-pointer hover:text-primary transition-colors" @click="toggleSort('size')">
            Size {{ sortIcon('size') }}
          </div>
          <div class="w-40 text-right cursor-pointer hover:text-primary transition-colors" @click="toggleSort('modified')">
            Modified {{ sortIcon('modified') }}
          </div>
          <div class="w-24 text-right">Permissions</div>
        </div>

        <!-- Loading Skeleton -->
        <div v-if="loadingFiles" class="p-4 space-y-2">
          <div v-for="i in 8" :key="i" class="flex items-center gap-3">
            <div class="skeleton h-8 w-8 rounded"></div>
            <div class="skeleton h-4 flex-1 rounded"></div>
            <div class="skeleton h-4 w-20 rounded"></div>
          </div>
        </div>

        <!-- Empty State -->
        <div v-else-if="sortedFiles.length === 0" class="flex-1 flex items-center justify-center">
          <div class="text-center">
            <div class="text-4xl mb-3 text-[var(--text-muted)]">&#128194;</div>
            <p class="text-sm text-[var(--text-muted)]">This folder is empty</p>
          </div>
        </div>

        <!-- List View -->
        <div v-else-if="viewMode === 'list'" class="flex-1 overflow-y-auto">
          <div
            v-for="file in sortedFiles"
            :key="file.name"
            class="flex items-center px-4 py-2 hover:bg-[var(--surface-elevated)] transition-colors cursor-pointer group"
            :class="{ 'bg-primary/5': isSelected(file) }"
            @click.exact="selectFile(file)"
            @click.ctrl="toggleFileSelection(file)"
            @click.meta="toggleFileSelection(file)"
            @dblclick="openFile(file)"
            @contextmenu.prevent.stop="showContextMenu($event, file)"
          >
            <div class="w-8 flex items-center justify-center">
              <input
                type="checkbox"
                :checked="isSelected(file)"
                class="opacity-0 group-hover:opacity-100 transition-opacity"
                :class="{ '!opacity-100': isSelected(file) }"
                @click.stop="toggleFileSelection(file)"
              />
            </div>
            <div class="flex-1 flex items-center gap-2 min-w-0">
              <span class="text-base flex-shrink-0">{{ fileIcon(file) }}</span>
              <span class="text-sm text-[var(--text-primary)] truncate">{{ file.name }}</span>
            </div>
            <div class="w-24 text-right text-xs text-[var(--text-muted)] font-mono">
              {{ file.is_dir ? '--' : formatSize(file.size) }}
            </div>
            <div class="w-40 text-right text-xs text-[var(--text-muted)]">
              {{ formatDate(file.modified) }}
            </div>
            <div class="w-24 text-right text-xs text-[var(--text-muted)] font-mono">
              {{ file.permissions || '--' }}
            </div>
          </div>
        </div>

        <!-- Grid View -->
        <div v-else class="flex-1 overflow-y-auto p-4">
          <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
            <div
              v-for="file in sortedFiles"
              :key="file.name"
              class="flex flex-col items-center gap-2 p-3 rounded-xl hover:bg-[var(--surface-elevated)] transition-colors cursor-pointer group"
              :class="{ 'bg-primary/5 ring-1 ring-primary/30': isSelected(file) }"
              @click.exact="selectFile(file)"
              @click.ctrl="toggleFileSelection(file)"
              @click.meta="toggleFileSelection(file)"
              @dblclick="openFile(file)"
              @contextmenu.prevent.stop="showContextMenu($event, file)"
            >
              <span class="text-3xl">{{ fileIcon(file) }}</span>
              <span class="text-xs text-[var(--text-primary)] text-center truncate w-full">{{ file.name }}</span>
              <span class="text-xs text-[var(--text-muted)]">{{ file.is_dir ? 'Folder' : formatSize(file.size) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Context Menu -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="contextMenu.visible"
          class="fixed z-50 min-w-[180px] py-1 glass-strong rounded-lg shadow-xl"
          :style="{ top: contextMenu.y + 'px', left: contextMenu.x + 'px' }"
          @contextmenu.prevent
        >
          <template v-if="contextMenu.file">
            <button class="context-menu-item" @click="contextAction('open')">
              <span>&#128194;</span> Open
            </button>
            <button class="context-menu-item" @click="contextAction('download')">
              <span>&#8595;</span> Download
            </button>
            <div class="border-t border-[var(--border)] my-1"></div>
            <button class="context-menu-item" @click="contextAction('rename')">
              <span>&#9998;</span> Rename
            </button>
            <button class="context-menu-item" @click="contextAction('copy')">
              <span>&#128203;</span> Copy
            </button>
            <button class="context-menu-item" @click="contextAction('move')">
              <span>&#10132;</span> Move
            </button>
            <button class="context-menu-item" @click="contextAction('chmod')">
              <span>&#128274;</span> Chmod
            </button>
            <div class="border-t border-[var(--border)] my-1"></div>
            <button v-if="!contextMenu.file.is_dir" class="context-menu-item" @click="contextAction('compress')">
              <span>&#128230;</span> Compress
            </button>
            <button v-if="isArchive(contextMenu.file)" class="context-menu-item" @click="contextAction('extract')">
              <span>&#128194;</span> Extract
            </button>
            <div class="border-t border-[var(--border)] my-1"></div>
            <button class="context-menu-item text-error hover:text-error" @click="contextAction('delete')">
              <span>&#128465;</span> Delete
            </button>
          </template>
          <template v-else>
            <button class="context-menu-item" @click="contextAction('upload')">
              <span>&#8593;</span> Upload Here
            </button>
            <button class="context-menu-item" @click="contextAction('newfolder')">
              <span>&#128193;</span> New Folder
            </button>
            <button class="context-menu-item" @click="contextAction('newfile')">
              <span>&#128196;</span> New File
            </button>
          </template>
        </div>
      </Transition>
    </Teleport>

    <!-- Hidden file input -->
    <input
      ref="fileInputRef"
      type="file"
      multiple
      class="hidden"
      @change="handleFileSelect"
    />

    <!-- New Folder Modal -->
    <Modal v-model="showNewFolderModal" title="New Folder" size="sm">
      <div>
        <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Folder Name</label>
        <input
          v-model="newItemName"
          type="text"
          placeholder="my-folder"
          class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          @keydown.enter="createFolder"
        />
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showNewFolderModal = false">Cancel</button>
        <button class="btn-primary" :disabled="!newItemName.trim()" @click="createFolder">Create</button>
      </template>
    </Modal>

    <!-- New File Modal -->
    <Modal v-model="showNewFileModal" title="New File" size="sm">
      <div>
        <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">File Name</label>
        <input
          v-model="newItemName"
          type="text"
          placeholder="index.html"
          class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          @keydown.enter="createFile"
        />
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showNewFileModal = false">Cancel</button>
        <button class="btn-primary" :disabled="!newItemName.trim()" @click="createFile">Create</button>
      </template>
    </Modal>

    <!-- Rename Modal -->
    <Modal v-model="showRenameModal" title="Rename" size="sm">
      <div>
        <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">New Name</label>
        <input
          v-model="renameValue"
          type="text"
          class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          @keydown.enter="handleRename"
        />
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showRenameModal = false">Cancel</button>
        <button class="btn-primary" :disabled="!renameValue.trim()" @click="handleRename">Rename</button>
      </template>
    </Modal>

    <!-- Chmod Modal -->
    <Modal v-model="showChmodModal" title="Change Permissions" size="sm">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Permissions (e.g. 755)</label>
          <input
            v-model="chmodValue"
            type="text"
            maxlength="4"
            placeholder="755"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] font-mono focus:outline-none focus:ring-2 focus:ring-primary/50"
            @keydown.enter="handleChmod"
          />
        </div>
        <div class="grid grid-cols-3 gap-3 text-xs">
          <div v-for="(who, wIdx) in ['Owner', 'Group', 'Others']" :key="wIdx" class="space-y-1.5">
            <div class="font-medium text-[var(--text-primary)]">{{ who }}</div>
            <label v-for="(perm, pIdx) in ['Read', 'Write', 'Execute']" :key="pIdx" class="flex items-center gap-1.5 text-[var(--text-muted)]">
              <input type="checkbox" :checked="hasPermBit(wIdx, pIdx)" @change="togglePermBit(wIdx, pIdx)" />
              {{ perm }}
            </label>
          </div>
        </div>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showChmodModal = false">Cancel</button>
        <button class="btn-primary" :disabled="!/^[0-7]{3,4}$/.test(chmodValue)" @click="handleChmod">Apply</button>
      </template>
    </Modal>

    <!-- Move/Copy Modal -->
    <Modal v-model="showMoveModal" :title="moveMode === 'move' ? 'Move To' : 'Copy To'" size="md">
      <div>
        <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Destination Path</label>
        <input
          v-model="moveDestination"
          type="text"
          :placeholder="currentPath"
          class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] font-mono focus:outline-none focus:ring-2 focus:ring-primary/50"
          @keydown.enter="handleMove"
        />
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showMoveModal = false">Cancel</button>
        <button class="btn-primary" :disabled="!moveDestination.trim()" @click="handleMove">
          {{ moveMode === 'move' ? 'Move' : 'Copy' }}
        </button>
      </template>
    </Modal>

    <!-- Code Editor Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showEditor"
          class="fixed inset-0 z-50 flex items-center justify-center p-4"
        >
          <div class="absolute inset-0 bg-black/70 backdrop-blur-sm" @click="closeEditor" />
          <div class="relative w-full max-w-5xl h-[85vh] flex flex-col rounded-xl overflow-hidden shadow-2xl border border-[var(--border)]" style="background: #1e1e2e;">
            <!-- Editor Header -->
            <div class="flex items-center justify-between px-4 py-2 border-b border-[rgba(255,255,255,0.08)]" style="background: #181825;">
              <div class="flex items-center gap-3">
                <span class="text-sm text-[rgba(255,255,255,0.5)]">{{ editorFile?.name }}</span>
                <span v-if="editorDirty" class="w-2 h-2 rounded-full bg-warning"></span>
                <span class="badge badge-info text-xs">{{ editorLanguage }}</span>
              </div>
              <div class="flex items-center gap-2">
                <button
                  class="px-3 py-1 text-xs rounded bg-primary text-white hover:bg-primary-600 transition-colors"
                  :disabled="savingFile"
                  @click="saveFile"
                >
                  {{ savingFile ? 'Saving...' : 'Save' }}
                </button>
                <button
                  class="px-2 py-1 text-xs rounded text-[rgba(255,255,255,0.5)] hover:text-white hover:bg-[rgba(255,255,255,0.08)] transition-colors"
                  @click="closeEditor"
                >
                  &#10005;
                </button>
              </div>
            </div>
            <!-- Editor Body -->
            <div class="flex-1 overflow-hidden">
              <div class="flex h-full">
                <!-- Line Numbers -->
                <div
                  ref="lineNumbersRef"
                  class="select-none text-right pr-3 pl-4 py-3 text-xs leading-6 overflow-hidden"
                  style="background: #181825; color: rgba(255,255,255,0.2); min-width: 50px;"
                >
                  <div v-for="n in editorLineCount" :key="n">{{ n }}</div>
                </div>
                <!-- Textarea -->
                <div class="flex-1 relative">
                  <pre
                    ref="highlightRef"
                    class="absolute inset-0 py-3 px-4 text-sm leading-6 font-mono overflow-auto whitespace-pre pointer-events-none"
                    style="color: #cdd6f4; tab-size: 2;"
                    aria-hidden="true"
                    v-html="highlightedCode"
                  ></pre>
                  <textarea
                    ref="editorTextareaRef"
                    v-model="editorContent"
                    class="absolute inset-0 w-full h-full py-3 px-4 text-sm leading-6 font-mono resize-none bg-transparent text-transparent caret-white outline-none"
                    style="tab-size: 2;"
                    spellcheck="false"
                    @scroll="syncScroll"
                    @input="editorDirty = true"
                    @keydown.tab.prevent="handleTab"
                    @keydown.ctrl.s.prevent="saveFile"
                    @keydown.meta.s.prevent="saveFile"
                  ></textarea>
                </div>
              </div>
            </div>
            <!-- Editor Footer -->
            <div class="flex items-center justify-between px-4 py-1 text-xs border-t border-[rgba(255,255,255,0.08)]" style="background: #181825; color: rgba(255,255,255,0.4);">
              <span>{{ editorLineCount }} lines</span>
              <span>{{ editorLanguage }}</span>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Delete Confirm -->
    <ConfirmDialog
      v-model="showDeleteDialog"
      title="Delete"
      :message="deleteMessage"
      confirm-text="Delete"
      :destructive="true"
      @confirm="executeDelete"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick, defineComponent, h } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'
import { useAuthStore } from '@/stores/auth'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const notifications = useNotificationsStore()
const auth = useAuthStore()

// State
const currentPath = ref('/home/' + (auth.user?.username || 'user'))
const files = ref([])
const loadingFiles = ref(false)
const viewMode = ref('list')
const sortKey = ref('name')
const sortDir = ref('asc')
const selectedFiles = ref([])
const isDragging = ref(false)
const uploads = ref([])

// Modals
const showNewFolderModal = ref(false)
const showNewFileModal = ref(false)
const showRenameModal = ref(false)
const showChmodModal = ref(false)
const showMoveModal = ref(false)
const showDeleteDialog = ref(false)
const showEditor = ref(false)

// Form values
const newItemName = ref('')
const renameValue = ref('')
const renameTarget = ref(null)
const chmodValue = ref('755')
const chmodTarget = ref(null)
const moveDestination = ref('')
const moveMode = ref('move')
const moveTarget = ref(null)
const deleteTargets = ref([])

// Editor state
const editorContent = ref('')
const editorFile = ref(null)
const editorDirty = ref(false)
const savingFile = ref(false)
const editorTextareaRef = ref(null)
const highlightRef = ref(null)
const lineNumbersRef = ref(null)
const fileInputRef = ref(null)

// Directory tree
const directoryTree = ref({ name: '/', path: '/', children: [], expanded: true })

// Context menu
const contextMenu = ref({ visible: false, x: 0, y: 0, file: null })

// Computed
const pathSegments = computed(() => {
  return currentPath.value.split('/').filter(Boolean)
})

const editorLineCount = computed(() => {
  return (editorContent.value || '').split('\n').length
})

const editorLanguage = computed(() => {
  if (!editorFile.value) return 'text'
  const ext = editorFile.value.name.split('.').pop().toLowerCase()
  const map = {
    php: 'php', js: 'javascript', mjs: 'javascript', ts: 'typescript',
    html: 'html', htm: 'html', css: 'css', scss: 'scss',
    json: 'json', yaml: 'yaml', yml: 'yaml', xml: 'xml',
    ini: 'ini', conf: 'ini', cfg: 'ini', env: 'ini',
    py: 'python', rb: 'ruby', sh: 'bash', bash: 'bash',
    sql: 'sql', md: 'markdown', txt: 'text', log: 'text'
  }
  return map[ext] || 'text'
})

const highlightedCode = computed(() => {
  return syntaxHighlight(editorContent.value, editorLanguage.value)
})

const deleteMessage = computed(() => {
  if (deleteTargets.value.length === 1) {
    return `Are you sure you want to delete '${deleteTargets.value[0].name}'? This cannot be undone.`
  }
  return `Are you sure you want to delete ${deleteTargets.value.length} items? This cannot be undone.`
})

const sortedFiles = computed(() => {
  const items = [...files.value]
  // Directories first always
  items.sort((a, b) => {
    if (a.is_dir && !b.is_dir) return -1
    if (!a.is_dir && b.is_dir) return 1
    let cmp = 0
    if (sortKey.value === 'name') {
      cmp = a.name.localeCompare(b.name)
    } else if (sortKey.value === 'size') {
      cmp = (a.size || 0) - (b.size || 0)
    } else if (sortKey.value === 'modified') {
      cmp = new Date(a.modified || 0) - new Date(b.modified || 0)
    }
    return sortDir.value === 'asc' ? cmp : -cmp
  })
  return items
})

// Methods
function buildPath(idx) {
  return '/' + pathSegments.value.slice(0, idx + 1).join('/')
}

function toggleSort(key) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortDir.value = 'asc'
  }
}

function sortIcon(key) {
  if (sortKey.value !== key) return ''
  return sortDir.value === 'asc' ? '&#9650;' : '&#9660;'
}

function fileIcon(file) {
  if (file.is_dir) return '\uD83D\uDCC1'
  const ext = file.name.split('.').pop().toLowerCase()
  const icons = {
    php: '\uD83D\uDC18', js: '\uD83D\uDFE8', ts: '\uD83D\uDD35', html: '\uD83C\uDF10', css: '\uD83C\uDFA8',
    json: '\uD83D\uDCCB', yaml: '\u2699\uFE0F', yml: '\u2699\uFE0F', xml: '\uD83D\uDCDC',
    py: '\uD83D\uDC0D', rb: '\uD83D\uDD34', sh: '\uD83D\uDDA5\uFE0F', sql: '\uD83D\uDDC3\uFE0F',
    md: '\uD83D\uDCDD', txt: '\uD83D\uDCC4', log: '\uD83D\uDCDC',
    jpg: '\uD83D\uDDBC\uFE0F', jpeg: '\uD83D\uDDBC\uFE0F', png: '\uD83D\uDDBC\uFE0F', gif: '\uD83D\uDDBC\uFE0F', svg: '\uD83D\uDDBC\uFE0F',
    zip: '\uD83D\uDCE6', tar: '\uD83D\uDCE6', gz: '\uD83D\uDCE6', rar: '\uD83D\uDCE6', '7z': '\uD83D\uDCE6',
    pdf: '\uD83D\uDCC4', doc: '\uD83D\uDCC4', docx: '\uD83D\uDCC4'
  }
  return icons[ext] || '\uD83D\uDCC4'
}

function isTextFile(file) {
  if (file.is_dir) return false
  const ext = file.name.split('.').pop().toLowerCase()
  const textExts = ['php', 'js', 'mjs', 'ts', 'tsx', 'jsx', 'html', 'htm', 'css', 'scss', 'less',
    'json', 'yaml', 'yml', 'xml', 'ini', 'conf', 'cfg', 'env', 'htaccess',
    'py', 'rb', 'sh', 'bash', 'zsh', 'sql', 'md', 'txt', 'log', 'csv',
    'vue', 'svelte', 'go', 'rs', 'c', 'cpp', 'h', 'java', 'toml']
  return textExts.includes(ext)
}

function isArchive(file) {
  if (!file || file.is_dir) return false
  const ext = file.name.split('.').pop().toLowerCase()
  return ['zip', 'tar', 'gz', 'tgz', 'bz2', 'rar', '7z'].includes(ext)
}

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return '--'
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

function formatDate(dateStr) {
  if (!dateStr) return '--'
  const d = new Date(dateStr)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function isSelected(file) {
  return selectedFiles.value.some(f => f.name === file.name)
}

function selectFile(file) {
  selectedFiles.value = [file]
}

function toggleFileSelection(file) {
  const idx = selectedFiles.value.findIndex(f => f.name === file.name)
  if (idx >= 0) {
    selectedFiles.value.splice(idx, 1)
  } else {
    selectedFiles.value.push(file)
  }
}

function openFile(file) {
  if (file.is_dir) {
    navigateTo(currentPath.value + '/' + file.name)
  } else if (isTextFile(file)) {
    openEditor(file)
  } else {
    handleDownloadFile(file)
  }
}

async function navigateTo(path) {
  const normalized = path.replace(/\/+/g, '/').replace(/\/$/, '') || '/'
  currentPath.value = normalized
  selectedFiles.value = []
  await fetchFiles()
}

async function fetchFiles() {
  loadingFiles.value = true
  try {
    const { data } = await client.get('/files/list', { params: { path: currentPath.value } })
    files.value = Array.isArray(data?.items) ? data.items : Array.isArray(data?.files) ? data.files : Array.isArray(data) ? data : []
  } catch (err) {
    notifications.error('Failed to load directory.')
    files.value = []
  } finally {
    loadingFiles.value = false
  }
}

async function fetchTree() {
  try {
    const { data } = await client.get('/files/tree', { params: { path: '/' } })
    directoryTree.value = {
      name: data?.name || '/',
      path: data?.path || '/',
      children: Array.isArray(data?.children) ? data.children : [],
      expanded: true,
    }
  } catch {
    directoryTree.value = { name: '/', path: '/', children: [], expanded: true }
  }
}

// Upload
function triggerUpload() {
  fileInputRef.value?.click()
}

function handleFileSelect(e) {
  const fileList = e.target.files
  if (fileList?.length) {
    uploadFiles(Array.from(fileList))
  }
  e.target.value = ''
}

function handleDrop(e) {
  isDragging.value = false
  const fileList = e.dataTransfer?.files
  if (fileList?.length) {
    uploadFiles(Array.from(fileList))
  }
}

async function uploadFiles(fileList) {
  for (const file of fileList) {
    const uploadEntry = { name: file.name, progress: 0 }
    uploads.value.push(uploadEntry)
    const formData = new FormData()
    formData.append('file', file)
    formData.append('path', currentPath.value)
    try {
      await client.post('/files/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (e) => {
          uploadEntry.progress = Math.round((e.loaded / (e.total || 1)) * 100)
        }
      })
      notifications.success(`Uploaded '${file.name}'.`)
    } catch (err) {
      notifications.error(`Failed to upload '${file.name}'.`)
    }
    uploads.value = uploads.value.filter(u => u !== uploadEntry)
  }
  fetchFiles()
}

// CRUD operations
async function createFolder() {
  if (!newItemName.value.trim()) return
  try {
    await client.post('/files/create-dir', { path: currentPath.value + '/' + newItemName.value.trim() })
    notifications.success(`Folder '${newItemName.value}' created.`)
    showNewFolderModal.value = false
    newItemName.value = ''
    fetchFiles()
    fetchTree()
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to create folder.')
  }
}

async function createFile() {
  if (!newItemName.value.trim()) return
  try {
    await client.put('/files/write', { path: currentPath.value + '/' + newItemName.value.trim(), content: '' })
    notifications.success(`File '${newItemName.value}' created.`)
    showNewFileModal.value = false
    newItemName.value = ''
    fetchFiles()
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to create file.')
  }
}

function handleRenameSelected() {
  if (selectedFiles.value.length !== 1) return
  renameTarget.value = selectedFiles.value[0]
  renameValue.value = renameTarget.value.name
  showRenameModal.value = true
}

async function handleRename() {
  if (!renameTarget.value || !renameValue.value.trim()) return
  try {
    await client.post('/files/rename', {
      path: currentPath.value + '/' + renameTarget.value.name,
      new_name: renameValue.value.trim()
    })
    notifications.success('Renamed successfully.')
    showRenameModal.value = false
    fetchFiles()
    fetchTree()
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to rename.')
  }
}

function handleChmodSelected() {
  if (selectedFiles.value.length < 1) return
  chmodTarget.value = selectedFiles.value
  chmodValue.value = selectedFiles.value[0]?.permissions?.replace?.(/^.*?(\d{3,4})$/, '$1') || '755'
  showChmodModal.value = true
}

function hasPermBit(who, perm) {
  const val = chmodValue.value || '755'
  const digits = val.length === 4 ? val.slice(1) : val
  const digit = parseInt(digits[who] || '0', 10)
  const bits = [4, 2, 1]
  return (digit & bits[perm]) !== 0
}

function togglePermBit(who, perm) {
  let val = chmodValue.value || '755'
  let digits = (val.length === 4 ? val.slice(1) : val).split('').map(Number)
  const bits = [4, 2, 1]
  digits[who] = digits[who] ^ bits[perm]
  chmodValue.value = digits.join('')
}

async function handleChmod() {
  if (!chmodTarget.value || !/^[0-7]{3,4}$/.test(chmodValue.value)) return
  try {
    for (const file of chmodTarget.value) {
      await client.post('/files/chmod', {
        path: currentPath.value + '/' + file.name,
        permissions: chmodValue.value
      })
    }
    notifications.success('Permissions updated.')
    showChmodModal.value = false
    fetchFiles()
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to change permissions.')
  }
}

function handleCompressSelected() {
  if (selectedFiles.value.length < 1) return
  compressFiles(selectedFiles.value)
}

async function compressFiles(targets) {
  try {
    const paths = targets.map(f => currentPath.value + '/' + f.name)
    await client.post('/files/compress', { paths, destination: currentPath.value })
    notifications.success('Compression started.')
    fetchFiles()
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to compress.')
  }
}

async function extractFile(file) {
  try {
    await client.post('/files/extract', {
      archive_path: currentPath.value + '/' + file.name,
      destination: currentPath.value
    })
    notifications.success('Extraction started.')
    fetchFiles()
    fetchTree()
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to extract.')
  }
}

function handleDeleteSelected() {
  if (selectedFiles.value.length < 1) return
  deleteTargets.value = [...selectedFiles.value]
  showDeleteDialog.value = true
}

async function executeDelete() {
  try {
    for (const file of deleteTargets.value) {
      await client.delete('/files/delete', { data: { path: file.path || (currentPath.value + '/' + file.name) } })
    }
    notifications.success(deleteTargets.value.length === 1 ? 'Deleted successfully.' : `${deleteTargets.value.length} items deleted.`)
    selectedFiles.value = []
    deleteTargets.value = []
    fetchFiles()
    fetchTree()
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete.')
  }
}

function handleDownloadFile(file) {
  const link = document.createElement('a')
  link.href = `/api/v1/files/download?path=${encodeURIComponent(currentPath.value + '/' + file.name)}`
  link.download = file.name
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

// Editor
async function openEditor(file) {
  editorFile.value = file
  editorDirty.value = false
  savingFile.value = false
  try {
    const { data } = await client.get('/files/read', { params: { path: currentPath.value + '/' + file.name } })
    editorContent.value = typeof data === 'string' ? data : data.content || ''
  } catch {
    editorContent.value = ''
    notifications.error('Failed to load file content.')
  }
  showEditor.value = true
  await nextTick()
  editorTextareaRef.value?.focus()
}

function closeEditor() {
  if (editorDirty.value && !confirm('You have unsaved changes. Close anyway?')) return
  showEditor.value = false
  editorFile.value = null
  editorContent.value = ''
}

async function saveFile() {
  if (!editorFile.value) return
  savingFile.value = true
  try {
    await client.put('/files/write', {
      path: currentPath.value + '/' + editorFile.value.name,
      content: editorContent.value
    })
    editorDirty.value = false
    notifications.success('File saved.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to save file.')
  } finally {
    savingFile.value = false
  }
}

function handleTab(e) {
  const textarea = e.target
  const start = textarea.selectionStart
  const end = textarea.selectionEnd
  editorContent.value = editorContent.value.substring(0, start) + '  ' + editorContent.value.substring(end)
  nextTick(() => {
    textarea.selectionStart = textarea.selectionEnd = start + 2
  })
}

function syncScroll() {
  if (highlightRef.value && editorTextareaRef.value) {
    highlightRef.value.scrollTop = editorTextareaRef.value.scrollTop
    highlightRef.value.scrollLeft = editorTextareaRef.value.scrollLeft
  }
  if (lineNumbersRef.value && editorTextareaRef.value) {
    lineNumbersRef.value.scrollTop = editorTextareaRef.value.scrollTop
  }
}

// Syntax highlighting (lightweight)
function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function syntaxHighlight(code, lang) {
  if (!code) return ''
  let escaped = escapeHtml(code)

  // Comments
  escaped = escaped.replace(/(\/\/.*$)/gm, '<span style="color:#6c7086">$1</span>')
  escaped = escaped.replace(/(#.*$)/gm, '<span style="color:#6c7086">$1</span>')
  escaped = escaped.replace(/(\/\*[\s\S]*?\*\/)/g, '<span style="color:#6c7086">$1</span>')

  // Strings
  escaped = escaped.replace(/(&quot;[^&]*?&quot;|&#39;[^&]*?&#39;|"[^"]*?"|'[^']*?'|`[^`]*?`)/g, '<span style="color:#a6e3a1">$1</span>')

  // Numbers
  escaped = escaped.replace(/\b(\d+\.?\d*)\b/g, '<span style="color:#fab387">$1</span>')

  // Keywords
  const keywords = ['function', 'const', 'let', 'var', 'if', 'else', 'return', 'import', 'export', 'from', 'class', 'new', 'this', 'async', 'await', 'for', 'while', 'switch', 'case', 'break', 'try', 'catch', 'finally', 'throw', 'typeof', 'instanceof', 'in', 'of', 'true', 'false', 'null', 'undefined', 'def', 'print', 'echo', 'require', 'include', 'use', 'namespace', 'public', 'private', 'protected', 'static', 'extends', 'implements', 'interface', 'abstract']
  const kwRegex = new RegExp('\\b(' + keywords.join('|') + ')\\b', 'g')
  escaped = escaped.replace(kwRegex, '<span style="color:#cba6f7">$1</span>')

  // HTML tags
  if (lang === 'html' || lang === 'xml' || lang === 'php') {
    escaped = escaped.replace(/(&lt;\/?[a-zA-Z][a-zA-Z0-9-]*)/g, '<span style="color:#89b4fa">$1</span>')
    escaped = escaped.replace(/(\/?&gt;)/g, '<span style="color:#89b4fa">$1</span>')
  }

  return escaped
}

// Context menu
function showContextMenu(e, file) {
  contextMenu.value = {
    visible: true,
    x: Math.min(e.clientX, window.innerWidth - 200),
    y: Math.min(e.clientY, window.innerHeight - 300),
    file
  }
  if (!isSelected(file)) {
    selectedFiles.value = [file]
  }
}

function showContextMenuOnBackground(e) {
  contextMenu.value = {
    visible: true,
    x: Math.min(e.clientX, window.innerWidth - 200),
    y: Math.min(e.clientY, window.innerHeight - 200),
    file: null
  }
}

function contextAction(action) {
  const file = contextMenu.value.file
  contextMenu.value.visible = false
  switch (action) {
    case 'open':
      if (file) openFile(file)
      break
    case 'download':
      if (file) handleDownloadFile(file)
      break
    case 'rename':
      if (file) {
        renameTarget.value = file
        renameValue.value = file.name
        showRenameModal.value = true
      }
      break
    case 'copy':
      if (file) {
        moveMode.value = 'copy'
        moveTarget.value = file
        moveDestination.value = currentPath.value
        showMoveModal.value = true
      }
      break
    case 'move':
      if (file) {
        moveMode.value = 'move'
        moveTarget.value = file
        moveDestination.value = currentPath.value
        showMoveModal.value = true
      }
      break
    case 'chmod':
      if (file) {
        chmodTarget.value = [file]
        chmodValue.value = file.permissions?.replace?.(/^.*?(\d{3,4})$/, '$1') || '755'
        showChmodModal.value = true
      }
      break
    case 'compress':
      if (file) compressFiles([file])
      break
    case 'extract':
      if (file) extractFile(file)
      break
    case 'delete':
      if (file) {
        deleteTargets.value = [file]
        showDeleteDialog.value = true
      }
      break
    case 'upload':
      triggerUpload()
      break
    case 'newfolder':
      showNewFolderModal.value = true
      break
    case 'newfile':
      showNewFileModal.value = true
      break
  }
}

async function handleMove() {
  if (!moveTarget.value || !moveDestination.value.trim()) return
  try {
    await client.post(`/files/${moveMode.value}`, {
      path: currentPath.value + '/' + moveTarget.value.name,
      destination: moveDestination.value.trim()
    })
    notifications.success(moveMode.value === 'move' ? 'Moved successfully.' : 'Copied successfully.')
    showMoveModal.value = false
    fetchFiles()
    fetchTree()
  } catch (err) {
    notifications.error(err.response?.data?.detail || `Failed to ${moveMode.value}.`)
  }
}

// Close context menu on click outside
function handleGlobalClick() {
  if (contextMenu.value.visible) {
    contextMenu.value.visible = false
  }
}

// Watch for modal close resets
watch(showNewFolderModal, v => { if (!v) newItemName.value = '' })
watch(showNewFileModal, v => { if (!v) newItemName.value = '' })

onMounted(() => {
  fetchFiles()
  fetchTree()
  document.addEventListener('click', handleGlobalClick)
  document.addEventListener('dragenter', () => { isDragging.value = true })
})

onUnmounted(() => {
  document.removeEventListener('click', handleGlobalClick)
})
</script>

<script>
// DirectoryTreeNode as inline component
const DirectoryTreeNode = defineComponent({
  name: 'DirectoryTreeNode',
  props: {
    node: { type: Object, required: true },
    currentPath: { type: String, default: '' },
    depth: { type: Number, default: 0 }
  },
  emits: ['navigate'],
  setup(props, { emit }) {
    const expanded = ref(props.depth < 2)

    function toggle() {
      expanded.value = !expanded.value
    }

    function navigate() {
      emit('navigate', props.node.path)
    }

    return () => {
      const isActive = props.currentPath === props.node.path
      const hasChildren = props.node.children?.length > 0

      const children = []

      // Toggle arrow + folder name
      children.push(
        h('div', {
          class: [
            'flex items-center gap-1.5 py-1 px-2 rounded cursor-pointer text-sm transition-colors',
            isActive ? 'bg-primary/10 text-primary' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-elevated)]'
          ].join(' '),
          style: { paddingLeft: (props.depth * 12 + 8) + 'px' },
          onClick: navigate
        }, [
          h('span', {
            class: 'text-xs cursor-pointer w-3 text-center flex-shrink-0',
            onClick: (e) => { e.stopPropagation(); toggle() }
          }, hasChildren ? (expanded.value ? '\u25BE' : '\u25B8') : '\u00A0'),
          h('span', { class: 'flex-shrink-0' }, '\uD83D\uDCC1'),
          h('span', { class: 'truncate' }, props.node.name)
        ])
      )

      // Children
      if (expanded.value && hasChildren) {
        for (const child of props.node.children) {
          children.push(
            h(DirectoryTreeNode, {
              node: child,
              currentPath: props.currentPath,
              depth: props.depth + 1,
              onNavigate: (path) => emit('navigate', path)
            })
          )
        }
      }

      return h('div', null, children)
    }
  }
})

export { DirectoryTreeNode }
</script>

<style scoped>
.context-menu-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.375rem 0.75rem;
  font-size: 0.8125rem;
  color: var(--text-primary);
  background: none;
  border: none;
  cursor: pointer;
  transition: background-color 0.15s ease;
  text-align: left;
}
.context-menu-item:hover {
  background-color: var(--surface-elevated);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

textarea {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}
</style>
