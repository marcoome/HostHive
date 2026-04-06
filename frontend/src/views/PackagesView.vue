<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <div class="flex items-center gap-4">
        <h1 class="text-2xl font-semibold text-[var(--text-primary)]">Packages</h1>
        <!-- Scope filter (resellers only) -->
        <div v-if="isResellerView" class="flex items-center gap-1 bg-[var(--surface)] border border-[var(--border)] rounded-lg p-0.5 text-xs">
          <button
            v-for="s in scopeOptions"
            :key="s.value"
            class="px-3 py-1 rounded-md transition-colors"
            :class="scope === s.value
              ? 'bg-primary text-white'
              : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'"
            @click="scope = s.value; fetchPackages()"
          >
            {{ s.label }}
          </button>
        </div>
      </div>
      <button class="btn-primary inline-flex items-center gap-2" @click="openCreateModal">
        <span class="text-lg leading-none">+</span>
        Create Package
      </button>
    </div>

    <!-- Loading Skeleton -->
    <div v-if="loading" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
      <div v-for="i in 6" :key="i" class="glass rounded-2xl p-6 space-y-4">
        <div class="skeleton h-6 w-32 rounded"></div>
        <div class="skeleton h-4 w-full rounded"></div>
        <div class="skeleton h-4 w-3/4 rounded"></div>
        <div class="skeleton h-4 w-1/2 rounded"></div>
      </div>
    </div>

    <!-- Package Cards Grid -->
    <div v-else-if="packages.length > 0" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
      <div
        v-for="pkg in packages"
        :key="pkg.id"
        class="glass rounded-2xl p-6 flex flex-col"
      >
        <!-- Header -->
        <div class="flex items-start justify-between mb-4">
          <div>
            <h3 class="text-lg font-semibold text-[var(--text-primary)]">{{ pkg.name }}</h3>
            <div class="flex items-center gap-2 mt-1">
              <span class="text-2xl font-bold text-primary">
                ${{ pkg.price_monthly || 0 }}
              </span>
              <span class="text-xs text-[var(--text-muted)]">/month</span>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <span
              v-if="isResellerView"
              class="px-2 py-0.5 rounded-full text-[10px] font-medium"
              :class="pkg.created_by ? 'bg-primary/15 text-primary' : 'bg-[var(--text-muted)]/10 text-[var(--text-muted)]'"
            >
              {{ pkg.created_by ? 'Custom' : 'Global' }}
            </span>
            <div class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-primary/10 text-primary text-xs font-medium">
              {{ pkg.user_count || 0 }} users
            </div>
          </div>
        </div>

        <!-- Resource Limits -->
        <div class="space-y-3 flex-1">
          <div class="flex items-center justify-between text-sm">
            <span class="text-[var(--text-muted)]">Disk Space</span>
            <span class="text-[var(--text-primary)] font-medium font-mono">{{ pkg.disk_quota_mb === 0 ? 'Unlimited' : formatSize(pkg.disk_quota_mb) }}</span>
          </div>
          <div class="flex items-center justify-between text-sm">
            <span class="text-[var(--text-muted)]">Bandwidth</span>
            <span class="text-[var(--text-primary)] font-medium font-mono">{{ pkg.bandwidth_gb === 0 ? 'Unlimited' : pkg.bandwidth_gb + ' GB' }}</span>
          </div>
          <div class="flex items-center justify-between text-sm">
            <span class="text-[var(--text-muted)]">Domains</span>
            <span class="text-[var(--text-primary)] font-medium font-mono">{{ pkg.max_domains === 0 ? 'Unlimited' : pkg.max_domains }}</span>
          </div>
          <div class="flex items-center justify-between text-sm">
            <span class="text-[var(--text-muted)]">Databases</span>
            <span class="text-[var(--text-primary)] font-medium font-mono">{{ pkg.max_databases === 0 ? 'Unlimited' : pkg.max_databases }}</span>
          </div>
          <div class="flex items-center justify-between text-sm">
            <span class="text-[var(--text-muted)]">Email Accounts</span>
            <span class="text-[var(--text-primary)] font-medium font-mono">{{ pkg.max_email_accounts === 0 ? 'Unlimited' : pkg.max_email_accounts }}</span>
          </div>
          <div class="flex items-center justify-between text-sm">
            <span class="text-[var(--text-muted)]">DNS Domains</span>
            <span class="text-[var(--text-primary)] font-medium font-mono">{{ pkg.max_dns_domains === 0 ? 'Unlimited' : pkg.max_dns_domains }}</span>
          </div>
          <div class="flex items-center justify-between text-sm">
            <span class="text-[var(--text-muted)]">Mail Domains</span>
            <span class="text-[var(--text-primary)] font-medium font-mono">{{ pkg.max_mail_domains === 0 ? 'Unlimited' : pkg.max_mail_domains }}</span>
          </div>
          <div class="flex items-center justify-between text-sm">
            <span class="text-[var(--text-muted)]">Backups</span>
            <span class="text-[var(--text-primary)] font-medium font-mono">{{ pkg.max_backups === 0 ? 'Unlimited' : pkg.max_backups }}</span>
          </div>
          <div class="flex items-center justify-between text-sm">
            <span class="text-[var(--text-muted)]">Shell Access</span>
            <span
              class="font-medium font-mono text-xs px-2 py-0.5 rounded-full"
              :class="pkg.shell_access ? 'bg-primary/10 text-primary' : 'bg-[var(--background)] text-[var(--text-muted)]'"
            >
              {{ pkg.shell_access ? pkg.shell_type || 'bash' : 'Disabled' }}
            </span>
          </div>

          <!-- Resource details -->
          <div class="pt-2 border-t border-[var(--border)] grid grid-cols-2 gap-2">
            <div class="flex items-center justify-between text-xs">
              <span class="text-[var(--text-muted)]">CPU</span>
              <span class="text-[var(--text-primary)] font-mono">{{ pkg.cpu_cores || 1 }} cores</span>
            </div>
            <div class="flex items-center justify-between text-xs">
              <span class="text-[var(--text-muted)]">RAM</span>
              <span class="text-[var(--text-primary)] font-mono">{{ formatSize(pkg.ram_mb || 1024) }}</span>
            </div>
            <div class="flex items-center justify-between text-xs">
              <span class="text-[var(--text-muted)]">Web</span>
              <span class="text-[var(--text-primary)] font-mono capitalize">{{ pkg.default_webserver || 'nginx' }}</span>
            </div>
            <div class="flex items-center justify-between text-xs">
              <span class="text-[var(--text-muted)]">DB</span>
              <span class="text-[var(--text-primary)] font-mono">{{ pkg.default_db_version || 'mariadb11' }}</span>
            </div>
          </div>

          <!-- Caching badges -->
          <div v-if="pkg.redis_enabled || pkg.memcached_enabled" class="flex items-center gap-2 flex-wrap">
            <span
              v-if="pkg.redis_enabled"
              class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 font-medium"
            >
              Redis {{ pkg.redis_memory_mb }}MB
            </span>
            <span
              v-if="pkg.memcached_enabled"
              class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 font-medium"
            >
              Memcached {{ pkg.memcached_memory_mb }}MB
            </span>
          </div>
        </div>

        <!-- Actions -->
        <div class="flex items-center gap-2 mt-5 pt-4 border-t border-[var(--border)]">
          <button
            class="btn-ghost text-xs px-3 py-1.5 flex-1"
            :disabled="isResellerView && !pkg.created_by"
            :title="isResellerView && !pkg.created_by ? 'Cannot edit global packages' : 'Edit package'"
            @click="openEditModal(pkg)"
          >
            Edit
          </button>
          <button
            class="btn-ghost text-xs px-3 py-1.5 flex-1 text-error hover:text-error"
            :disabled="pkg.user_count > 0 || (isResellerView && !pkg.created_by)"
            :title="isResellerView && !pkg.created_by ? 'Cannot delete global packages' : (pkg.user_count > 0 ? 'Cannot delete: users assigned' : 'Delete package')"
            @click="confirmDeletePackage(pkg)"
          >
            Delete
          </button>
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-else class="glass rounded-2xl p-12 text-center">
      <div class="text-4xl mb-3">&#128230;</div>
      <p class="text-[var(--text-muted)] text-sm">No packages yet. Create your first hosting package.</p>
    </div>

    <!-- Create/Edit Package Modal -->
    <Modal v-model="showModal" :title="editingPackage ? 'Edit Package' : 'Create Package'" size="lg">
      <form class="space-y-4" @submit.prevent="handleSave">
        <!-- Package Name -->
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Package Name</label>
          <input
            v-model="form.name"
            type="text"
            placeholder="Basic, Pro, Enterprise..."
            required
            class="input-field"
          />
        </div>

        <!-- ===== Pricing ===== -->
        <div class="section-wrap">
          <button type="button" class="section-header" @click="toggleSection('pricing')">
            <span class="text-sm font-semibold text-[var(--text-primary)]">Pricing</span>
            <svg :class="['section-chevron', openSections.pricing && 'rotate-180']" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" /></svg>
          </button>
          <div class="section-body" :style="{ gridTemplateRows: openSections.pricing ? '1fr' : '0fr' }">
            <div class="overflow-hidden">
              <div class="px-4 py-4">
                <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Monthly Price</label>
                <div class="relative">
                  <span class="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-[var(--text-muted)] font-medium">$</span>
                  <input v-model.number="form.price_monthly" type="number" step="0.01" min="0" class="input-field pl-7" />
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ===== Basic Limits ===== -->
        <div class="section-wrap">
          <button type="button" class="section-header" @click="toggleSection('basic')">
            <span class="text-sm font-semibold text-[var(--text-primary)]">Basic Limits</span>
            <svg :class="['section-chevron', openSections.basic && 'rotate-180']" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" /></svg>
          </button>
          <div class="section-body" :style="{ gridTemplateRows: openSections.basic ? '1fr' : '0fr' }">
            <div class="overflow-hidden">
              <div class="px-4 py-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
                <!-- Disk Space -->
                <div>
                  <div class="flex items-center justify-between mb-1">
                    <label class="text-sm font-medium text-[var(--text-primary)]">Disk Space (MB)</label>
                    <span class="text-xs text-[var(--text-muted)] font-mono">{{ form.disk_quota_mb === 0 ? 'Unlimited' : formatSize(form.disk_quota_mb) }}</span>
                  </div>
                  <input v-model.number="form.disk_quota_mb" type="range" min="0" max="102400" step="1024" class="w-full accent-primary" />
                  <div class="flex justify-between text-xs text-[var(--text-muted)] mt-0.5"><span>Unlimited</span><span>100 GB</span></div>
                </div>
                <!-- Bandwidth -->
                <div>
                  <div class="flex items-center justify-between mb-1">
                    <label class="text-sm font-medium text-[var(--text-primary)]">Bandwidth (GB)</label>
                    <span class="text-xs text-[var(--text-muted)] font-mono">{{ form.bandwidth_gb === 0 ? 'Unlimited' : form.bandwidth_gb + ' GB' }}</span>
                  </div>
                  <input v-model.number="form.bandwidth_gb" type="range" min="0" max="10240" step="10" class="w-full accent-primary" />
                  <div class="flex justify-between text-xs text-[var(--text-muted)] mt-0.5"><span>Unlimited</span><span>10 TB</span></div>
                </div>
                <!-- Domains -->
                <div>
                  <div class="flex items-center justify-between mb-1">
                    <label class="text-sm font-medium text-[var(--text-primary)]">Domains</label>
                    <span class="text-xs text-[var(--text-muted)] font-mono">{{ form.max_domains === 0 ? 'Unlimited' : form.max_domains }}</span>
                  </div>
                  <input v-model.number="form.max_domains" type="range" min="0" max="100" step="1" class="w-full accent-primary" />
                  <div class="flex justify-between text-xs text-[var(--text-muted)] mt-0.5"><span>Unlimited</span><span>100</span></div>
                </div>
                <!-- Databases -->
                <div>
                  <div class="flex items-center justify-between mb-1">
                    <label class="text-sm font-medium text-[var(--text-primary)]">Databases</label>
                    <span class="text-xs text-[var(--text-muted)] font-mono">{{ form.max_databases === 0 ? 'Unlimited' : form.max_databases }}</span>
                  </div>
                  <input v-model.number="form.max_databases" type="range" min="0" max="100" step="1" class="w-full accent-primary" />
                  <div class="flex justify-between text-xs text-[var(--text-muted)] mt-0.5"><span>Unlimited</span><span>100</span></div>
                </div>
                <!-- Email Accounts -->
                <div>
                  <div class="flex items-center justify-between mb-1">
                    <label class="text-sm font-medium text-[var(--text-primary)]">Email Accounts</label>
                    <span class="text-xs text-[var(--text-muted)] font-mono">{{ form.max_email_accounts === 0 ? 'Unlimited' : form.max_email_accounts }}</span>
                  </div>
                  <input v-model.number="form.max_email_accounts" type="range" min="0" max="500" step="5" class="w-full accent-primary" />
                  <div class="flex justify-between text-xs text-[var(--text-muted)] mt-0.5"><span>Unlimited</span><span>500</span></div>
                </div>
                <!-- FTP Accounts -->
                <div>
                  <div class="flex items-center justify-between mb-1">
                    <label class="text-sm font-medium text-[var(--text-primary)]">FTP Accounts</label>
                    <span class="text-xs text-[var(--text-muted)] font-mono">{{ form.max_ftp_accounts === 0 ? 'Unlimited' : form.max_ftp_accounts }}</span>
                  </div>
                  <input v-model.number="form.max_ftp_accounts" type="range" min="0" max="100" step="1" class="w-full accent-primary" />
                  <div class="flex justify-between text-xs text-[var(--text-muted)] mt-0.5"><span>Unlimited</span><span>100</span></div>
                </div>
                <!-- Cron Jobs (full width) -->
                <div class="sm:col-span-2">
                  <div class="flex items-center justify-between mb-1">
                    <label class="text-sm font-medium text-[var(--text-primary)]">Cron Jobs</label>
                    <span class="text-xs text-[var(--text-muted)] font-mono">{{ form.max_cron_jobs === 0 ? 'Unlimited' : form.max_cron_jobs }}</span>
                  </div>
                  <input v-model.number="form.max_cron_jobs" type="range" min="0" max="50" step="1" class="w-full accent-primary" />
                  <div class="flex justify-between text-xs text-[var(--text-muted)] mt-0.5"><span>Unlimited</span><span>50</span></div>
                </div>
                <!-- DNS Domains -->
                <div>
                  <div class="flex items-center justify-between mb-1">
                    <label class="text-sm font-medium text-[var(--text-primary)]">DNS Domains</label>
                    <span class="text-xs text-[var(--text-muted)] font-mono">{{ form.max_dns_domains === 0 ? 'Unlimited' : form.max_dns_domains }}</span>
                  </div>
                  <input v-model.number="form.max_dns_domains" type="range" min="0" max="100" step="1" class="w-full accent-primary" />
                  <div class="flex justify-between text-xs text-[var(--text-muted)] mt-0.5"><span>Unlimited</span><span>100</span></div>
                </div>
                <!-- Mail Domains -->
                <div>
                  <div class="flex items-center justify-between mb-1">
                    <label class="text-sm font-medium text-[var(--text-primary)]">Mail Domains</label>
                    <span class="text-xs text-[var(--text-muted)] font-mono">{{ form.max_mail_domains === 0 ? 'Unlimited' : form.max_mail_domains }}</span>
                  </div>
                  <input v-model.number="form.max_mail_domains" type="range" min="0" max="100" step="1" class="w-full accent-primary" />
                  <div class="flex justify-between text-xs text-[var(--text-muted)] mt-0.5"><span>Unlimited</span><span>100</span></div>
                </div>
                <!-- Backups -->
                <div class="sm:col-span-2">
                  <div class="flex items-center justify-between mb-1">
                    <label class="text-sm font-medium text-[var(--text-primary)]">Backups</label>
                    <span class="text-xs text-[var(--text-muted)] font-mono">{{ form.max_backups === 0 ? 'Unlimited' : form.max_backups }}</span>
                  </div>
                  <input v-model.number="form.max_backups" type="range" min="0" max="50" step="1" class="w-full accent-primary" />
                  <div class="flex justify-between text-xs text-[var(--text-muted)] mt-0.5"><span>Unlimited</span><span>50</span></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ===== Resource Limits ===== -->
        <div class="section-wrap">
          <button type="button" class="section-header" @click="toggleSection('resources')">
            <span class="text-sm font-semibold text-[var(--text-primary)]">Resource Limits</span>
            <svg :class="['section-chevron', openSections.resources && 'rotate-180']" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" /></svg>
          </button>
          <div class="section-body" :style="{ gridTemplateRows: openSections.resources ? '1fr' : '0fr' }">
            <div class="overflow-hidden">
              <div class="px-4 py-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">CPU Cores</label>
                  <input v-model.number="form.cpu_cores" type="number" min="0.25" max="32" step="0.25" class="input-field" />
                  <p class="text-xs text-[var(--text-muted)] mt-1">Docker --cpus value</p>
                </div>
                <div>
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">RAM (MB)</label>
                  <input v-model.number="form.ram_mb" type="number" min="128" max="65536" step="128" class="input-field" />
                  <p class="text-xs text-[var(--text-muted)] mt-1">Docker --memory limit</p>
                </div>
                <div>
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">I/O Bandwidth (MB/s)</label>
                  <input v-model.number="form.io_bandwidth_mbps" type="number" min="1" max="10000" step="10" class="input-field" />
                </div>
                <div>
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">IOPS Limit</label>
                  <input v-model.number="form.iops_limit" type="number" min="100" max="100000" step="100" class="input-field" />
                </div>
                <div>
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Inodes Limit</label>
                  <input v-model.number="form.inodes_limit" type="number" min="10000" max="5000000" step="10000" class="input-field" />
                </div>
                <div>
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Max Processes</label>
                  <input v-model.number="form.nproc_limit" type="number" min="10" max="1000" step="10" class="input-field" />
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ===== Server Configuration ===== -->
        <div class="section-wrap">
          <button type="button" class="section-header" @click="toggleSection('server')">
            <span class="text-sm font-semibold text-[var(--text-primary)]">Server Configuration</span>
            <svg :class="['section-chevron', openSections.server && 'rotate-180']" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" /></svg>
          </button>
          <div class="section-body" :style="{ gridTemplateRows: openSections.server ? '1fr' : '0fr' }">
            <div class="overflow-hidden">
              <div class="px-4 py-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Default Web Server</label>
                  <select v-model="form.default_webserver" class="input-field appearance-none cursor-pointer">
                    <option value="nginx">Nginx</option>
                    <option value="apache">Apache</option>
                    <option value="openlitespeed">OpenLiteSpeed</option>
                    <option value="caddy">Caddy</option>
                  </select>
                </div>
                <div>
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Default Database</label>
                  <select v-model="form.default_db_version" class="input-field appearance-none cursor-pointer">
                    <option value="mysql8">MySQL 8</option>
                    <option value="mysql9">MySQL 9</option>
                    <option value="mariadb11">MariaDB 11</option>
                    <option value="percona8">Percona 8</option>
                  </select>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ===== Caching ===== -->
        <div class="section-wrap">
          <button type="button" class="section-header" @click="toggleSection('caching')">
            <span class="text-sm font-semibold text-[var(--text-primary)]">Caching</span>
            <svg :class="['section-chevron', openSections.caching && 'rotate-180']" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" /></svg>
          </button>
          <div class="section-body" :style="{ gridTemplateRows: openSections.caching ? '1fr' : '0fr' }">
            <div class="overflow-hidden">
              <div class="px-4 py-4 space-y-5">
                <!-- Redis -->
                <div class="space-y-3">
                  <div class="flex items-center justify-between">
                    <div>
                      <span class="text-sm font-medium text-[var(--text-primary)]">Redis</span>
                      <p class="text-xs text-[var(--text-muted)]">In-memory data store</p>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      :aria-checked="form.redis_enabled"
                      class="toggle-switch"
                      :class="form.redis_enabled ? 'bg-primary' : 'bg-[var(--border)]'"
                      @click="form.redis_enabled = !form.redis_enabled"
                    >
                      <span class="toggle-knob" :class="form.redis_enabled ? 'translate-x-5' : 'translate-x-0'" />
                    </button>
                  </div>
                  <Transition name="slide-fade">
                    <div v-if="form.redis_enabled">
                      <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Redis Memory (MB)</label>
                      <input v-model.number="form.redis_memory_mb" type="number" min="16" max="2048" step="16" class="input-field" />
                    </div>
                  </Transition>
                </div>
                <!-- Memcached -->
                <div class="space-y-3">
                  <div class="flex items-center justify-between">
                    <div>
                      <span class="text-sm font-medium text-[var(--text-primary)]">Memcached</span>
                      <p class="text-xs text-[var(--text-muted)]">Distributed memory caching</p>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      :aria-checked="form.memcached_enabled"
                      class="toggle-switch"
                      :class="form.memcached_enabled ? 'bg-primary' : 'bg-[var(--border)]'"
                      @click="form.memcached_enabled = !form.memcached_enabled"
                    >
                      <span class="toggle-knob" :class="form.memcached_enabled ? 'translate-x-5' : 'translate-x-0'" />
                    </button>
                  </div>
                  <Transition name="slide-fade">
                    <div v-if="form.memcached_enabled">
                      <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Memcached Memory (MB)</label>
                      <input v-model.number="form.memcached_memory_mb" type="number" min="16" max="2048" step="16" class="input-field" />
                    </div>
                  </Transition>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ===== Shell Access ===== -->
        <div class="section-wrap">
          <button type="button" class="section-header" @click="toggleSection('shell')">
            <span class="text-sm font-semibold text-[var(--text-primary)]">Shell Access</span>
            <svg :class="['section-chevron', openSections.shell && 'rotate-180']" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" /></svg>
          </button>
          <div class="section-body" :style="{ gridTemplateRows: openSections.shell ? '1fr' : '0fr' }">
            <div class="overflow-hidden">
              <div class="px-4 py-4 space-y-3">
                <div class="flex items-center justify-between">
                  <div>
                    <span class="text-sm font-medium text-[var(--text-primary)]">Enable Shell Access</span>
                    <p class="text-xs text-[var(--text-muted)]">Allow SSH shell login for users on this package</p>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    :aria-checked="form.shell_access"
                    class="toggle-switch"
                    :class="form.shell_access ? 'bg-primary' : 'bg-[var(--border)]'"
                    @click="form.shell_access = !form.shell_access"
                  >
                    <span class="toggle-knob" :class="form.shell_access ? 'translate-x-5' : 'translate-x-0'" />
                  </button>
                </div>
                <Transition name="slide-fade">
                  <div v-if="form.shell_access">
                    <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Shell Type</label>
                    <select v-model="form.shell_type" class="input-field appearance-none cursor-pointer">
                      <option value="bash">Bash (/bin/bash)</option>
                      <option value="sh">SH (/bin/sh)</option>
                      <option value="rbash">Restricted Bash (/bin/rbash)</option>
                      <option value="nologin">No Login (/usr/sbin/nologin)</option>
                    </select>
                  </div>
                </Transition>
              </div>
            </div>
          </div>
        </div>
      </form>

      <template #actions>
        <button class="btn-secondary" @click="showModal = false">Cancel</button>
        <button class="btn-primary" :disabled="submitting || !form.name.trim()" @click="handleSave">
          <span v-if="submitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          {{ submitting ? 'Saving...' : (editingPackage ? 'Save Changes' : 'Create Package') }}
        </button>
      </template>
    </Modal>

    <!-- Delete Confirm -->
    <ConfirmDialog
      v-model="showDeleteDialog"
      title="Delete Package"
      :message="`Are you sure you want to delete the package '${packageToDelete?.name}'?`"
      confirm-text="Delete Package"
      :destructive="true"
      @confirm="handleDelete"
    />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import client from '@/api/client'
