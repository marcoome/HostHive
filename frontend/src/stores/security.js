import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'

export const useSecurityStore = defineStore('security', () => {
  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  const scanResult = ref(null)        // Full scan result from GET /security/scan
  const scanning = ref(false)
  const loading = ref(false)

  const fail2banStatus = ref(null)    // From GET /security/scan -> checks[Fail2ban]
  const bannedIPs = ref([])           // From login-history top_attacker_ips

  const sshConfig = ref(null)         // From GET /security/ssh
  const sshLoading = ref(false)

  const firewallStatus = ref(null)    // From GET /security/scan -> checks[Firewall]
  const firewallRules = ref([])       // Parsed from firewall output

  const portsData = ref(null)         // From GET /security/ports
  const permissionsData = ref(null)   // From GET /security/permissions
  const updatesData = ref(null)       // From GET /security/updates
  const loginHistory = ref(null)      // From GET /security/login-history
  const malwareStatus = ref(null)     // From GET /security/malware

  // ---------------------------------------------------------------------------
  // Computed
  // ---------------------------------------------------------------------------
  const securityScore = computed(() => {
    if (!scanResult.value) return null
    const { score, max_score } = scanResult.value
    if (!max_score) return 0
    return Math.round((score / max_score) * 100)
  })

  const securityGrade = computed(() => scanResult.value?.grade || '-')

  const checks = computed(() => scanResult.value?.checks || [])

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  async function fetchSecurityScore() {
    loading.value = true
    try {
      const { data } = await client.get('/security/scan')
      scanResult.value = data

      // Extract fail2ban and firewall from checks
      const f2b = (data.checks || []).find(c => c.name === 'Fail2ban')
      if (f2b) fail2banStatus.value = f2b

      const fw = (data.checks || []).find(c => c.name === 'Firewall')
      if (fw) {
        firewallStatus.value = fw
        _parseFirewallRules(fw.details?.output || '')
      }

      return data
    } finally {
      loading.value = false
    }
  }

  async function runSecurityScan() {
    scanning.value = true
    const notify = useNotificationsStore()
    try {
      const data = await fetchSecurityScore()
      notify.success('Security scan completed')
      return data
    } catch (err) {
      notify.error('Security scan failed: ' + (err.response?.data?.detail || err.message))
      throw err
    } finally {
      scanning.value = false
    }
  }

  // ---- Fail2ban ----

  async function fetchFail2banStatus() {
    try {
      // Fail2ban info comes from the full scan; re-fetch if not present
      if (!scanResult.value) await fetchSecurityScore()
      return fail2banStatus.value
    } catch {
      return null
    }
  }

  async function fetchBannedIPs() {
    try {
      const { data } = await client.get('/security/login-history', { params: { lines: 500 } })
      loginHistory.value = data
      bannedIPs.value = data.summary?.top_attacker_ips || []
      return data
    } catch {
      return null
    }
  }

  async function unbanIP(ip) {
    const notify = useNotificationsStore()
    try {
      // Uses the SSH harden endpoint pattern - send a direct command
      // Note: this calls a custom endpoint if available, otherwise we note it
      await client.post('/security/unban', { ip })
      notify.success(`Unbanned IP: ${ip}`)
      bannedIPs.value = bannedIPs.value.filter(b => b.ip !== ip)
    } catch {
      notify.warning('Unban endpoint not available. Use fail2ban-client manually.')
    }
  }

  // ---- SSH ----

  async function fetchSSHConfig() {
    sshLoading.value = true
    try {
      const { data } = await client.get('/security/ssh')
      sshConfig.value = data
      return data
    } finally {
      sshLoading.value = false
    }
  }

  async function updateSSHConfig(payload) {
    const notify = useNotificationsStore()
    try {
      const { data } = await client.post('/security/ssh/harden', payload)
      notify.success('SSH configuration updated')
      await fetchSSHConfig()
      return data
    } catch (err) {
      notify.error('SSH update failed: ' + (err.response?.data?.detail || err.message))
      throw err
    }
  }

  // ---- Firewall ----

  async function fetchFirewallStatus() {
    try {
      if (!scanResult.value) await fetchSecurityScore()
      return firewallStatus.value
    } catch {
      return null
    }
  }

  async function fetchFirewallRules() {
    try {
      if (!scanResult.value) await fetchSecurityScore()
      return firewallRules.value
    } catch {
      return []
    }
  }

  // ---- Ports ----

  async function fetchOpenPorts() {
    try {
      const { data } = await client.get('/security/ports')
      portsData.value = data
      return data
    } catch {
      return null
    }
  }

  // ---- Permissions ----

  async function fetchPermissions() {
    try {
      const { data } = await client.get('/security/permissions')
      permissionsData.value = data
      return data
    } catch {
      return null
    }
  }

  // ---- Updates ----

  async function fetchUpdates() {
    try {
      const { data } = await client.get('/security/updates')
      updatesData.value = data
      return data
    } catch {
      return null
    }
  }

  async function applyUpdates(payload = {}) {
    const notify = useNotificationsStore()
    try {
      const { data } = await client.post('/security/updates/apply', payload)
      if (data.status === 'completed') {
        notify.success('Updates applied successfully')
      } else {
        notify.warning(data.detail || 'Update process ended with warnings')
      }
      await fetchUpdates()
      return data
    } catch (err) {
      notify.error('Update failed: ' + (err.response?.data?.detail || err.message))
      throw err
    }
  }

  // ---- Malware ----

  async function fetchMalwareStatus() {
    try {
      const { data } = await client.get('/security/malware')
      malwareStatus.value = data
      return data
    } catch {
      return null
    }
  }

  // ---- Helpers ----

  function _parseFirewallRules(output) {
    if (!output) { firewallRules.value = []; return }
    const lines = output.split('\n').filter(l => l.trim())
    const rules = []
    let inRules = false
    for (const line of lines) {
      if (line.includes('---')) { inRules = true; continue }
      if (inRules && line.trim()) {
        // UFW format: "To                         Action      From"
        const parts = line.trim().split(/\s{2,}/)
        if (parts.length >= 3) {
          rules.push({ to: parts[0], action: parts[1], from: parts[2] })
        }
      }
    }
    firewallRules.value = rules
  }

  return {
    // State
    scanResult,
    scanning,
    loading,
    fail2banStatus,
    bannedIPs,
    sshConfig,
    sshLoading,
    firewallStatus,
    firewallRules,
    portsData,
    permissionsData,
    updatesData,
    loginHistory,
    malwareStatus,

    // Computed
    securityScore,
    securityGrade,
    checks,

    // Actions
    fetchSecurityScore,
    runSecurityScan,
    fetchFail2banStatus,
    fetchBannedIPs,
    unbanIP,
    fetchSSHConfig,
    updateSSHConfig,
    fetchFirewallStatus,
    fetchFirewallRules,
    fetchOpenPorts,
    fetchPermissions,
    fetchUpdates,
    applyUpdates,
    fetchMalwareStatus
  }
})
