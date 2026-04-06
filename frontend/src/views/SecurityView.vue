<template>
  <div class="security-view" ref="viewRef">
    <!-- Page Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
      <div>
        <h1 class="text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">Security</h1>
        <p class="text-sm mt-1" :style="{ color: 'var(--text-muted)' }">Server security audit, hardening, and monitoring</p>
      </div>
      <button
        class="btn-primary text-sm self-start sm:self-auto min-h-[44px] inline-flex items-center gap-1.5"
        :disabled="store.scanning"
        @click="runScan"
      >
        <svg v-if="store.scanning" class="animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
        </svg>
        <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>
        </svg>
        {{ store.scanning ? 'Scanning...' : 'Run AI Scan' }}
      </button>
    </div>

    <!-- Security Score + Grade Row -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
      <!-- Large Circular Gauge -->
      <div class="card flex flex-col items-center justify-center py-8 lg:col-span-1">
        <template v-if="initialLoading">
          <div class="skeleton w-[140px] h-[140px] rounded-full mb-3"></div>
          <div class="skeleton w-20 h-4 mt-2"></div>
        </template>
        <template v-else>
          <div class="security-gauge" :style="{ '--gauge-color': scoreColor }">
            <svg width="140" height="140" viewBox="0 0 140 140">
              <circle cx="70" cy="70" r="60" fill="none" :stroke="trackColor" stroke-width="10" stroke-linecap="round" />
              <circle
                cx="70" cy="70" r="60" fill="none"
                :stroke="scoreColor"
                stroke-width="10"
                stroke-linecap="round"
                :stroke-dasharray="circumference"
                :stroke-dashoffset="dashOffset"
                style="transition: stroke-dashoffset 1s ease, stroke 0.3s ease"
                transform="rotate(-90 70 70)"
              />
            </svg>
            <div class="security-gauge-label">
              <span class="text-3xl font-bold" :style="{ color: scoreColor }">{{ displayScore }}</span>
              <span class="text-xs mt-0.5" :style="{ color: 'var(--text-muted)' }">/ 100</span>
            </div>
          </div>
          <div class="flex items-center gap-2 mt-3">
            <span
              class="badge text-sm font-semibold"
              :class="gradeClass"
            >Grade {{ store.securityGrade }}</span>
          </div>
          <p class="text-xs mt-2" :style="{ color: 'var(--text-muted)' }">
            {{ store.scanResult?.timestamp ? 'Scanned ' + timeAgo(store.scanResult.timestamp) : 'No scan data yet' }}
          </p>
        </template>
      </div>

      <!-- Check Results Summary -->
      <div class="card-static p-5 lg:col-span-2">
        <h3 class="text-sm font-medium mb-4" :style="{ color: 'var(--text-primary)' }">Security Checks</h3>
        <template v-if="initialLoading">
          <div v-for="i in 6" :key="i" class="skeleton w-full h-10 mb-2 rounded-lg"></div>
        </template>
        <template v-else-if="store.checks.length === 0">
          <div class="text-sm py-8 text-center" :style="{ color: 'var(--text-muted)' }">
            Run a security scan to see results
          </div>
        </template>
        <div v-else class="space-y-2">
          <div
            v-for="check in store.checks"
            :key="check.name"
            class="flex items-center gap-3 p-3 rounded-lg"
            :style="{ background: 'rgba(var(--border-rgb), 0.1)' }"
          >
            <div class="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center"
              :style="{ background: checkScoreColor(check) + '20', color: checkScoreColor(check) }">
              <svg v-if="check.score === check.max_score" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
              <svg v-else-if="check.score === 0" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
              <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 9v4"/><path d="M12 17h.01"/>
              </svg>
            </div>
            <div class="flex-1 min-w-0">
              <span class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">{{ check.name }}</span>
            </div>
            <div class="flex items-center gap-2 flex-shrink-0">
              <div class="w-24 h-2 rounded-full overflow-hidden" :style="{ background: 'rgba(var(--border-rgb), 0.3)' }">
                <div class="h-full rounded-full transition-all duration-500" :style="{ width: (check.score / check.max_score * 100) + '%', background: checkScoreColor(check) }"></div>
              </div>
              <span class="text-xs font-medium w-8 text-right" :style="{ color: checkScoreColor(check) }">{{ check.score }}/{{ check.max_score }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Collapsible Sections -->
    <div class="space-y-4">
      <!-- SSH Hardening -->
      <div class="card-static overflow-hidden">
        <button
          class="w-full flex items-center justify-between p-5 text-left min-h-[44px]"
          @click="toggleSection('ssh')"
        >
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-lg flex items-center justify-center" :style="{ background: 'rgba(var(--primary-rgb), 0.12)', color: 'var(--primary)' }">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
              </svg>
            </div>
            <div>
              <h3 class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">SSH Hardening</h3>
              <p class="text-xs" :style="{ color: 'var(--text-muted)' }">Port, root login, authentication settings</p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <span v-if="sshRiskBadge" class="badge" :class="sshRiskBadge.cls">{{ sshRiskBadge.label }}</span>
            <svg
              width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
              class="transition-transform duration-200"
              :class="{ 'rotate-180': openSections.ssh }"
              :style="{ color: 'var(--text-muted)' }"
            >
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </div>
        </button>
        <Transition name="collapse">
          <div v-if="openSections.ssh" class="px-5 pb-5">
            <div v-if="store.sshLoading" class="space-y-3">
              <div v-for="i in 4" :key="i" class="skeleton w-full h-12 rounded-lg"></div>
            </div>
            <div v-else-if="!store.sshConfig" class="text-sm py-4 text-center" :style="{ color: 'var(--text-muted)' }">
              Loading SSH configuration...
            </div>
            <div v-else>
              <!-- Current Settings -->
              <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
                <div class="p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
                  <p class="text-xs mb-1" :style="{ color: 'var(--text-muted)' }">Port</p>
                  <p class="text-sm font-semibold" :style="{ color: 'var(--text-primary)' }">{{ store.sshConfig.settings?.Port || '22' }}</p>
                </div>
                <div class="p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
                  <p class="text-xs mb-1" :style="{ color: 'var(--text-muted)' }">Root Login</p>
                  <p class="text-sm font-semibold" :style="{ color: rootLoginColor }">{{ store.sshConfig.settings?.PermitRootLogin || 'yes (default)' }}</p>
                </div>
                <div class="p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
                  <p class="text-xs mb-1" :style="{ color: 'var(--text-muted)' }">Password Auth</p>
                  <p class="text-sm font-semibold" :style="{ color: pwdAuthColor }">{{ store.sshConfig.settings?.PasswordAuthentication || 'yes (default)' }}</p>
                </div>
                <div class="p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
                  <p class="text-xs mb-1" :style="{ color: 'var(--text-muted)' }">Max Auth Tries</p>
                  <p class="text-sm font-semibold" :style="{ color: 'var(--text-primary)' }">{{ store.sshConfig.settings?.MaxAuthTries || '6 (default)' }}</p>
                </div>
              </div>

              <!-- Recommendations -->
              <div v-if="store.sshConfig.recommendations?.length" class="mb-4">
                <h4 class="text-xs font-semibold uppercase tracking-wider mb-2" :style="{ color: 'var(--text-muted)' }">Recommendations</h4>
                <div class="space-y-2">
                  <div
                    v-for="(rec, idx) in store.sshConfig.recommendations"
                    :key="idx"
                    class="flex items-start gap-3 p-3 rounded-lg"
                    :style="{ background: 'rgba(var(--border-rgb), 0.08)' }"
                  >
                    <span class="badge flex-shrink-0" :class="severityBadge(rec.severity)">{{ rec.severity }}</span>
                    <div class="flex-1 min-w-0">
                      <p class="text-sm" :style="{ color: 'var(--text-primary)' }">{{ rec.description }}</p>
                      <p class="text-xs mt-1" :style="{ color: 'var(--text-muted)' }">
                        <span class="font-medium">{{ rec.setting }}</span>: {{ rec.current }} &rarr; {{ rec.recommended }}
                      </p>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Harden Button -->
              <div class="flex flex-wrap gap-2">
                <button
                  class="btn-primary text-sm min-h-[44px]"
                  :disabled="hardeningSSH"
                  @click="hardenSSH"
                >
                  {{ hardeningSSH ? 'Applying...' : 'Apply Hardening' }}
                </button>
                <button class="btn-secondary text-sm min-h-[44px]" @click="store.fetchSSHConfig()">
                  Refresh
                </button>
              </div>
            </div>
          </div>
        </Transition>
      </div>

      <!-- Fail2ban -->
      <div class="card-static overflow-hidden">
        <button
          class="w-full flex items-center justify-between p-5 text-left min-h-[44px]"
          @click="toggleSection('fail2ban')"
        >
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-lg flex items-center justify-center" :style="{ background: 'rgba(239, 68, 68, 0.12)', color: '#ef4444' }">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
            </div>
            <div>
              <h3 class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">Fail2ban</h3>
              <p class="text-xs" :style="{ color: 'var(--text-muted)' }">Intrusion prevention and banned IPs</p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <span v-if="store.fail2banStatus" class="badge" :class="store.fail2banStatus.details?.active ? 'badge-success' : 'badge-error'">
              {{ store.fail2banStatus.details?.active ? 'Active' : 'Inactive' }}
            </span>
            <svg
              width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
              class="transition-transform duration-200"
              :class="{ 'rotate-180': openSections.fail2ban }"
              :style="{ color: 'var(--text-muted)' }"
            >
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </div>
        </button>
        <Transition name="collapse">
          <div v-if="openSections.fail2ban" class="px-5 pb-5">
            <!-- Fail2ban Stats -->
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
              <div class="p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
                <p class="text-xs mb-1" :style="{ color: 'var(--text-muted)' }">Status</p>
                <p class="text-sm font-semibold" :style="{ color: store.fail2banStatus?.details?.active ? 'var(--success)' : 'var(--error)' }">
                  {{ store.fail2banStatus?.details?.active ? 'Running' : 'Stopped' }}
                </p>
              </div>
              <div class="p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
                <p class="text-xs mb-1" :style="{ color: 'var(--text-muted)' }">Active Jails</p>
                <p class="text-sm font-semibold" :style="{ color: 'var(--text-primary)' }">{{ store.fail2banStatus?.details?.jail_count || 0 }}</p>
              </div>
              <div class="p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
                <p class="text-xs mb-1" :style="{ color: 'var(--text-muted)' }">Top Attacker IPs</p>
                <p class="text-sm font-semibold" :style="{ color: 'var(--text-primary)' }">{{ store.bannedIPs.length }}</p>
              </div>
            </div>

            <!-- Banned IPs Table -->
            <div v-if="store.bannedIPs.length > 0">
              <h4 class="text-xs font-semibold uppercase tracking-wider mb-2" :style="{ color: 'var(--text-muted)' }">Top Attacker IPs</h4>
              <div class="overflow-x-auto">
                <table class="w-full text-sm">
                  <thead>
                    <tr :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
                      <th class="text-left py-2 px-3 text-xs font-medium" :style="{ color: 'var(--text-muted)' }">IP Address</th>
                      <th class="text-left py-2 px-3 text-xs font-medium" :style="{ color: 'var(--text-muted)' }">Attempts</th>
                      <th class="text-right py-2 px-3 text-xs font-medium" :style="{ color: 'var(--text-muted)' }">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="entry in store.bannedIPs.slice(0, 15)"
                      :key="entry.ip"
                      :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.15)' }"
                    >
                      <td class="py-2 px-3 font-mono text-xs" :style="{ color: 'var(--text-primary)' }">{{ entry.ip }}</td>
                      <td class="py-2 px-3">
                        <span class="badge" :class="entry.attempts > 10 ? 'badge-error' : entry.attempts > 5 ? 'badge-warning' : 'badge-info'">
                          {{ entry.attempts }} attempts
                        </span>
                      </td>
                      <td class="py-2 px-3 text-right">
                        <button class="btn-ghost text-xs min-h-[32px] px-2" @click="store.unbanIP(entry.ip)">Unban</button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div v-else class="text-sm py-4 text-center" :style="{ color: 'var(--text-muted)' }">
              No banned IPs detected
            </div>

            <!-- Login History Summary -->
            <div v-if="store.loginHistory?.summary" class="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div class="p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
                <p class="text-xs mb-1" :style="{ color: 'var(--text-muted)' }">Successful Logins</p>
                <p class="text-lg font-semibold" :style="{ color: 'var(--success)' }">{{ store.loginHistory.summary.total_successful || 0 }}</p>
              </div>
              <div class="p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
                <p class="text-xs mb-1" :style="{ color: 'var(--text-muted)' }">Failed Attempts</p>
                <p class="text-lg font-semibold" :style="{ color: 'var(--error)' }">{{ store.loginHistory.summary.total_failed || 0 }}</p>
              </div>
            </div>
          </div>
        </Transition>
      </div>

      <!-- Firewall (UFW) -->
      <div class="card-static overflow-hidden">
        <button
          class="w-full flex items-center justify-between p-5 text-left min-h-[44px]"
          @click="toggleSection('firewall')"
        >
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-lg flex items-center justify-center" :style="{ background: 'rgba(245, 158, 11, 0.12)', color: '#f59e0b' }">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="1" y="1" width="22" height="22" rx="2"/><line x1="1" y1="8" x2="23" y2="8"/><line x1="1" y1="16" x2="23" y2="16"/><line x1="8" y1="1" x2="8" y2="23"/><line x1="16" y1="1" x2="16" y2="23"/>
              </svg>
            </div>
            <div>
              <h3 class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">Firewall (UFW)</h3>
              <p class="text-xs" :style="{ color: 'var(--text-muted)' }">Firewall status and rules management</p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <span v-if="store.firewallStatus" class="badge" :class="store.firewallStatus.details?.active ? 'badge-success' : 'badge-error'">
              {{ store.firewallStatus.details?.active ? 'Active' : 'Inactive' }}
            </span>
            <svg
              width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
              class="transition-transform duration-200"
              :class="{ 'rotate-180': openSections.firewall }"
              :style="{ color: 'var(--text-muted)' }"
            >
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </div>
        </button>
        <Transition name="collapse">
          <div v-if="openSections.firewall" class="px-5 pb-5">
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
              <div class="p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
                <p class="text-xs mb-1" :style="{ color: 'var(--text-muted)' }">UFW Status</p>
                <p class="text-sm font-semibold" :style="{ color: store.firewallStatus?.details?.active ? 'var(--success)' : 'var(--error)' }">
                  {{ store.firewallStatus?.details?.active ? 'Active' : store.firewallStatus?.details?.installed ? 'Installed (Inactive)' : 'Not Installed' }}
                </p>
              </div>
              <div class="p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
                <p class="text-xs mb-1" :style="{ color: 'var(--text-muted)' }">Rules Count</p>
                <p class="text-sm font-semibold" :style="{ color: 'var(--text-primary)' }">{{ store.firewallRules.length }}</p>
              </div>
            </div>

            <!-- Rules Table -->
            <div v-if="store.firewallRules.length > 0">
              <h4 class="text-xs font-semibold uppercase tracking-wider mb-2" :style="{ color: 'var(--text-muted)' }">Firewall Rules</h4>
              <div class="overflow-x-auto">
                <table class="w-full text-sm">
                  <thead>
                    <tr :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
                      <th class="text-left py-2 px-3 text-xs font-medium" :style="{ color: 'var(--text-muted)' }">To</th>
                      <th class="text-left py-2 px-3 text-xs font-medium" :style="{ color: 'var(--text-muted)' }">Action</th>
                      <th class="text-left py-2 px-3 text-xs font-medium" :style="{ color: 'var(--text-muted)' }">From</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="(rule, idx) in store.firewallRules"
                      :key="idx"
                      :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.15)' }"
                    >
                      <td class="py-2 px-3 font-mono text-xs" :style="{ color: 'var(--text-primary)' }">{{ rule.to }}</td>
                      <td class="py-2 px-3">
                        <span class="badge" :class="rule.action?.toLowerCase().includes('allow') ? 'badge-success' : 'badge-error'">
                          {{ rule.action }}
                        </span>
                      </td>
                      <td class="py-2 px-3 font-mono text-xs" :style="{ color: 'var(--text-primary)' }">{{ rule.from }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div v-else class="text-sm py-4 text-center" :style="{ color: 'var(--text-muted)' }">
              No firewall rules found
            </div>
          </div>
        </Transition>
      </div>

      <!-- Open Ports -->
      <div class="card-static overflow-hidden">
        <button
          class="w-full flex items-center justify-between p-5 text-left min-h-[44px]"
          @click="toggleSection('ports')"
        >
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-lg flex items-center justify-center" :style="{ background: 'rgba(99, 102, 241, 0.12)', color: '#6366f1' }">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
              </svg>
            </div>
            <div>
              <h3 class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">Open Ports</h3>
              <p class="text-xs" :style="{ color: 'var(--text-muted)' }">Listening ports and services</p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <span v-if="store.portsData" class="badge badge-info">{{ store.portsData.total || 0 }} ports</span>
            <svg
              width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
              class="transition-transform duration-200"
              :class="{ 'rotate-180': openSections.ports }"
              :style="{ color: 'var(--text-muted)' }"
            >
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </div>
        </button>
        <Transition name="collapse">
          <div v-if="openSections.ports" class="px-5 pb-5">
            <div v-if="!store.portsData" class="text-sm py-4 text-center" :style="{ color: 'var(--text-muted)' }">
              <button class="btn-secondary text-sm min-h-[44px]" @click="store.fetchOpenPorts()">Scan Ports</button>
            </div>
            <div v-else>
              <div class="overflow-x-auto">
                <table class="w-full text-sm">
                  <thead>
                    <tr :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
                      <th class="text-left py-2 px-3 text-xs font-medium" :style="{ color: 'var(--text-muted)' }">Port</th>
                      <th class="text-left py-2 px-3 text-xs font-medium" :style="{ color: 'var(--text-muted)' }">Protocol</th>
                      <th class="text-left py-2 px-3 text-xs font-medium" :style="{ color: 'var(--text-muted)' }">Address</th>
                      <th class="text-left py-2 px-3 text-xs font-medium" :style="{ color: 'var(--text-muted)' }">Process</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="(port, idx) in store.portsData.ports"
                      :key="idx"
                      :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.15)' }"
                    >
                      <td class="py-2 px-3 font-mono text-xs font-semibold" :style="{ color: 'var(--text-primary)' }">{{ port.port }}</td>
                      <td class="py-2 px-3">
                        <span class="badge badge-info">{{ port.protocol }}</span>
                      </td>
                      <td class="py-2 px-3 font-mono text-xs" :style="{ color: 'var(--text-muted)' }">{{ port.address }}</td>
                      <td class="py-2 px-3 text-xs" :style="{ color: 'var(--text-primary)' }">{{ port.process || '-' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="mt-3">
                <button class="btn-secondary text-sm min-h-[44px]" @click="store.fetchOpenPorts()">Rescan</button>
              </div>
            </div>
          </div>
        </Transition>
      </div>

      <!-- File Permissions -->
      <div class="card-static overflow-hidden">
        <button
          class="w-full flex items-center justify-between p-5 text-left min-h-[44px]"
          @click="toggleSection('permissions')"
        >
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-lg flex items-center justify-center" :style="{ background: 'rgba(34, 197, 94, 0.12)', color: '#22c55e' }">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>
              </svg>
            </div>
            <div>
              <h3 class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">File Permissions</h3>
              <p class="text-xs" :style="{ color: 'var(--text-muted)' }">System file permission audit</p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <span v-if="store.permissionsData" class="badge" :class="store.permissionsData.issue_count > 0 ? 'badge-warning' : 'badge-success'">
              {{ store.permissionsData.issue_count || 0 }} issues
            </span>
            <svg
              width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
              class="transition-transform duration-200"
              :class="{ 'rotate-180': openSections.permissions }"
              :style="{ color: 'var(--text-muted)' }"
            >
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </div>
        </button>
        <Transition name="collapse">
          <div v-if="openSections.permissions" class="px-5 pb-5">
            <div v-if="!store.permissionsData" class="text-sm py-4 text-center" :style="{ color: 'var(--text-muted)' }">
              <button class="btn-secondary text-sm min-h-[44px]" @click="store.fetchPermissions()">Check Permissions</button>
            </div>
            <div v-else-if="store.permissionsData.issues?.length === 0" class="text-sm py-4 text-center" :style="{ color: 'var(--success)' }">
              No permission issues found
            </div>
            <div v-else>
              <div class="space-y-2">
                <div
                  v-for="(issue, idx) in store.permissionsData.issues"
                  :key="idx"
                  class="flex items-start gap-3 p-3 rounded-lg"
                  :style="{ background: 'rgba(var(--border-rgb), 0.08)' }"
                >
                  <span class="badge flex-shrink-0" :class="severityBadge(issue.severity)">{{ issue.severity }}</span>
                  <div class="flex-1 min-w-0">
                    <p class="text-sm font-mono break-all" :style="{ color: 'var(--text-primary)' }">{{ issue.file }}</p>
                    <p class="text-xs mt-1" :style="{ color: 'var(--text-muted)' }">
                      {{ issue.description || issue.type }}
                      <template v-if="issue.current"> &mdash; Current: {{ issue.current }}, Expected: {{ issue.expected }}</template>
                    </p>
                  </div>
                </div>
              </div>
              <div class="mt-3">
                <button class="btn-secondary text-sm min-h-[44px]" @click="store.fetchPermissions()">Rescan</button>
              </div>
            </div>
          </div>
        </Transition>
      </div>

      <!-- System Updates -->
      <div class="card-static overflow-hidden">
        <button
          class="w-full flex items-center justify-between p-5 text-left min-h-[44px]"
          @click="toggleSection('updates')"
        >
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-lg flex items-center justify-center" :style="{ background: 'rgba(168, 85, 247, 0.12)', color: '#a855f7' }">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
              </svg>
            </div>
            <div>
              <h3 class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">System Updates</h3>
              <p class="text-xs" :style="{ color: 'var(--text-muted)' }">Available package updates and patches</p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <span v-if="store.updatesData" class="badge" :class="store.updatesData.count > 0 ? 'badge-warning' : 'badge-success'">
              {{ store.updatesData.count || 0 }} available
            </span>
            <svg
              width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
              class="transition-transform duration-200"
              :class="{ 'rotate-180': openSections.updates }"
              :style="{ color: 'var(--text-muted)' }"
            >
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </div>
        </button>
        <Transition name="collapse">
          <div v-if="openSections.updates" class="px-5 pb-5">
            <div v-if="!store.updatesData" class="text-sm py-4 text-center" :style="{ color: 'var(--text-muted)' }">
              <button class="btn-secondary text-sm min-h-[44px]" @click="store.fetchUpdates()">Check Updates</button>
            </div>
            <div v-else>
              <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
                <div class="p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
                  <p class="text-xs mb-1" :style="{ color: 'var(--text-muted)' }">Total Available</p>
                  <p class="text-lg font-semibold" :style="{ color: 'var(--text-primary)' }">{{ store.updatesData.count }}</p>
                </div>
                <div class="p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
                  <p class="text-xs mb-1" :style="{ color: 'var(--text-muted)' }">Security Updates</p>
                  <p class="text-lg font-semibold" :style="{ color: store.updatesData.security_count > 0 ? 'var(--error)' : 'var(--success)' }">{{ store.updatesData.security_count }}</p>
                </div>
                <div class="p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
                  <p class="text-xs mb-1" :style="{ color: 'var(--text-muted)' }">Last Checked</p>
                  <p class="text-sm font-semibold" :style="{ color: 'var(--text-primary)' }">{{ store.updatesData.last_update ? timeAgo(store.updatesData.last_update) : 'Unknown' }}</p>
                </div>
              </div>

              <!-- Packages list (show first 20) -->
              <div v-if="store.updatesData.packages?.length > 0" class="mb-4">
                <h4 class="text-xs font-semibold uppercase tracking-wider mb-2" :style="{ color: 'var(--text-muted)' }">Packages</h4>
                <div class="overflow-x-auto max-h-[300px] overflow-y-auto">
                  <table class="w-full text-sm">
                    <thead class="sticky top-0" :style="{ background: 'var(--surface)' }">
                      <tr :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.3)' }">
                        <th class="text-left py-2 px-3 text-xs font-medium" :style="{ color: 'var(--text-muted)' }">Package</th>
                        <th class="text-left py-2 px-3 text-xs font-medium" :style="{ color: 'var(--text-muted)' }">Current</th>
                        <th class="text-left py-2 px-3 text-xs font-medium" :style="{ color: 'var(--text-muted)' }">Available</th>
                        <th class="text-left py-2 px-3 text-xs font-medium" :style="{ color: 'var(--text-muted)' }">Type</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="pkg in store.updatesData.packages.slice(0, 30)"
                        :key="pkg.name"
                        :style="{ borderBottom: '1px solid rgba(var(--border-rgb), 0.15)' }"
                      >
                        <td class="py-2 px-3 font-mono text-xs" :style="{ color: 'var(--text-primary)' }">{{ pkg.name }}</td>
                        <td class="py-2 px-3 text-xs" :style="{ color: 'var(--text-muted)' }">{{ pkg.current_version }}</td>
                        <td class="py-2 px-3 text-xs" :style="{ color: 'var(--text-primary)' }">{{ pkg.new_version }}</td>
                        <td class="py-2 px-3">
                          <span class="badge" :class="pkg.is_security ? 'badge-error' : 'badge-info'">
                            {{ pkg.is_security ? 'Security' : 'Regular' }}
                          </span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              <div class="flex flex-wrap gap-2">
                <button
                  class="btn-primary text-sm min-h-[44px]"
                  :disabled="applyingUpdates"
                  @click="applySecurityUpdates"
                >
                  {{ applyingUpdates ? 'Applying...' : 'Apply Security Updates' }}
                </button>
                <button class="btn-secondary text-sm min-h-[44px]" @click="store.fetchUpdates()">Refresh</button>
              </div>
            </div>
          </div>
        </Transition>
      </div>

      <!-- Malware Scanner -->
      <div class="card-static overflow-hidden">
        <button
          class="w-full flex items-center justify-between p-5 text-left min-h-[44px]"
          @click="toggleSection('malware')"
        >
          <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-lg flex items-center justify-center" :style="{ background: 'rgba(236, 72, 153, 0.12)', color: '#ec4899' }">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/><path d="m9 12 2 2 4-4"/>
              </svg>
            </div>
            <div>
              <h3 class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">Malware Scanner</h3>
              <p class="text-xs" :style="{ color: 'var(--text-muted)' }">ClamAV status and scan results</p>
            </div>
          </div>
          <svg
            width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
            class="transition-transform duration-200"
            :class="{ 'rotate-180': openSections.malware }"
            :style="{ color: 'var(--text-muted)' }"
          >
            <polyline points="6 9 12 15 18 9"/>
          </svg>
        </button>
        <Transition name="collapse">
          <div v-if="openSections.malware" class="px-5 pb-5">
            <div v-if="!store.malwareStatus" class="text-sm py-4 text-center" :style="{ color: 'var(--text-muted)' }">
              <button class="btn-secondary text-sm min-h-[44px]" @click="store.fetchMalwareStatus()">Check Status</button>
            </div>
            <div v-else>
              <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
                <div class="p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
                  <p class="text-xs mb-1" :style="{ color: 'var(--text-muted)' }">ClamAV Installed</p>
                  <p class="text-sm font-semibold" :style="{ color: store.malwareStatus.installed ? 'var(--success)' : 'var(--error)' }">
                    {{ store.malwareStatus.installed ? 'Yes' : 'No' }}
                  </p>
                </div>
                <div class="p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
                  <p class="text-xs mb-1" :style="{ color: 'var(--text-muted)' }">Daemon Running</p>
                  <p class="text-sm font-semibold" :style="{ color: store.malwareStatus.running ? 'var(--success)' : 'var(--error)' }">
                    {{ store.malwareStatus.running ? 'Yes' : 'No' }}
                  </p>
                </div>
                <div class="p-3 rounded-lg" :style="{ background: 'rgba(var(--border-rgb), 0.1)' }">
                  <p class="text-xs mb-1" :style="{ color: 'var(--text-muted)' }">Last Scan Threats</p>
                  <p class="text-sm font-semibold" :style="{ color: (store.malwareStatus.last_scan?.infected_count || 0) > 0 ? 'var(--error)' : 'var(--success)' }">
                    {{ store.malwareStatus.last_scan?.infected_count ?? 'N/A' }}
                  </p>
                </div>
              </div>

              <div v-if="store.malwareStatus.last_scan?.infected_files?.length" class="mb-4">
                <h4 class="text-xs font-semibold uppercase tracking-wider mb-2" :style="{ color: 'var(--error)' }">Infected Files</h4>
                <div class="space-y-1">
                  <div
                    v-for="(file, idx) in store.malwareStatus.last_scan.infected_files.slice(0, 10)"
                    :key="idx"
                    class="p-2 rounded text-xs font-mono break-all"
                    :style="{ background: 'rgba(239, 68, 68, 0.08)', color: 'var(--text-primary)' }"
                  >
                    {{ file }}
                  </div>
                </div>
              </div>

              <button class="btn-secondary text-sm min-h-[44px]" @click="store.fetchMalwareStatus()">Refresh Status</button>
            </div>
          </div>
        </Transition>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, reactive, onMounted } from 'vue'