import { useNotificationsStore } from '@/stores/notifications'
import { useAuthStore } from '@/stores/auth'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const notifications = useNotificationsStore()
const authStore = useAuthStore()

// Detect if we're in reseller context (non-admin reseller)
const isResellerView = computed(() => authStore.isReseller && !authStore.isAdmin)

const scope = ref('all')
const scopeOptions = [
  { value: 'all', label: 'All' },
  { value: 'reseller', label: 'My Packages' },
  { value: 'global', label: 'Global' },
]

const packages = ref([])
const loading = ref(false)
const submitting = ref(false)
const showModal = ref(false)
const showDeleteDialog = ref(false)
const editingPackage = ref(null)
const packageToDelete = ref(null)

// Track which collapsible sections are open
const openSections = reactive({
  pricing: true,
  basic: true,
  resources: false,
  server: false,
  caching: false,
  shell: false,
})

function toggleSection(key) {
  openSections[key] = !openSections[key]
}

const defaultForm = {
  name: '',
  price_monthly: 0,
  disk_quota_mb: 10240,
  bandwidth_gb: 100,
  max_domains: 10,
  max_databases: 5,
  max_email_accounts: 20,
  max_ftp_accounts: 5,
  max_cron_jobs: 5,
  max_dns_domains: 10,
  max_mail_domains: 10,
  max_backups: 5,
  // Docker resource limits
  cpu_cores: 1,
  ram_mb: 1024,
  io_bandwidth_mbps: 100,
  iops_limit: 1000,
  inodes_limit: 500000,
  nproc_limit: 100,
  // Server config
  default_webserver: 'nginx',
  default_db_version: 'mariadb11',
  // Caching
  redis_enabled: false,
  redis_memory_mb: 64,
  memcached_enabled: false,
  memcached_memory_mb: 64,
  // Shell
  shell_access: false,
  shell_type: 'nologin',
}

