<template>
  <div>
    <!-- Header -->
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold text-text-primary">SSL Certificates</h1>
        <p class="text-sm text-text-muted mt-1">Manage SSL/TLS certificates for your domains</p>
      </div>
      <div class="flex items-center gap-3">
        <button class="btn-secondary" @click="showUpload = true">
          &#8682; Upload Certificate
        </button>
        <button class="btn-primary" @click="showIssue = true">
          &#43; Issue Certificate
        </button>
      </div>
    </div>

    <!-- Expiry Warning Banner -->
    <Transition name="slide-down">
      <div
        v-if="ssl.expiringCerts.length > 0"
        class="mb-6 p-4 rounded-2xl bg-error/10 border border-error/20 flex items-center gap-3"
      >
        <span class="text-error text-xl flex-shrink-0">&#9888;</span>
        <div class="flex-1">
          <p class="text-sm font-medium text-error">
            {{ ssl.expiringCerts.length }} certificate{{ ssl.expiringCerts.length > 1 ? 's' : '' }} expiring within 14 days!
          </p>
          <p class="text-xs text-error/80 mt-0.5">
            {{ ssl.expiringCerts.map(c => c.domain).join(', ') }}
          </p>
        </div>
        <button class="btn-ghost text-xs text-error" @click="renewAllExpiring">
          Renew All
        </button>
      </div>
    </Transition>

    <!-- Loading Skeleton -->
    <div v-if="ssl.loading && ssl.certificates.length === 0" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
      <div v-for="i in 3" :key="i" class="glass rounded-2xl p-6">
        <LoadingSkeleton class="h-6 w-48 mb-3" />
        <LoadingSkeleton class="h-4 w-32 mb-2" />
        <LoadingSkeleton class="h-4 w-24 mb-4" />
        <LoadingSkeleton class="h-20 w-20 rounded-full mx-auto mb-4" />
        <LoadingSkeleton class="h-8 w-full" />
      </div>
    </div>

    <!-- Empty State -->
    <div v-else-if="ssl.certificates.length === 0" class="glass rounded-2xl p-12 text-center">
      <div class="text-5xl mb-4 text-text-muted">&#128274;</div>
      <h3 class="text-lg font-medium text-text-primary mb-2">No SSL Certificates</h3>
      <p class="text-sm text-text-muted mb-6">Secure your domains by issuing an SSL certificate.</p>
      <button class="btn-primary" @click="showIssue = true">Issue Your First Certificate</button>
    </div>

    <!-- Certificate Cards Grid -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
      <div
        v-for="cert in ssl.certificates"
        :key="cert.id"
        class="glass rounded-2xl p-6 group relative overflow-hidden"
      >
        <!-- Status corner indicator -->
        <div
          class="absolute top-0 right-0 w-16 h-16 overflow-hidden"
        >
          <div
            class="absolute top-2 right-[-20px] w-[80px] text-center text-[9px] font-bold text-white uppercase tracking-wider rotate-45 py-0.5"
            :class="cert.status === 'active' ? 'bg-success' : cert.status === 'pending' ? 'bg-warning' : 'bg-error'"
          >
            {{ cert.status }}
          </div>
        </div>

        <!-- Lock icon + Domain -->
        <div class="flex items-start gap-3 mb-4">
          <div class="w-10 h-10 rounded-xl flex items-center justify-center text-lg flex-shrink-0"
               :class="cert.status === 'active' ? 'bg-success/10 text-success' : 'bg-error/10 text-error'">
            &#128274;
          </div>
          <div class="min-w-0 flex-1">
            <h3 class="text-base font-semibold text-text-primary truncate" :title="cert.domain">
              {{ cert.domain }}
            </h3>
            <p class="text-xs text-text-muted mt-0.5">{{ cert.issuer || 'Unknown Issuer' }}</p>
          </div>
        </div>

        <!-- Expiry Progress Ring -->
        <div class="flex items-center justify-center my-5">
          <div class="relative w-24 h-24">
            <svg class="w-24 h-24 transform -rotate-90" viewBox="0 0 100 100">
              <!-- Background ring -->
              <circle
                cx="50" cy="50" r="42"
                stroke="currentColor"
                class="text-border"
                stroke-width="6"
                fill="none"
              />
              <!-- Progress ring -->
              <circle
                cx="50" cy="50" r="42"
                :stroke="expiryColor(cert)"
                stroke-width="6"
                fill="none"
                stroke-linecap="round"
                :stroke-dasharray="264"
                :stroke-dashoffset="264 - (264 * expiryPercent(cert) / 100)"
                class="transition-all duration-700 ease-out"
              />
            </svg>
            <div class="absolute inset-0 flex flex-col items-center justify-center">
              <span class="text-lg font-bold" :style="{ color: expiryColor(cert) }">
                {{ daysRemaining(cert) }}
              </span>
              <span class="text-[10px] text-text-muted">days left</span>
            </div>
          </div>
        </div>

        <!-- Expiry date -->
        <p class="text-xs text-text-muted text-center mb-4">
          Expires {{ formatDate(cert.expires_at) }}
        </p>

        <!-- Auto-renew toggle -->
        <div class="flex items-center justify-between py-3 border-t border-border">
          <span class="text-sm text-text-muted">Auto-renew</span>
          <button
            class="relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none"
            :class="cert.auto_renew ? 'bg-success' : 'bg-border'"
            @click="toggleAutoRenew(cert)"
          >
            <span
              class="inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow-sm transition-transform"
              :class="cert.auto_renew ? 'translate-x-4' : 'translate-x-0.5'"
            ></span>
          </button>
        </div>

        <!-- Actions -->
        <div class="flex items-center gap-2 mt-3 pt-3 border-t border-border">
          <button
            class="btn-secondary text-xs flex-1 py-1.5"
            :disabled="cert.status !== 'active'"
            @click="confirmRenew(cert)"
          >
            &#8635; Renew
          </button>
          <button
            class="btn-ghost text-xs text-error hover:text-error py-1.5 px-3"
            @click="confirmRevoke(cert)"
          >
            Revoke
          </button>
        </div>
      </div>
    </div>

    <!-- Issue Certificate Modal -->
    <Modal v-model="showIssue" title="Issue SSL Certificate" size="md">
      <div class="space-y-4">
        <div>
          <label class="input-label">Domain</label>
          <select v-model="issueForm.domain" class="w-full" required>
            <option value="" disabled>Select a domain...</option>
            <option v-for="d in availableDomains" :key="d" :value="d">{{ d }}</option>
          </select>
        </div>
        <div>
          <label class="input-label">Certificate Type</label>
          <div class="flex gap-3">
            <label
              class="flex-1 p-4 rounded-xl border cursor-pointer transition-all"
              :class="issueForm.type === 'letsencrypt'
                ? 'border-primary bg-primary/5'
                : 'border-border hover:border-primary/30'"
            >
              <input v-model="issueForm.type" type="radio" value="letsencrypt" class="sr-only" />
              <span class="text-sm font-medium text-text-primary block">Let's Encrypt</span>
              <span class="text-xs text-text-muted mt-1 block">Free, auto-renewable, 90-day validity</span>
            </label>
            <label
              class="flex-1 p-4 rounded-xl border cursor-pointer transition-all"
              :class="issueForm.type === 'selfsigned'
                ? 'border-primary bg-primary/5'
                : 'border-border hover:border-primary/30'"
            >
              <input v-model="issueForm.type" type="radio" value="selfsigned" class="sr-only" />
              <span class="text-sm font-medium text-text-primary block">Self-Signed</span>
              <span class="text-xs text-text-muted mt-1 block">For testing only, not trusted by browsers</span>
            </label>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <input
            v-model="issueForm.include_www"
            type="checkbox"
            id="include-www"
            class="w-4 h-4 rounded border-border"
          />
          <label for="include-www" class="text-sm text-text-primary">Include www subdomain</label>
        </div>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showIssue = false">Cancel</button>
        <button class="btn-primary" :disabled="issuingCert || !issueForm.domain" @click="issueCert">
          <span v-if="issuingCert" class="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full"></span>
          {{ issuingCert ? 'Issuing...' : 'Issue Certificate' }}
        </button>
      </template>
    </Modal>

    <!-- Upload Certificate Modal -->
    <Modal v-model="showUpload" title="Upload Custom Certificate" size="lg">
      <div class="space-y-4">
        <div>
          <label class="input-label">Domain</label>
          <input v-model="uploadForm.domain" type="text" class="w-full" placeholder="example.com" required />
        </div>
        <div>
          <label class="input-label">Certificate (PEM)</label>
          <textarea
            v-model="uploadForm.certificate"
            class="w-full font-mono text-xs"
            rows="6"
            placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
            required
          ></textarea>
        </div>
        <div>
          <label class="input-label">Private Key (PEM)</label>
          <textarea
            v-model="uploadForm.private_key"
            class="w-full font-mono text-xs"
            rows="6"
            placeholder="-----BEGIN PRIVATE KEY-----&#10;...&#10;-----END PRIVATE KEY-----"
            required
          ></textarea>
        </div>
        <div>
          <label class="input-label">CA Bundle (optional)</label>
          <textarea
            v-model="uploadForm.ca_bundle"
            class="w-full font-mono text-xs"
            rows="4"
            placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
          ></textarea>
        </div>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showUpload = false">Cancel</button>
        <button class="btn-primary" :disabled="uploadingCert" @click="uploadCert">
          <span v-if="uploadingCert" class="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full"></span>
          {{ uploadingCert ? 'Uploading...' : 'Upload Certificate' }}
        </button>
      </template>
    </Modal>

    <!-- Renew Confirm -->
    <ConfirmDialog
      v-model="showRenewConfirm"
      title="Renew Certificate"
      :message="`Renew the SSL certificate for '${certToRenew?.domain}'?`"
      confirm-text="Renew"
      :destructive="false"
      @confirm="renewCert"
    />

    <!-- Revoke Confirm -->
    <ConfirmDialog
      v-model="showRevokeConfirm"
      title="Revoke Certificate"
      :message="`Are you sure you want to revoke the SSL certificate for '${certToRevoke?.domain}'? This cannot be undone and will disable HTTPS for this domain.`"
      confirm-text="Revoke Certificate"
      :destructive="true"
      @confirm="revokeCert"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useSslStore } from '@/stores/ssl'
