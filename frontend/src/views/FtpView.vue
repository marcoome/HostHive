<template>
  <div>
    <!-- Header -->
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold text-text-primary">FTP Accounts</h1>
        <p class="text-sm text-text-muted mt-1">Manage FTP access to your hosting account</p>
      </div>
      <button class="btn-primary" @click="openAddModal">
        &#43; Add FTP Account
      </button>
    </div>

    <!-- Connection Info Card -->
    <div class="glass rounded-2xl p-6 mb-6">
      <h2 class="text-sm font-semibold text-text-primary uppercase tracking-wider mb-3">Connection Information</h2>
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div>
          <span class="text-xs text-text-muted block">FTP Host</span>
          <div class="flex items-center gap-2 mt-1">
            <span class="font-mono text-sm text-text-primary">{{ ftpHost }}</span>
            <button class="text-text-muted hover:text-primary text-xs transition-colors" @click="copyText(ftpHost)">
              &#9112;
            </button>
          </div>
        </div>
        <div>
          <span class="text-xs text-text-muted block">Port</span>
          <span class="font-mono text-sm text-text-primary mt-1 block">21 (FTP) / 990 (FTPS)</span>
        </div>
        <div>
          <span class="text-xs text-text-muted block">Protocol</span>
          <span class="text-sm text-text-primary mt-1 block">FTP with TLS (Explicit FTPS recommended)</span>
        </div>
      </div>
    </div>

    <!-- Accounts Table -->
    <DataTable
      :columns="columns"
      :rows="ftp.accounts"
      :loading="ftp.loading"
      empty-text="No FTP accounts found. Create your first account to get started."
    >
      <template #cell-username="{ row }">
        <span class="font-mono text-sm">{{ row.username }}</span>
      </template>
      <template #cell-home_directory="{ row }">
        <span class="font-mono text-sm text-text-muted">{{ row.home_directory }}</span>
      </template>
      <template #cell-status="{ row }">
        <StatusBadge :status="row.status" :label="row.status" />
      </template>
      <template #actions="{ row }">
        <div class="flex items-center justify-end gap-1 flex-wrap">
          <button class="btn-ghost text-xs px-2 py-1.5 min-h-[36px]" @click="showCredentials(row)">
            Credentials
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

    <!-- Add/Edit FTP Account Modal -->
    <Modal v-model="showModal" :title="editingAccount ? 'Edit FTP Account' : 'Add FTP Account'" size="md">
      <form @submit.prevent="saveAccount" class="space-y-4">
        <div>
          <label class="input-label">Username</label>
          <div class="flex items-center gap-0">
            <span class="inline-flex items-center px-3 py-2 text-sm text-text-muted bg-surface-elevated border border-r-0 border-border rounded-l">
              {{ systemUser }}_
            </span>
            <input
              v-model="form.username_suffix"
              type="text"
              class="flex-1 rounded-l-none"
              placeholder="myuser"
              :disabled="!!editingAccount"
              required
            />
          </div>
        </div>
        <div>
          <label class="input-label">Password</label>
          <div class="flex items-center gap-2">
            <input
              v-model="form.password"
              :type="showPassword ? 'text' : 'password'"
              class="flex-1"
              placeholder="Enter password"
              :required="!editingAccount"
            />
            <button type="button" class="btn-secondary text-sm px-3" @click="showPassword = !showPassword">
              {{ showPassword ? '&#9673;' : '&#9678;' }}
            </button>
            <button type="button" class="btn-secondary text-sm px-3" @click="generatePassword">
              Generate
            </button>
          </div>
          <p v-if="generatedPassword" class="text-xs text-success mt-1 flex items-center gap-2">
            Generated!
            <button type="button" class="underline" @click="copyText(generatedPassword)">Copy to clipboard</button>
          </p>
        </div>
        <div>
          <label class="input-label">Home Directory</label>
          <input
            v-model="form.home_directory"
            type="text"
            class="w-full font-mono"
            placeholder="/home/user/public_html"
          />
          <p class="text-xs text-text-muted mt-1">Leave empty for default home directory</p>
        </div>
      </form>
      <template #actions>
        <button class="btn-secondary" @click="showModal = false">Cancel</button>
        <button class="btn-primary" :disabled="saving" @click="saveAccount">
          <span v-if="saving" class="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full"></span>
          {{ saving ? 'Saving...' : (editingAccount ? 'Save Changes' : 'Create Account') }}
        </button>
      </template>
    </Modal>

    <!-- Credentials Modal -->
    <Modal v-model="showCredentialsModal" title="FTP Credentials" size="sm">
      <div class="space-y-4">
        <div>
          <label class="input-label">Host</label>
          <div class="flex items-center gap-2">
            <input :value="ftpHost" type="text" class="flex-1 font-mono text-sm" readonly />
            <button class="btn-secondary text-sm px-3" @click="copyText(ftpHost)">Copy</button>
          </div>
        </div>
        <div>
          <label class="input-label">Port</label>
          <input value="21" type="text" class="w-full font-mono text-sm" readonly />
        </div>
        <div>
          <label class="input-label">Username</label>
          <div class="flex items-center gap-2">
            <input :value="credentialsAccount?.username" type="text" class="flex-1 font-mono text-sm" readonly />
            <button class="btn-secondary text-sm px-3" @click="copyText(credentialsAccount?.username)">Copy</button>
          </div>
        </div>
        <div>
          <label class="input-label">Directory</label>
          <input :value="credentialsAccount?.home_directory" type="text" class="w-full font-mono text-sm" readonly />
        </div>
        <div class="p-3 rounded-lg bg-warning/10 border border-warning/20 text-sm text-warning">
          Password was shown only at creation time. Use the Edit button to reset the password.
        </div>
      </div>
      <template #actions>
        <button class="btn-primary" @click="showCredentialsModal = false">Close</button>
      </template>
    </Modal>

    <!-- Delete Confirm -->
    <ConfirmDialog
      v-model="showDeleteConfirm"
      title="Delete FTP Account"
      :message="`Are you sure you want to delete the FTP account '${accountToDelete?.username}'? This action cannot be undone.`"
      confirm-text="Delete Account"
      :destructive="true"
      @confirm="deleteAccount"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useFtpStore } from '@/stores/ftp'