const form = ref({ ...defaultForm })

function formatSize(mb) {
  if (!mb && mb !== 0) return '--'
  if (mb >= 1024) return (mb / 1024).toFixed(1) + ' GB'
  return mb + ' MB'
}

async function fetchPackages() {
  loading.value = true
  try {
    let data
    if (isResellerView.value) {
      // Resellers use the reseller endpoint which supports scope filtering
      const res = await client.get('/reseller/packages', { params: { scope: scope.value } })
      data = res.data
    } else {
      const res = await client.get('/packages')
      data = res.data
    }
    packages.value = data.items || data
  } catch {
    notifications.error('Failed to load packages.')
  } finally {
    loading.value = false
  }
}

function openCreateModal() {
  editingPackage.value = null
  form.value = { ...defaultForm }
  showModal.value = true
}

function openEditModal(pkg) {
  editingPackage.value = pkg
  form.value = {
    name: pkg.name,
    price_monthly: pkg.price_monthly || 0,
    disk_quota_mb: pkg.disk_quota_mb || 0,
    bandwidth_gb: pkg.bandwidth_gb || 0,
    max_domains: pkg.max_domains || 0,
    max_databases: pkg.max_databases || 0,
    max_email_accounts: pkg.max_email_accounts || 0,
    max_ftp_accounts: pkg.max_ftp_accounts || 0,
    max_cron_jobs: pkg.max_cron_jobs || 0,
    max_dns_domains: pkg.max_dns_domains || 0,
    max_mail_domains: pkg.max_mail_domains || 0,
    max_backups: pkg.max_backups || 0,
    cpu_cores: pkg.cpu_cores || 1,
    ram_mb: pkg.ram_mb || 1024,
    io_bandwidth_mbps: pkg.io_bandwidth_mbps || 100,
    iops_limit: pkg.iops_limit || 1000,
    inodes_limit: pkg.inodes_limit || 500000,
    nproc_limit: pkg.nproc_limit || 100,
    default_webserver: pkg.default_webserver || 'nginx',
    default_db_version: pkg.default_db_version || 'mariadb11',
    redis_enabled: pkg.redis_enabled || false,
    redis_memory_mb: pkg.redis_memory_mb || 64,
    memcached_enabled: pkg.memcached_enabled || false,
    memcached_memory_mb: pkg.memcached_memory_mb || 64,
    shell_access: pkg.shell_access || false,
    shell_type: pkg.shell_type || 'nologin',
  }
  showModal.value = true
}