import { useNotificationsStore } from '@/stores/notifications'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import client from '@/api/client'

const ssl = useSslStore()
const notifications = useNotificationsStore()

const showIssue = ref(false)
const showUpload = ref(false)
const showRenewConfirm = ref(false)
const showRevokeConfirm = ref(false)
const issuingCert = ref(false)
const uploadingCert = ref(false)
const certToRenew = ref(null)
const certToRevoke = ref(null)
const availableDomains = ref([])

const issueForm = ref({
  domain: '',
  type: 'letsencrypt',
  include_www: true
})

const uploadForm = ref({
  domain: '',
  certificate: '',
  private_key: '',
  ca_bundle: ''
})

onMounted(async () => {
  ssl.fetchCertificates()
  try {
    const { data } = await client.get('/domains')
    availableDomains.value = data.map(d => d.name || d.domain)
  } catch {
    availableDomains.value = []
  }
})

function daysRemaining(cert) {
  const days = ssl.daysUntilExpiry(cert.expires_at)
  return days < 0 ? 0 : days
}

function expiryPercent(cert) {
  const days = daysRemaining(cert)
  // Assume 90-day cert cycle
  return Math.min(100, Math.max(0, (days / 90) * 100))
}

function expiryColor(cert) {
  const days = daysRemaining(cert)
  if (days > 30) return 'var(--success)'
  if (days > 14) return 'var(--warning)'
  return 'var(--error)'
}