import { useNotificationsStore } from '@/stores/notifications'
import DataTable from '@/components/DataTable.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const ftp = useFtpStore()
const notifications = useNotificationsStore()

const ftpHost = ref(window.location.hostname)
const systemUser = ref('admin')

const columns = [
  { key: 'username', label: 'Username' },
  { key: 'home_directory', label: 'Home Directory' },
  { key: 'status', label: 'Status' }
]

const showModal = ref(false)
const showCredentialsModal = ref(false)
const showDeleteConfirm = ref(false)
const showPassword = ref(false)
const saving = ref(false)
const editingAccount = ref(null)
const accountToDelete = ref(null)
const credentialsAccount = ref(null)
const generatedPassword = ref('')

const form = ref({
  username_suffix: '',
  password: '',
  home_directory: ''
})

onMounted(() => {
  ftp.fetchAccounts()
})

function openAddModal() {
  editingAccount.value = null
  form.value = { username_suffix: '', password: '', home_directory: '' }
  generatedPassword.value = ''
  showPassword.value = false
  showModal.value = true
}

function openEditModal(account) {
  editingAccount.value = account
  const suffix = account.username.includes('_')
    ? account.username.split('_').slice(1).join('_')
    : account.username
  form.value = {
    username_suffix: suffix,
    password: '',
    home_directory: account.home_directory
  }
  generatedPassword.value = ''
  showPassword.value = false
  showModal.value = true
}

function generatePassword() {
  const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*'
  let password = ''
  const array = new Uint32Array(20)
  crypto.getRandomValues(array)
  for (let i = 0; i < 20; i++) {
    password += chars[array[i] % chars.length]
  }
  form.value.password = password
  generatedPassword.value = password
  showPassword.value = true
}

function copyText(text) {
  if (!text) return
  navigator.clipboard.writeText(text)
  notifications.success('Copied to clipboard')
}

function showCredentials(account) {
  credentialsAccount.value = account
  showCredentialsModal.value = true
}

async function saveAccount() {
  if (!form.value.username_suffix) return
  saving.value = true
  try {
    const payload = {
      username: `${systemUser.value}_${form.value.username_suffix}`,
      home_directory: form.value.home_directory || undefined
    }
    if (form.value.password) payload.password = form.value.password

    if (editingAccount.value) {
      await ftp.updateAccount(editingAccount.value.id, payload)
      notifications.success('FTP account updated')
    } else {
      if (!form.value.password) {
        notifications.error('Password is required for new accounts')
        saving.value = false
        return
      }
      await ftp.createAccount(payload)
      notifications.success('FTP account created')
    }
    showModal.value = false
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to save FTP account')
  } finally {
    saving.value = false
  }
}

function confirmDelete(account) {
  accountToDelete.value = account
  showDeleteConfirm.value = true
}

async function deleteAccount() {
  if (!accountToDelete.value) return
  try {
    await ftp.removeAccount(accountToDelete.value.id)
    notifications.success('FTP account deleted')
    accountToDelete.value = null
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to delete account')
  }
}
</script>