async function handleSave() {
  if (!form.value.name.trim()) return
  submitting.value = true
  try {
    const baseUrl = isResellerView.value ? '/reseller/packages' : '/packages'
    if (editingPackage.value?.id) {
      const { data } = await client.put(`${baseUrl}/${editingPackage.value.id}`, form.value)
      const idx = packages.value.findIndex(p => p.id === editingPackage.value.id)
      if (idx >= 0) packages.value[idx] = data
      notifications.success('Package updated.')
    } else {
      const { data } = await client.post(baseUrl, form.value)
      packages.value.push(data)
      notifications.success('Package created.')
    }
    showModal.value = false
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to save package.')
  } finally {
    submitting.value = false
  }
}

function confirmDeletePackage(pkg) {
  packageToDelete.value = pkg
  showDeleteDialog.value = true
}

async function handleDelete() {
  if (!packageToDelete.value?.id) return
  try {
    const baseUrl = isResellerView.value ? '/reseller/packages' : '/packages'
    await client.delete(`${baseUrl}/${packageToDelete.value.id}`)
    packages.value = packages.value.filter(p => p.id !== packageToDelete.value.id)
    notifications.success('Package deleted.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete package.')
  } finally {
    packageToDelete.value = null
  }
}

watch(showModal, v => {
  if (!v) {
    editingPackage.value = null
    form.value = { ...defaultForm }
  }
})

onMounted(() => {
  fetchPackages()
})
</script>

<style scoped>
/* Shared input style */
.input-field {
  @apply w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary focus:ring-opacity-50;
}

/* Collapsible section wrapper */
.section-wrap {
  @apply rounded-xl border border-[var(--border)] overflow-hidden;
}

.section-header {
  @apply w-full flex items-center justify-between px-4 py-3 transition-colors text-left;
  background: var(--surface-alt, var(--surface));
}
.section-header:hover {
  background: var(--surface-hover, var(--surface));
}

.section-chevron {
  @apply w-4 h-4 text-[var(--text-muted)] transition-transform duration-200;
}

.section-body {
  display: grid;
  transition: grid-template-rows 0.25s ease;
}

/* Toggle switch */
.toggle-switch {
  @apply relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out;
  @apply focus:outline-none focus:ring-2 focus:ring-primary focus:ring-opacity-50 focus:ring-offset-2 focus:ring-offset-[var(--surface)];
}

.toggle-knob {
  @apply pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out;
}

/* Slide-fade transition for conditional fields */
.slide-fade-enter-active,
.slide-fade-leave-active {
  transition: all 0.2s ease;
}
.slide-fade-enter-from,
.slide-fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