import { useSecurityStore } from '@/stores/security'

const store = useSecurityStore()
const viewRef = ref(null)
const initialLoading = ref(true)
const hardeningSSH = ref(false)
const applyingUpdates = ref(false)

const openSections = reactive({
  ssh: false,
  fail2ban: false,
  firewall: false,
  ports: false,
  permissions: false,
  updates: false,
  malware: false
})

// ---------------------------------------------------------------------------
// Gauge computations
// ---------------------------------------------------------------------------
const circumference = 2 * Math.PI * 60  // radius=60
const dashOffset = computed(() => {
  const score = store.securityScore ?? 0
  const progress = Math.min(Math.max(score, 0), 100) / 100
  return circumference * (1 - progress)
})
const trackColor = computed(() => 'rgba(var(--border-rgb), 0.4)')
const displayScore = computed(() => store.securityScore ?? 0)

const scoreColor = computed(() => {
  const s = store.securityScore ?? 0
  if (s >= 80) return 'var(--success)'
  if (s >= 50) return 'var(--warning)'
  return 'var(--error)'
})

const gradeClass = computed(() => {
  const g = store.securityGrade
  if (g === 'A') return 'badge-success'
  if (g === 'B') return 'badge-info'
  if (g === 'C') return 'badge-warning'
  return 'badge-error'
})