function formatDate(dateStr) {
  if (!dateStr) return 'N/A'
  return new Date(dateStr).toLocaleDateString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric'
  })
}

async function issueCert() {
  if (!issueForm.value.domain) return
  issuingCert.value = true
  try {
    await ssl.issueCertificate(issueForm.value)
    notifications.success(`Certificate issued for ${issueForm.value.domain}`)
    showIssue.value = false
    issueForm.value = { domain: '', type: 'letsencrypt', include_www: true }
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to issue certificate')
  } finally {
    issuingCert.value = false
  }
}

async function uploadCert() {
  if (!uploadForm.value.certificate || !uploadForm.value.private_key || !uploadForm.value.domain) return
  uploadingCert.value = true
  try {
    await ssl.uploadCertificate(uploadForm.value)
    notifications.success(`Certificate uploaded for ${uploadForm.value.domain}`)
    showUpload.value = false
    uploadForm.value = { domain: '', certificate: '', private_key: '', ca_bundle: '' }
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to upload certificate')
  } finally {
    uploadingCert.value = false
  }
}

function confirmRenew(cert) {
  certToRenew.value = cert
  showRenewConfirm.value = true
}

async function renewCert() {
  if (!certToRenew.value) return
  try {
    await ssl.renewCertificate(certToRenew.value.id)
    notifications.success(`Certificate renewed for ${certToRenew.value.domain}`)
    certToRenew.value = null
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to renew certificate')
  }
}

function confirmRevoke(cert) {
  certToRevoke.value = cert
  showRevokeConfirm.value = true
}

async function revokeCert() {
  if (!certToRevoke.value) return
  try {
    await ssl.revokeCertificate(certToRevoke.value.id)
    notifications.success(`Certificate revoked for ${certToRevoke.value.domain}`)
    certToRevoke.value = null
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to revoke certificate')
  }
}

async function toggleAutoRenew(cert) {
  try {
    await ssl.toggleAutoRenew(cert.id)
    notifications.success(`Auto-renew ${cert.auto_renew ? 'disabled' : 'enabled'} for ${cert.domain}`)
  } catch (err) {
    notifications.error(err.response?.data?.message || 'Failed to toggle auto-renew')
  }
}

async function renewAllExpiring() {
  for (const cert of ssl.expiringCerts) {
    try {
      await ssl.renewCertificate(cert.id)
    } catch {
      notifications.error(`Failed to renew ${cert.domain}`)
    }
  }
  notifications.success('All expiring certificates renewal initiated')
}
</script>

<style scoped>
.slide-down-enter-active {
  transition: all 0.3s ease-out;
}
.slide-down-leave-active {
  transition: all 0.2s ease-in;
}
.slide-down-enter-from {
  opacity: 0;
  transform: translateY(-10px);
}
.slide-down-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
</style>