// ---------------------------------------------------------------------------
// SSH helpers
// ---------------------------------------------------------------------------
const sshRiskBadge = computed(() => {
  if (!store.sshConfig) return null
  const r = store.sshConfig.risk_level
  if (r === 'secure') return { cls: 'badge-success', label: 'Secure' }
  if (r === 'low') return { cls: 'badge-info', label: 'Low Risk' }
  if (r === 'medium') return { cls: 'badge-warning', label: 'Medium Risk' }
  if (r === 'high') return { cls: 'badge-error', label: 'High Risk' }
  return { cls: 'badge-info', label: 'Unknown' }
})

const rootLoginColor = computed(() => {
  const v = store.sshConfig?.settings?.PermitRootLogin
  if (v === 'no' || v === 'prohibit-password') return 'var(--success)'
  return 'var(--error)'
})

const pwdAuthColor = computed(() => {
  const v = store.sshConfig?.settings?.PasswordAuthentication
  if (v === 'no') return 'var(--success)'
  return 'var(--warning)'
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function checkScoreColor(check) {
  const pct = check.max_score > 0 ? check.score / check.max_score : 0
  if (pct >= 0.8) return 'var(--success)'
  if (pct >= 0.5) return 'var(--warning)'
  return 'var(--error)'
}

function severityBadge(severity) {
  if (severity === 'critical') return 'badge-error'
  if (severity === 'high') return 'badge-error'
  if (severity === 'medium') return 'badge-warning'
  if (severity === 'low') return 'badge-info'
  return 'badge-info'
}

function timeAgo(dateStr) {
  if (!dateStr) return ''
  const now = new Date()
  const past = new Date(dateStr)
  const diff = Math.floor((now - past) / 1000)
  if (diff < 60) return 'just now'
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago'
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago'
  return Math.floor(diff / 86400) + 'd ago'
}

function toggleSection(name) {
  openSections[name] = !openSections[name]
  // Lazy-load data when section opens
  if (openSections[name]) {
    if (name === 'ssh' && !store.sshConfig) store.fetchSSHConfig()
    if (name === 'fail2ban') store.fetchBannedIPs()
    if (name === 'ports' && !store.portsData) store.fetchOpenPorts()
    if (name === 'permissions' && !store.permissionsData) store.fetchPermissions()
    if (name === 'updates' && !store.updatesData) store.fetchUpdates()
    if (name === 'malware' && !store.malwareStatus) store.fetchMalwareStatus()
  }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------
async function runScan() {
  await store.runSecurityScan()
}

async function hardenSSH() {
  hardeningSSH.value = true
  try {
    await store.updateSSHConfig({
      disable_root_login: true,
      disable_password_auth: false,
      max_auth_tries: 3
    })
  } finally {
    hardeningSSH.value = false
  }
}

async function applySecurityUpdates() {
  applyingUpdates.value = true
  try {
    await store.applyUpdates({ security_only: true })
  } finally {
    applyingUpdates.value = false
  }
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
onMounted(async () => {
  try {
    await store.fetchSecurityScore()
  } catch {
    // Scan may fail if server is not reachable
  } finally {
    initialLoading.value = false
  }
})
</script>

<style scoped>
.security-view {
  position: relative;
  z-index: 1;
}

.security-gauge {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 140px;
  height: 140px;
}

.security-gauge-label {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

/* Collapse transition */
.collapse-enter-active,
.collapse-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.collapse-enter-from,
.collapse-leave-to {
  max-height: 0;
  opacity: 0;
  padding-top: 0;
  padding-bottom: 0;
}

.collapse-enter-to,
.collapse-leave-from {
  max-height: 2000px;
  opacity: 1;
}
</style>
