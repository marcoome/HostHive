<template>
  <div class="space-y-6">
    <!-- Back Button + Header -->
    <div class="flex items-center gap-4">
      <button
        class="btn-ghost p-2 rounded-lg"
        @click="$router.push({ name: 'domains' })"
        title="Back to domains"
      >
        &#8592;
      </button>
      <div class="flex-1">
        <h1 class="text-2xl font-semibold text-[var(--text-primary)]">
          {{ domain?.name || 'Domain Details' }}
        </h1>
        <p v-if="domain" class="text-sm text-[var(--text-muted)] mt-1">
          Created {{ formatDate(domain.created_at) }}
        </p>
      </div>
      <StatusBadge
        v-if="domain"
        :status="domain.ssl_enabled ? 'enabled' : 'disabled'"
        :label="domain.ssl_enabled ? 'SSL Active' : 'No SSL'"
      />
    </div>

    <!-- Loading skeleton -->
    <div v-if="store.loading && !domain" class="space-y-4">
      <div class="glass rounded-2xl p-6">
        <LoadingSkeleton class="h-6 w-48 mb-4" />
        <LoadingSkeleton class="h-4 w-full mb-2" />
        <LoadingSkeleton class="h-4 w-3/4 mb-2" />
        <LoadingSkeleton class="h-4 w-1/2" />
      </div>
    </div>

    <!-- Tabs -->
    <div v-else-if="domain">
      <div class="flex border-b border-[var(--border)] mb-6 overflow-x-auto">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="px-4 py-3 text-sm font-medium border-b-2 transition-colors whitespace-nowrap"
          :class="activeTab === tab.key
            ? 'border-primary text-primary'
            : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:border-[var(--border)]'"
          @click="activeTab = tab.key"
        >
          {{ tab.label }}
        </button>
      </div>

      <!-- Overview Tab -->
      <Transition name="fade" mode="out-in">
        <div v-if="activeTab === 'overview'" key="overview" class="space-y-6">
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- Domain Info -->
            <div class="glass rounded-2xl p-6">
              <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Domain Information</h3>
              <dl class="space-y-3">
                <div class="flex justify-between">
                  <dt class="text-sm text-[var(--text-muted)]">Domain Name</dt>
                  <dd class="text-sm text-[var(--text-primary)] font-medium">{{ domain.name }}</dd>
                </div>
                <div class="flex justify-between">
                  <dt class="text-sm text-[var(--text-muted)]">Document Root</dt>
                  <dd class="text-sm text-[var(--text-primary)] font-mono text-right break-all">{{ domain.document_root || `/home/${auth.user?.username}/web/${domain.name}/public_html` }}</dd>
                </div>
                <div class="flex justify-between">
                  <dt class="text-sm text-[var(--text-muted)]">PHP Version</dt>
                  <dd>
                    <span class="inline-flex items-center px-2.5 py-0.5 rounded-badge text-xs font-medium bg-primary/10 text-primary">
                      PHP {{ domain.php_version }}
                    </span>
                  </dd>
                </div>
                <div class="flex justify-between">
                  <dt class="text-sm text-[var(--text-muted)]">Web Server</dt>
                  <dd>
                    <span class="inline-flex items-center px-2.5 py-0.5 rounded-badge text-xs font-medium bg-primary/10 text-primary">
                      {{ webserverLabel(domain.webserver) }}
                    </span>
                  </dd>
                </div>
                <div class="flex justify-between">
                  <dt class="text-sm text-[var(--text-muted)]">Disk Usage</dt>
                  <dd class="text-sm text-[var(--text-primary)]">{{ formatBytes(domain.disk_usage) }}</dd>
                </div>
                <div class="flex justify-between">
                  <dt class="text-sm text-[var(--text-muted)]">Created</dt>
                  <dd class="text-sm text-[var(--text-primary)]">{{ formatDate(domain.created_at) }}</dd>
                </div>
              </dl>
            </div>

            <!-- Quick Actions -->
            <div class="glass rounded-2xl p-6">
              <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Quick Actions</h3>
              <div class="space-y-3">
                <button class="w-full btn-secondary text-left px-4 py-3 rounded-lg flex items-center justify-between" @click="showEditPhp = true">
                  <span class="text-sm">Change PHP Version</span>
                  <span class="text-xs text-[var(--text-muted)]">Currently PHP {{ domain.php_version }}</span>
                </button>
                <button class="w-full btn-secondary text-left px-4 py-3 rounded-lg flex items-center justify-between" @click="showEditWebserver = true">
                  <span class="text-sm">Change Web Server</span>
                  <span class="text-xs text-[var(--text-muted)]">{{ webserverLabel(domain.webserver) }}</span>
                </button>
                <button class="w-full btn-secondary text-left px-4 py-3 rounded-lg flex items-center justify-between" @click="activeTab = 'ssl'">
                  <span class="text-sm">Manage SSL</span>
                  <span class="text-xs text-[var(--text-muted)]">{{ domain.ssl_enabled ? 'Active' : 'Not configured' }}</span>
                </button>
                <button class="w-full btn-secondary text-left px-4 py-3 rounded-lg flex items-center justify-between" @click="activeTab = 'logs'">
                  <span class="text-sm">View Logs</span>
                  <span class="text-xs text-[var(--text-muted)]">Access &amp; error logs</span>
                </button>
                <button class="w-full btn-secondary text-left px-4 py-3 rounded-lg flex items-center justify-between text-error" @click="showDeleteDialog = true">
                  <span class="text-sm">Delete Domain</span>
                  <span class="text-xs">Permanent action</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Subdomains Tab -->
        <div v-else-if="activeTab === 'subdomains'" key="subdomains" class="space-y-6">
          <div class="glass rounded-2xl p-6">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-lg font-semibold text-[var(--text-primary)]">Subdomains</h3>
              <button class="btn-primary inline-flex items-center gap-2 text-sm" @click="showAddSubdomain = true">
                <span class="text-lg leading-none">+</span>
                Add Subdomain
              </button>
            </div>

            <!-- Loading state -->
            <div v-if="store.subdomainsLoading" class="space-y-3">
              <LoadingSkeleton v-for="i in 3" :key="i" class="h-16 w-full" />
            </div>

            <!-- Empty state -->
            <div v-else-if="store.subdomains.length === 0" class="text-center py-12">
              <p class="text-[var(--text-muted)] text-sm mb-2">No subdomains yet</p>
              <p class="text-[var(--text-muted)] text-xs">Create a subdomain like blog.{{ domain?.domain_name }} to get started.</p>
            </div>

            <!-- Subdomains list -->
            <div v-else class="divide-y divide-[var(--border)]">
              <div
                v-for="sub in store.subdomains"
                :key="sub.id"
                class="py-4 flex flex-col sm:flex-row sm:items-center gap-3"
              >
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2 mb-1">
                    <span class="text-sm font-medium text-[var(--text-primary)] truncate">{{ sub.domain_name }}</span>
                    <span
                      class="inline-flex items-center px-2 py-0.5 rounded-badge text-xs font-medium"
                      :class="sub.ssl_enabled ? 'bg-success/10 text-success' : 'bg-[var(--border)] text-[var(--text-muted)]'"
                    >
                      {{ sub.ssl_enabled ? 'SSL' : 'No SSL' }}
                    </span>
                  </div>
                  <div class="flex items-center gap-4 text-xs text-[var(--text-muted)]">
                    <span class="font-mono truncate max-w-[300px]" :title="sub.document_root">{{ sub.document_root }}</span>
                    <span class="inline-flex items-center px-2 py-0.5 rounded-badge bg-primary/10 text-primary font-medium">
                      PHP {{ sub.php_version }}
                    </span>
                  </div>
                </div>
                <div class="flex items-center gap-1 shrink-0">
                  <button
                    class="btn-ghost text-xs px-3 py-1.5 text-error hover:text-error"
                    @click="confirmDeleteSubdomain(sub)"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- SSL Tab -->
        <div v-else-if="activeTab === 'ssl'" key="ssl" class="space-y-6">
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- Current Certificate -->
            <div class="glass rounded-2xl p-6">
              <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">SSL Certificate</h3>
              <div v-if="domain.ssl_enabled" class="space-y-3">
                <dl class="space-y-3">
                  <div class="flex justify-between">
                    <dt class="text-sm text-[var(--text-muted)]">Issuer</dt>
                    <dd class="text-sm text-[var(--text-primary)]">{{ domain.ssl_issuer || "Let's Encrypt" }}</dd>
                  </div>
                  <div class="flex justify-between">
                    <dt class="text-sm text-[var(--text-muted)]">Expires</dt>
                    <dd class="text-sm text-[var(--text-primary)]">{{ formatDate(domain.ssl_expiry) }}</dd>
                  </div>
                  <div class="flex justify-between">
                    <dt class="text-sm text-[var(--text-muted)]">Days Remaining</dt>
                    <dd class="text-sm font-medium" :class="sslDaysRemaining > 14 ? 'text-success' : sslDaysRemaining > 7 ? 'text-warning' : 'text-error'">
                      {{ sslDaysRemaining }} days
                    </dd>
                  </div>
                </dl>
                <div class="flex items-center justify-between pt-3 border-t border-[var(--border)]">
                  <span class="text-sm text-[var(--text-muted)]">Auto-renew</span>
                  <button
                    class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
                    :class="autoRenew ? 'bg-primary' : 'bg-[var(--border)]'"
                    @click="toggleAutoRenew"
                  >
                    <span
                      class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
                      :class="autoRenew ? 'translate-x-6' : 'translate-x-1'"
                    />
                  </button>
                </div>
              </div>
              <div v-else class="text-center py-6">
                <p class="text-[var(--text-muted)] text-sm mb-2">No SSL certificate installed</p>
                <p class="text-[var(--text-muted)] text-xs">Issue a free certificate or upload your own.</p>
              </div>
            </div>

            <!-- SSL Actions -->
            <div class="glass rounded-2xl p-6">
              <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Actions</h3>
              <div class="space-y-3">
                <button class="w-full btn-primary py-3" :disabled="issuingSSL" @click="issueSSL">
                  <span v-if="issuingSSL" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
                  {{ issuingSSL ? 'Issuing...' : "Issue Let's Encrypt SSL" }}
                </button>
                <button class="w-full btn-secondary py-3" @click="showUploadCert = true">
                  Upload Custom Certificate
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Caching Tab -->
        <div v-else-if="activeTab === 'caching'" key="caching" class="space-y-6">
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- Cache Settings -->
            <div class="glass rounded-2xl p-6">
              <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Cache Settings</h3>
              <div class="space-y-4">
                <!-- Enable/Disable Toggle -->
                <div class="flex items-center justify-between">
                  <div>
                    <span class="text-sm font-medium text-[var(--text-primary)]">Enable Caching</span>
                    <p class="text-xs text-[var(--text-muted)] mt-0.5">Cache dynamic content to improve page load speed</p>
                  </div>
                  <button
                    class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
                    :class="cacheForm.cache_enabled ? 'bg-primary' : 'bg-[var(--border)]'"
                    @click="cacheForm.cache_enabled = !cacheForm.cache_enabled"
                  >
                    <span
                      class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
                      :class="cacheForm.cache_enabled ? 'translate-x-6' : 'translate-x-1'"
                    />
                  </button>
                </div>

                <!-- Cache Type -->
                <div>
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Cache Type</label>
                  <select
                    v-model="cacheForm.cache_type"
                    :disabled="!cacheForm.cache_enabled"
                    class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50 disabled:opacity-50"
                  >
                    <option value="fastcgi">FastCGI Cache</option>
                    <option value="proxy">Proxy Cache</option>
                  </select>
                  <p class="text-xs text-[var(--text-muted)] mt-1">
                    <strong>FastCGI</strong> &mdash; caches PHP responses directly from PHP-FPM.<br/>
                    <strong>Proxy</strong> &mdash; caches responses from an upstream backend.
                  </p>
                </div>

                <!-- TTL -->
                <div>
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Cache TTL (seconds)</label>
                  <input
                    v-model.number="cacheForm.cache_ttl"
                    type="number"
                    min="0"
                    max="86400"
                    :disabled="!cacheForm.cache_enabled"
                    class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50 disabled:opacity-50"
                  />
                  <p class="text-xs text-[var(--text-muted)] mt-1">How long cached responses are stored (0-86400). Default: 3600 (1 hour).</p>
                </div>

                <!-- Bypass Cookie -->
                <div>
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Bypass Cookie</label>
                  <input
                    v-model="cacheForm.cache_bypass_cookie"
                    type="text"
                    :disabled="!cacheForm.cache_enabled"
                    placeholder="wordpress_logged_in"
                    class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 disabled:opacity-50"
                  />
                  <p class="text-xs text-[var(--text-muted)] mt-1">Skip cache when this cookie is present (e.g., logged-in users).</p>
                </div>

                <button
                  class="w-full btn-primary py-2.5 mt-2"
                  :disabled="cacheSaving"
                  @click="saveCacheSettings"
                >
                  <span v-if="cacheSaving" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
                  {{ cacheSaving ? 'Saving...' : 'Save Cache Settings' }}
                </button>
              </div>
            </div>

            <!-- Cache Actions -->
            <div class="glass rounded-2xl p-6">
              <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Actions</h3>
              <div class="space-y-4">
                <div class="p-4 rounded-lg bg-[var(--background)] border border-[var(--border)]">
                  <h4 class="text-sm font-medium text-[var(--text-primary)] mb-1">Purge Cache</h4>
                  <p class="text-xs text-[var(--text-muted)] mb-3">Remove all cached content for this domain. New requests will be served fresh from the backend.</p>
                  <button
                    class="w-full btn-secondary py-2.5"
                    :disabled="cachePurging || !domain.cache_enabled"
                    @click="purgeCache"
                  >
                    <span v-if="cachePurging" class="inline-block w-4 h-4 border-2 border-current/30 border-t-current rounded-full animate-spin mr-2"></span>
                    {{ cachePurging ? 'Purging...' : 'Purge All Cache' }}
                  </button>
                </div>

                <!-- Cache Status -->
                <div class="p-4 rounded-lg bg-[var(--background)] border border-[var(--border)]">
                  <h4 class="text-sm font-medium text-[var(--text-primary)] mb-2">Current Status</h4>
                  <dl class="space-y-2">
                    <div class="flex justify-between">
                      <dt class="text-xs text-[var(--text-muted)]">Status</dt>
                      <dd>
                        <span
                          class="inline-flex items-center px-2 py-0.5 rounded-badge text-xs font-medium"
                          :class="domain.cache_enabled ? 'bg-success/10 text-success' : 'bg-[var(--border)] text-[var(--text-muted)]'"
                        >
                          {{ domain.cache_enabled ? 'Enabled' : 'Disabled' }}
                        </span>
                      </dd>
                    </div>
                    <div class="flex justify-between">
                      <dt class="text-xs text-[var(--text-muted)]">Type</dt>
                      <dd class="text-xs text-[var(--text-primary)]">{{ cacheTypeLabel(domain.cache_type) }}</dd>
                    </div>
                    <div class="flex justify-between">
                      <dt class="text-xs text-[var(--text-muted)]">TTL</dt>
                      <dd class="text-xs text-[var(--text-primary)]">{{ formatTTL(domain.cache_ttl) }}</dd>
                    </div>
                    <div class="flex justify-between">
                      <dt class="text-xs text-[var(--text-muted)]">Bypass Cookie</dt>
                      <dd class="text-xs text-[var(--text-primary)] font-mono">{{ domain.cache_bypass_cookie }}</dd>
                    </div>
                  </dl>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Error Pages Tab -->
        <div v-else-if="activeTab === 'error-pages'" key="error-pages" class="space-y-6">
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- Error Page Cards -->
            <div class="glass rounded-2xl p-6 lg:col-span-2">
              <div class="flex items-center justify-between mb-6">
                <div>
                  <h3 class="text-lg font-semibold text-[var(--text-primary)]">Custom Error Pages</h3>
                  <p class="text-sm text-[var(--text-muted)] mt-1">Configure custom error pages for different HTTP status codes.</p>
                </div>
                <button
                  class="btn-primary text-sm py-2 px-4"
                  :disabled="errorPagesSaving"
                  @click="saveErrorPages"
                >
                  <span v-if="errorPagesSaving" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
                  {{ errorPagesSaving ? 'Saving...' : 'Save All' }}
                </button>
              </div>

              <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                <div
                  v-for="ep in errorPageEntries"
                  :key="ep.code"
                  class="p-4 rounded-xl bg-[var(--background)] border border-[var(--border)] space-y-3"
                >
                  <!-- Header -->
                  <div class="flex items-center justify-between">
                    <div class="flex items-center gap-2">
                      <span
                        class="inline-flex items-center justify-center w-10 h-10 rounded-lg text-sm font-bold"
                        :class="ep.colorClass"
                      >{{ ep.code }}</span>
                      <div>
                        <span class="text-sm font-medium text-[var(--text-primary)]">{{ ep.label }}</span>
                        <p class="text-xs text-[var(--text-muted)]">{{ ep.description }}</p>
                      </div>
                    </div>
                  </div>

                  <!-- Mode Toggle -->
                  <div>
                    <label class="block text-xs font-medium text-[var(--text-muted)] mb-1.5">Mode</label>
                    <div class="flex rounded-lg overflow-hidden border border-[var(--border)]">
                      <button
                        v-for="mode in ['default', 'url', 'html']"
                        :key="mode"
                        class="flex-1 text-xs py-1.5 transition-colors capitalize"
                        :class="ep.mode === mode
                          ? 'bg-primary text-white'
                          : 'bg-[var(--surface)] text-[var(--text-muted)] hover:text-[var(--text-primary)]'"
                        @click="ep.mode = mode; if (mode === 'default') ep.value = ''"
                      >{{ mode === 'url' ? 'Custom URL' : mode === 'html' ? 'Custom HTML' : 'Default' }}</button>
                    </div>
                  </div>

                  <!-- Custom URL Input -->
                  <div v-if="ep.mode === 'url'">
                    <label class="block text-xs font-medium text-[var(--text-muted)] mb-1">Page Path</label>
                    <input
                      v-model="ep.value"
                      type="text"
                      placeholder="/custom_404.html"
                      class="w-full px-3 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                    />
                    <p class="text-xs text-[var(--text-muted)] mt-1">Path relative to document root.</p>
                  </div>

                  <!-- Custom HTML Editor -->
                  <div v-if="ep.mode === 'html'">
                    <label class="block text-xs font-medium text-[var(--text-muted)] mb-1">HTML Content</label>
                    <textarea
                      v-model="ep.value"
                      rows="6"
                      placeholder="<!DOCTYPE html>&#10;<html>&#10;  <body>&#10;    <h1>Error</h1>&#10;  </body>&#10;</html>"
                      class="w-full px-3 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-xs text-[var(--text-primary)] font-mono placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 resize-y"
                    />
                    <div class="flex gap-2 mt-2">
                      <button class="btn-ghost text-xs py-1 px-2" @click="previewErrorPage(ep)">
                        Preview
                      </button>
                      <button class="btn-ghost text-xs py-1 px-2" @click="useErrorTemplate(ep)">
                        Use Template
                      </button>
                    </div>
                  </div>

                  <!-- Use Template button for URL mode -->
                  <div v-if="ep.mode === 'url'">
                    <button class="btn-ghost text-xs py-1 px-2" @click="ep.mode = 'html'; useErrorTemplate(ep)">
                      Use Styled Template Instead
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>


        <!-- Directory Privacy Tab -->
        <div v-else-if="activeTab === 'privacy'" key="privacy" class="space-y-6">
          <div class="glass rounded-2xl p-6">
            <div class="flex items-center justify-between mb-4">
              <div>
                <h3 class="text-lg font-semibold text-[var(--text-primary)]">Directory Privacy</h3>
                <p class="text-sm text-[var(--text-muted)] mt-1">Password-protect directories with .htpasswd authentication</p>
              </div>
              <button class="btn-primary text-sm px-4 py-2" @click="showProtectDirModal = true">
                Protect Directory
              </button>
            </div>

            <div v-if="dpLoading" class="space-y-3">
              <LoadingSkeleton v-for="i in 3" :key="i" class="h-16 w-full" />
            </div>

            <div v-else-if="dpRules.length === 0" class="text-center py-12">
              <div class="text-4xl mb-3 opacity-50">&#128274;</div>
              <p class="text-[var(--text-muted)] text-sm">No directories are protected yet.</p>
              <p class="text-[var(--text-muted)] text-xs mt-1">Click &quot;Protect Directory&quot; to add password authentication to a path.</p>
            </div>

            <div v-else class="space-y-3">
              <div
                v-for="rule in dpRules"
                :key="rule.id"
                class="border border-[var(--border)] rounded-xl overflow-hidden"
              >
                <div
                  class="flex items-center gap-4 p-4 cursor-pointer hover:bg-[var(--surface)] transition-colors"
                  @click="dpExpandedRule === rule.id ? dpExpandedRule = null : dpExpandedRule = rule.id"
                >
                  <div class="shrink-0">
                    <span class="inline-flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10 text-primary text-sm font-mono">&#128274;</span>
                  </div>
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                      <span class="text-sm font-medium text-[var(--text-primary)] font-mono">{{ rule.path }}</span>
                      <span class="text-xs px-2 py-0.5 rounded-badge bg-[var(--surface)] text-[var(--text-muted)]">{{ rule.auth_name }}</span>
                    </div>
                    <div class="text-xs text-[var(--text-muted)] mt-0.5">{{ rule.user_count }} {{ rule.user_count === 1 ? 'user' : 'users' }}</div>
                  </div>
                  <div class="flex items-center gap-3 shrink-0">
                    <button
                      class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
                      :class="rule.is_active ? 'bg-primary' : 'bg-[var(--border)]'"
                      @click.stop="toggleDpActive(rule)"
                      :title="rule.is_active ? 'Active' : 'Inactive'"
                    >
                      <span class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform" :class="rule.is_active ? 'translate-x-6' : 'translate-x-1'" />
                    </button>
                    <button class="p-1.5 rounded-lg hover:bg-error/10 text-[var(--text-muted)] hover:text-error transition-colors" title="Remove protection" @click.stop="confirmDeleteDp(rule)">
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                    </button>
                    <svg class="w-4 h-4 text-[var(--text-muted)] transition-transform" :class="dpExpandedRule === rule.id ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
                  </div>
                </div>

                <div v-if="dpExpandedRule === rule.id" class="border-t border-[var(--border)] bg-[var(--background)] p-4">
                  <div class="flex items-center justify-between mb-3">
                    <h4 class="text-sm font-medium text-[var(--text-primary)]">Authorized Users</h4>
                    <button class="text-xs btn-secondary px-3 py-1.5" @click="openAddUserModal(rule)">Add User</button>
                  </div>
                  <div v-if="rule.users.length === 0" class="text-center py-4">
                    <p class="text-xs text-[var(--text-muted)]">No users added yet. Add a user to enable authentication.</p>
                  </div>
                  <div v-else class="space-y-2">
                    <div v-for="user in rule.users" :key="user.username" class="flex items-center justify-between p-2.5 rounded-lg bg-[var(--surface)] border border-[var(--border)]">
                      <div class="flex items-center gap-2">
                        <span class="inline-flex items-center justify-center w-7 h-7 rounded-full bg-primary/10 text-primary text-xs font-medium">{{ user.username.charAt(0).toUpperCase() }}</span>
                        <span class="text-sm text-[var(--text-primary)] font-mono">{{ user.username }}</span>
                      </div>
                      <button class="p-1 rounded hover:bg-error/10 text-[var(--text-muted)] hover:text-error transition-colors" title="Remove user" @click="removeDpUser(rule, user.username)">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Redirects Tab -->
        <div v-else-if="activeTab === 'redirects'" key="redirects" class="space-y-6">
          <div class="glass rounded-2xl p-6">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-lg font-semibold text-[var(--text-primary)]">URL Redirects</h3>
              <button class="btn-primary text-sm py-2 px-4" @click="openAddRedirect">
                Add Redirect
              </button>
            </div>

            <div v-if="redirectsLoading" class="space-y-2">
              <LoadingSkeleton v-for="i in 3" :key="i" class="h-12 w-full" />
            </div>
            <div v-else-if="redirects.length === 0" class="text-center py-12">
              <p class="text-[var(--text-muted)] text-sm mb-1">No redirects configured</p>
              <p class="text-[var(--text-muted)] text-xs">Add a redirect to forward traffic from one URL to another.</p>
            </div>
            <div v-else class="overflow-x-auto">
              <table class="w-full text-sm">
                <thead>
                  <tr class="border-b border-[var(--border)]">
                    <th class="text-left py-2 px-2 text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Source Path</th>
                    <th class="text-left py-2 px-2 text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Destination</th>
                    <th class="text-center py-2 px-2 text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Type</th>
                    <th class="text-center py-2 px-2 text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Regex</th>
                    <th class="text-center py-2 px-2 text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Active</th>
                    <th class="text-right py-2 px-2 text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Actions</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-[var(--border)]">
                  <tr v-for="r in redirects" :key="r.id" class="hover:bg-[var(--surface)] transition-colors">
                    <td class="py-3 px-2 font-mono text-[var(--text-primary)] break-all max-w-[200px]">{{ r.source_path }}</td>
                    <td class="py-3 px-2 text-[var(--text-primary)] break-all max-w-[250px]">{{ r.destination_url }}</td>
                    <td class="py-3 px-2 text-center">
                      <span
                        class="inline-flex items-center px-2 py-0.5 rounded-badge text-xs font-medium"
                        :class="{
                          'bg-primary/10 text-primary': r.redirect_type === 301,
                          'bg-warning/10 text-warning': r.redirect_type === 302,
                          'bg-info/10 text-info': r.redirect_type === 307,
                        }"
                      >{{ r.redirect_type }}</span>
                    </td>
                    <td class="py-3 px-2 text-center">
                      <button
                        class="relative inline-flex h-5 w-9 items-center rounded-full transition-colors"
                        :class="r.is_regex ? 'bg-primary' : 'bg-[var(--border)]'"
                        @click="toggleRedirectField(r, 'is_regex')"
                      >
                        <span
                          class="inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform"
                          :class="r.is_regex ? 'translate-x-4.5' : 'translate-x-0.5'"
                        />
                      </button>
                    </td>
                    <td class="py-3 px-2 text-center">
                      <button
                        class="relative inline-flex h-5 w-9 items-center rounded-full transition-colors"
                        :class="r.is_active ? 'bg-success' : 'bg-[var(--border)]'"
                        @click="toggleRedirectField(r, 'is_active')"
                      >
                        <span
                          class="inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform"
                          :class="r.is_active ? 'translate-x-4.5' : 'translate-x-0.5'"
                        />
                      </button>
                    </td>
                    <td class="py-3 px-2 text-right">
                      <div class="flex items-center justify-end gap-1">
                        <button
                          class="p-1.5 rounded-md hover:bg-[var(--surface)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
                          title="Edit"
                          @click="openEditRedirect(r)"
                        >
                          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
                        </button>
                        <button
                          class="p-1.5 rounded-md hover:bg-error/10 text-[var(--text-muted)] hover:text-error transition-colors"
                          title="Delete"
                          @click="confirmDeleteRedirect(r)"
                        >
                          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                        </button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <!-- Security Tab (Hotlink Protection) -->
        <div v-else-if="activeTab === 'security'" key="security" class="space-y-6">
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- Hotlink Protection Settings -->
            <div class="glass rounded-2xl p-6">
              <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Hotlink Protection</h3>
              <div class="space-y-4">
                <!-- Enable/Disable Toggle -->
                <div class="flex items-center justify-between">
                  <div>
                    <span class="text-sm font-medium text-[var(--text-primary)]">Enable Hotlink Protection</span>
                    <p class="text-xs text-[var(--text-muted)] mt-0.5">Prevent other websites from directly linking to your images, videos, and other media files.</p>
                  </div>
                  <button
                    class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
                    :class="hotlinkForm.hotlink_protection ? 'bg-primary' : 'bg-[var(--border)]'"
                    @click="hotlinkForm.hotlink_protection = !hotlinkForm.hotlink_protection"
                  >
                    <span
                      class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
                      :class="hotlinkForm.hotlink_protection ? 'translate-x-6' : 'translate-x-1'"
                    />
                  </button>
                </div>

                <!-- Protected Extensions (chips/tags) -->
                <div>
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Protected File Extensions</label>
                  <div class="flex flex-wrap gap-1.5 mb-2" v-if="hotlinkExtensionsAsArray().length">
                    <span
                      v-for="ext in hotlinkExtensionsAsArray()"
                      :key="ext"
                      class="inline-flex items-center gap-1 px-2.5 py-1 rounded-badge text-xs font-medium bg-primary/10 text-primary"
                    >
                      .{{ ext }}
                      <button
                        class="ml-0.5 hover:text-error transition-colors"
                        :disabled="!hotlinkForm.hotlink_protection"
                        @click="removeHotlinkExtension(ext)"
                        title="Remove"
                      >&times;</button>
                    </span>
                  </div>
                  <div class="flex gap-2">
                    <input
                      v-model="hotlinkExtensionInput"
                      type="text"
                      :disabled="!hotlinkForm.hotlink_protection"
                      placeholder="e.g. pdf"
                      class="flex-1 px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 disabled:opacity-50"
                      @keydown.enter.prevent="addHotlinkExtension"
                    />
                    <button
                      class="btn-secondary px-3 py-2 text-sm"
                      :disabled="!hotlinkForm.hotlink_protection || !hotlinkExtensionInput.trim()"
                      @click="addHotlinkExtension"
                    >Add</button>
                  </div>
                  <p class="text-xs text-[var(--text-muted)] mt-1">File types that will be protected from hotlinking. Type an extension and press Enter or click Add.</p>
                </div>

                <!-- Allowed Domains -->
                <div>
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Allowed Domains</label>
                  <textarea
                    :value="hotlinkAllowedDomainsForDisplay()"
                    @input="setHotlinkAllowedDomains($event.target.value)"
                    rows="4"
                    :disabled="!hotlinkForm.hotlink_protection"
                    placeholder="example.com&#10;*.example.com&#10;trusted-site.org"
                    class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] font-mono placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 disabled:opacity-50"
                  />
                  <p class="text-xs text-[var(--text-muted)] mt-1">One domain per line. These domains will be allowed to link to your files. Your own domain is always allowed.</p>
                </div>

                <!-- Redirect URL -->
                <div>
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Redirect URL (optional)</label>
                  <input
                    v-model="hotlinkForm.hotlink_redirect_url"
                    type="text"
                    :disabled="!hotlinkForm.hotlink_protection"
                    placeholder="https://example.com/hotlink-notice.html"
                    class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 disabled:opacity-50"
                  />
                  <p class="text-xs text-[var(--text-muted)] mt-1">Hotlinkers will be redirected to this URL. If empty, a 403 Forbidden response is returned instead.</p>
                </div>

                <button
                  class="w-full btn-primary py-2.5 mt-2"
                  :disabled="hotlinkSaving"
                  @click="saveHotlinkSettings"
                >
                  <span v-if="hotlinkSaving" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
                  {{ hotlinkSaving ? 'Saving...' : 'Save Hotlink Settings' }}
                </button>
              </div>
            </div>

            <!-- Hotlink Status / Info -->
            <div class="glass rounded-2xl p-6">
              <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Current Status</h3>
              <div class="space-y-4">
                <div class="p-4 rounded-lg bg-[var(--background)] border border-[var(--border)]">
                  <dl class="space-y-3">
                    <div class="flex justify-between">
                      <dt class="text-sm text-[var(--text-muted)]">Hotlink Protection</dt>
                      <dd>
                        <span
                          class="inline-flex items-center px-2 py-0.5 rounded-badge text-xs font-medium"
                          :class="domain.hotlink_protection ? 'bg-success/10 text-success' : 'bg-[var(--border)] text-[var(--text-muted)]'"
                        >
                          {{ domain.hotlink_protection ? 'Enabled' : 'Disabled' }}
                        </span>
                      </dd>
                    </div>
                    <div class="flex justify-between">
                      <dt class="text-sm text-[var(--text-muted)]">Protected Extensions</dt>
                      <dd class="text-sm text-[var(--text-primary)] text-right max-w-[60%] break-all">{{ domain.hotlink_extensions || '--' }}</dd>
                    </div>
                    <div class="flex justify-between">
                      <dt class="text-sm text-[var(--text-muted)]">Action</dt>
                      <dd class="text-sm text-[var(--text-primary)]">{{ domain.hotlink_redirect_url ? 'Redirect (301)' : '403 Forbidden' }}</dd>
                    </div>
                    <div v-if="domain.hotlink_redirect_url" class="flex justify-between">
                      <dt class="text-sm text-[var(--text-muted)]">Redirect URL</dt>
                      <dd class="text-sm text-[var(--text-primary)] text-right max-w-[60%] break-all font-mono">{{ domain.hotlink_redirect_url }}</dd>
                    </div>
                    <div v-if="domain.hotlink_allowed_domains" class="flex justify-between">
                      <dt class="text-sm text-[var(--text-muted)]">Allowed Domains</dt>
                      <dd class="text-sm text-[var(--text-primary)] text-right max-w-[60%] break-all">{{ domain.hotlink_allowed_domains }}</dd>
                    </div>
                  </dl>
                </div>

                <div class="p-4 rounded-lg bg-[var(--background)] border border-[var(--border)]">
                  <h4 class="text-sm font-medium text-[var(--text-primary)] mb-2">How it works</h4>
                  <ul class="text-xs text-[var(--text-muted)] space-y-1.5 list-disc list-inside">
                    <li>Checks the HTTP <code class="bg-[var(--surface)] px-1 rounded">Referer</code> header on requests for protected file types.</li>
                    <li>Requests from your own domain and allowed domains are served normally.</li>
                    <li>Direct access (no referer) and search engine crawlers are always allowed.</li>
                    <li>All other requests are blocked with a 403 or redirected to your chosen URL.</li>
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Git Deploy Tab -->
        <div v-else-if="activeTab === 'git'" key="git" class="space-y-6">
          <!-- Setup Form (when not configured) -->
          <div v-if="!gitDeploy" class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div class="glass rounded-2xl p-6 lg:col-span-2">
              <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-2">Set Up Git Deployment</h3>
              <p class="text-sm text-[var(--text-muted)] mb-6">Deploy code directly from your Git repository. Push to deploy with automatic builds.</p>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div class="md:col-span-2">
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Repository URL</label>
                  <input
                    v-model="gitForm.repo_url"
                    type="text"
                    placeholder="git@github.com:user/repo.git"
                    class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                  <p class="text-xs text-[var(--text-muted)] mt-1">SSH URL recommended for deploy key authentication.</p>
                </div>
                <div>
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Branch</label>
                  <input
                    v-model="gitForm.branch"
                    type="text"
                    placeholder="main"
                    class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
                <div>
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Build Command</label>
                  <input
                    v-model="gitForm.build_command"
                    type="text"
                    placeholder="npm install && npm run build"
                    class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                  <p class="text-xs text-[var(--text-muted)] mt-1">Optional. Runs after each pull.</p>
                </div>
                <div>
                  <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Post-Deploy Hook</label>
                  <input
                    v-model="gitForm.post_deploy_hook"
                    type="text"
                    placeholder="php artisan cache:clear"
                    class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                  <p class="text-xs text-[var(--text-muted)] mt-1">Optional. Runs after build completes.</p>
                </div>
                <div class="flex items-center gap-3">
                  <button
                    class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
                    :class="gitForm.auto_deploy ? 'bg-primary' : 'bg-[var(--border)]'"
                    @click="gitForm.auto_deploy = !gitForm.auto_deploy"
                  >
                    <span
                      class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
                      :class="gitForm.auto_deploy ? 'translate-x-6' : 'translate-x-1'"
                    />
                  </button>
                  <span class="text-sm text-[var(--text-primary)]">Auto-deploy on push</span>
                </div>
              </div>
              <button
                class="mt-6 btn-primary py-2.5 px-6"
                :disabled="gitSetupLoading || !gitForm.repo_url"
                @click="setupGitDeploy"
              >
                <span v-if="gitSetupLoading" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
                {{ gitSetupLoading ? 'Setting up...' : 'Set Up Git Deploy' }}
              </button>
            </div>
          </div>

          <!-- Configured State -->
          <div v-else class="space-y-6">
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <!-- Deploy Key -->
              <div class="glass rounded-2xl p-6">
                <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">SSH Deploy Key</h3>
                <p class="text-sm text-[var(--text-muted)] mb-3">Add this public key as a deploy key in your repository settings.</p>
                <div class="relative">
                  <pre class="bg-[var(--background)] border border-[var(--border)] rounded-lg p-3 text-xs font-mono text-[var(--text-primary)] whitespace-pre-wrap break-all pr-10 max-h-24 overflow-y-auto">{{ gitDeploy.deploy_key_public }}</pre>
                  <button
                    class="absolute top-2 right-2 p-1.5 rounded-md bg-[var(--surface)] border border-[var(--border)] hover:bg-[var(--border)] transition-colors"
                    title="Copy to clipboard"
                    @click="copyToClipboard(gitDeploy.deploy_key_public, 'Deploy key copied!')"
                  >
                    <svg class="w-4 h-4 text-[var(--text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>
                  </button>
                </div>
              </div>

              <!-- Webhook URL -->
              <div class="glass rounded-2xl p-6">
                <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Webhook URL</h3>
                <p class="text-sm text-[var(--text-muted)] mb-3">Add this URL as a webhook in your repository to enable auto-deploy.</p>
                <div class="relative">
                  <pre class="bg-[var(--background)] border border-[var(--border)] rounded-lg p-3 text-xs font-mono text-[var(--text-primary)] whitespace-pre-wrap break-all pr-10">{{ gitDeploy.webhook_url }}</pre>
                  <button
                    class="absolute top-2 right-2 p-1.5 rounded-md bg-[var(--surface)] border border-[var(--border)] hover:bg-[var(--border)] transition-colors"
                    title="Copy to clipboard"
                    @click="copyToClipboard(gitDeploy.webhook_url, 'Webhook URL copied!')"
                  >
                    <svg class="w-4 h-4 text-[var(--text-muted)]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>
                  </button>
                </div>
                <div class="mt-3 text-xs text-[var(--text-muted)]">
                  <strong>Webhook secret:</strong>
                  <code class="bg-[var(--background)] px-1.5 py-0.5 rounded text-[var(--text-primary)]">{{ gitDeploy.webhook_secret }}</code>
                  <button
                    class="ml-1 text-primary hover:underline"
                    @click="copyToClipboard(gitDeploy.webhook_secret, 'Webhook secret copied!')"
                  >copy</button>
                </div>
              </div>

              <!-- Deployment Status -->
              <div class="glass rounded-2xl p-6">
                <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Deployment Status</h3>
                <dl class="space-y-3">
                  <div class="flex justify-between">
                    <dt class="text-sm text-[var(--text-muted)]">Repository</dt>
                    <dd class="text-sm text-[var(--text-primary)] font-mono text-right break-all max-w-[60%]">{{ gitDeploy.repo_url }}</dd>
                  </div>
                  <div class="flex justify-between">
                    <dt class="text-sm text-[var(--text-muted)]">Branch</dt>
                    <dd>
                      <span class="inline-flex items-center px-2.5 py-0.5 rounded-badge text-xs font-medium bg-primary/10 text-primary">{{ gitDeploy.branch }}</span>
                    </dd>
                  </div>
                  <div class="flex justify-between">
                    <dt class="text-sm text-[var(--text-muted)]">Auto-Deploy</dt>
                    <dd>
                      <span
                        class="inline-flex items-center px-2.5 py-0.5 rounded-badge text-xs font-medium"
                        :class="gitDeploy.auto_deploy ? 'bg-success/10 text-success' : 'bg-[var(--border)] text-[var(--text-muted)]'"
                      >{{ gitDeploy.auto_deploy ? 'Enabled' : 'Disabled' }}</span>
                    </dd>
                  </div>
                  <div class="flex justify-between">
                    <dt class="text-sm text-[var(--text-muted)]">Last Deploy</dt>
                    <dd class="text-sm text-[var(--text-primary)]">{{ gitDeploy.last_deploy_at ? formatDate(gitDeploy.last_deploy_at) : 'Never' }}</dd>
                  </div>
                  <div class="flex justify-between">
                    <dt class="text-sm text-[var(--text-muted)]">Status</dt>
                    <dd>
                      <span
                        v-if="gitDeploy.last_deploy_status"
                        class="inline-flex items-center px-2.5 py-0.5 rounded-badge text-xs font-medium"
                        :class="{
                          'bg-success/10 text-success': gitDeploy.last_deploy_status === 'success',
                          'bg-error/10 text-error': gitDeploy.last_deploy_status === 'failed',
                          'bg-warning/10 text-warning': gitDeploy.last_deploy_status === 'deploying',
                        }"
                      >{{ gitDeploy.last_deploy_status }}</span>
                      <span v-else class="text-sm text-[var(--text-muted)]">--</span>
                    </dd>
                  </div>
                  <div v-if="gitDeploy.last_commit_hash" class="flex justify-between">
                    <dt class="text-sm text-[var(--text-muted)]">Commit</dt>
                    <dd class="text-sm text-[var(--text-primary)] font-mono">{{ gitDeploy.last_commit_hash?.substring(0, 8) }}</dd>
                  </div>
                  <div v-if="gitDeploy.build_command" class="flex justify-between">
                    <dt class="text-sm text-[var(--text-muted)]">Build</dt>
                    <dd class="text-sm text-[var(--text-primary)] font-mono text-right break-all max-w-[60%]">{{ gitDeploy.build_command }}</dd>
                  </div>
                </dl>
              </div>

              <!-- Actions -->
              <div class="glass rounded-2xl p-6">
                <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Actions</h3>
                <div class="space-y-3">
                  <button
                    class="w-full btn-primary py-3"
                    :disabled="gitDeploying"
                    @click="triggerGitDeploy"
                  >
                    <span v-if="gitDeploying" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
                    {{ gitDeploying ? 'Deploying...' : 'Deploy Now' }}
                  </button>
                  <button class="w-full btn-secondary py-3" @click="showGitSettings = true">
                    Edit Settings
                  </button>
                  <button class="w-full btn-secondary py-3 text-error" @click="showRemoveGit = true">
                    Remove Git Deploy
                  </button>
                </div>
              </div>
            </div>

            <!-- Deploy Output (after manual deploy) -->
            <div v-if="gitDeployOutput" class="glass rounded-2xl p-6">
              <div class="flex items-center justify-between mb-4">
                <h3 class="text-lg font-semibold text-[var(--text-primary)]">Deploy Output</h3>
                <button class="btn-ghost text-xs" @click="gitDeployOutput = ''">Dismiss</button>
              </div>
              <div class="bg-[var(--background)] rounded-lg p-4 max-h-64 overflow-y-auto font-mono text-xs text-[var(--text-primary)] leading-relaxed border border-[var(--border)] whitespace-pre-wrap">{{ gitDeployOutput }}</div>
            </div>

            <!-- Deploy Logs -->
            <div class="glass rounded-2xl p-6">
              <div class="flex items-center justify-between mb-4">
                <h3 class="text-lg font-semibold text-[var(--text-primary)]">Deployment History</h3>
                <button class="btn-ghost text-xs" @click="fetchGitLogs">Refresh</button>
              </div>
              <div v-if="gitLogsLoading" class="space-y-2">
                <LoadingSkeleton v-for="i in 5" :key="i" class="h-10 w-full" />
              </div>
              <div v-else-if="gitLogs.length === 0" class="text-center py-8 text-sm text-[var(--text-muted)]">
                No deployments yet.
              </div>
              <div v-else class="divide-y divide-[var(--border)]">
                <div
                  v-for="log in gitLogs"
                  :key="log.id"
                  class="py-3 flex items-center gap-4 cursor-pointer hover:bg-[var(--surface)] -mx-2 px-2 rounded-lg transition-colors"
                  @click="expandedLog === log.id ? expandedLog = null : expandedLog = log.id"
                >
                  <div class="shrink-0">
                    <span
                      class="inline-flex items-center justify-center w-8 h-8 rounded-full text-xs font-medium"
                      :class="{
                        'bg-success/10 text-success': log.status === 'success',
                        'bg-error/10 text-error': log.status === 'failed',
                        'bg-warning/10 text-warning': log.status === 'deploying',
                      }"
                    >
                      <span v-if="log.status === 'success'">&#10003;</span>
                      <span v-else-if="log.status === 'failed'">&#10007;</span>
                      <span v-else>...</span>
                    </span>
                  </div>
                  <div class="flex-1 min-w-0">
                    <div class="text-sm text-[var(--text-primary)]">
                      <span class="font-mono">{{ log.commit_hash?.substring(0, 8) || '--' }}</span>
                      <span class="mx-2 text-[var(--text-muted)]">&middot;</span>
                      <span class="text-[var(--text-muted)]">{{ log.trigger }}</span>
                    </div>
                    <div v-if="expandedLog === log.id && log.output" class="mt-2 bg-[var(--background)] rounded-lg p-3 font-mono text-xs text-[var(--text-primary)] whitespace-pre-wrap max-h-48 overflow-y-auto border border-[var(--border)]">{{ log.output }}</div>
                  </div>
                  <div class="text-right shrink-0">
                    <div class="text-xs text-[var(--text-muted)]">{{ formatDate(log.created_at) }}</div>
                    <div v-if="log.duration_seconds != null" class="text-xs text-[var(--text-muted)]">{{ log.duration_seconds }}s</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Logs Tab -->
        <div v-else-if="activeTab === 'logs'" key="logs" class="space-y-6">
          <div class="glass rounded-2xl p-6">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-lg font-semibold text-[var(--text-primary)]">{{ webserverLabel(domain.webserver) }} Logs</h3>
              <div class="flex gap-2">
                <button
                  class="text-xs px-3 py-1.5 rounded-lg transition-colors"
                  :class="logType === 'access' ? 'bg-primary text-white' : 'btn-ghost'"
                  @click="logType = 'access'"
                >
                  Access Log
                </button>
                <button
                  class="text-xs px-3 py-1.5 rounded-lg transition-colors"
                  :class="logType === 'error' ? 'bg-primary text-white' : 'btn-ghost'"
                  @click="logType = 'error'"
                >
                  Error Log
                </button>
              </div>
            </div>
            <div
              ref="logContainer"
              class="bg-[var(--background)] rounded-lg p-4 h-96 overflow-y-auto font-mono text-xs text-[var(--text-primary)] leading-relaxed border border-[var(--border)]"
            >
              <div v-if="logsLoading" class="space-y-1">
                <LoadingSkeleton v-for="i in 10" :key="i" class="h-3 w-full" />
              </div>
              <div v-else-if="logLines.length === 0" class="text-center text-[var(--text-muted)] py-8">
                No log entries found.
              </div>
              <div v-else>
                <div v-for="(line, i) in logLines" :key="i" class="hover:bg-[var(--surface)] px-1 rounded">
                  {{ line }}
                </div>
              </div>
            </div>
            <div class="flex justify-end mt-3">
              <button class="btn-ghost text-xs" @click="fetchLogs">Refresh</button>
            </div>
          </div>
        </div>

        <!-- Stats Tab -->
        <div v-else-if="activeTab === 'stats'" key="stats" class="space-y-6">
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- Bandwidth Chart -->
            <div class="glass rounded-2xl p-6">
              <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Bandwidth (Last 7 Days)</h3>
              <div v-if="statsLoading" class="space-y-3">
                <LoadingSkeleton v-for="i in 7" :key="i" class="h-8 w-full" />
              </div>
              <div v-else class="space-y-2">
                <div v-for="day in bandwidthData" :key="day.date" class="flex items-center gap-3">
                  <span class="text-xs text-[var(--text-muted)] w-16 shrink-0">{{ formatShortDate(day.date) }}</span>
                  <div class="flex-1 bg-[var(--background)] rounded-full h-6 overflow-hidden">
                    <div
                      class="h-full bg-primary/70 rounded-full transition-all duration-500"
                      :style="{ width: bandwidthPercent(day.bytes) + '%' }"
                    />
                  </div>
                  <span class="text-xs text-[var(--text-muted)] w-20 text-right shrink-0">{{ formatBytes(day.bytes) }}</span>
                </div>
              </div>
            </div>

            <!-- Requests Chart -->
            <div class="glass rounded-2xl p-6">
              <h3 class="text-lg font-semibold text-[var(--text-primary)] mb-4">Requests per Day (Last 7 Days)</h3>
              <div v-if="statsLoading" class="space-y-3">
                <LoadingSkeleton v-for="i in 7" :key="i" class="h-8 w-full" />
              </div>
              <div v-else class="space-y-2">
                <div v-for="day in requestsData" :key="day.date" class="flex items-center gap-3">
                  <span class="text-xs text-[var(--text-muted)] w-16 shrink-0">{{ formatShortDate(day.date) }}</span>
                  <div class="flex-1 bg-[var(--background)] rounded-full h-6 overflow-hidden">
                    <div
                      class="h-full bg-success/70 rounded-full transition-all duration-500"
                      :style="{ width: requestsPercent(day.count) + '%' }"
                    />
                  </div>
                  <span class="text-xs text-[var(--text-muted)] w-16 text-right shrink-0">{{ day.count.toLocaleString() }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </div>

    <!-- Edit PHP Modal -->
    <Modal v-model="showEditPhp" title="Change PHP Version" size="sm">
      <div>
        <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">PHP Version</label>
        <select
          v-model="editPhpVersion"
          class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
        >
          <option v-for="v in phpVersions" :key="v" :value="v">PHP {{ v }}</option>
        </select>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showEditPhp = false">Cancel</button>
        <button class="btn-primary" @click="updatePhp">Save</button>
      </template>
    </Modal>

    <!-- Edit Webserver Modal -->
    <Modal v-model="showEditWebserver" title="Change Web Server" size="sm">
      <div>
        <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Web Server</label>
        <select
          v-model="editWebserver"
          class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
        >
          <option value="nginx">Nginx</option>
          <option value="apache">Apache</option>
          <option value="nginx_apache">Nginx + Apache</option>
        </select>
        <p class="text-xs text-[var(--text-muted)] mt-2">
          <strong>Nginx</strong> &mdash; lightweight, high-performance web server.<br/>
          <strong>Apache</strong> &mdash; traditional web server with .htaccess support.<br/>
          <strong>Nginx + Apache</strong> &mdash; Nginx reverse proxy on ports 80/443, Apache on 8080 for PHP &amp; .htaccess.
        </p>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showEditWebserver = false">Cancel</button>
        <button class="btn-primary" @click="updateWebserver">Save</button>
      </template>
    </Modal>

    <!-- Upload Cert Modal -->
    <Modal v-model="showUploadCert" title="Upload Custom Certificate" size="md">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Certificate (PEM)</label>
          <textarea
            v-model="certForm.certificate"
            rows="4"
            placeholder="-----BEGIN CERTIFICATE-----"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] font-mono placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Private Key (PEM)</label>
          <textarea
            v-model="certForm.private_key"
            rows="4"
            placeholder="-----BEGIN PRIVATE KEY-----"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] font-mono placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showUploadCert = false">Cancel</button>
        <button class="btn-primary" @click="uploadCert">Upload</button>
      </template>
    </Modal>

    <!-- Git Settings Modal -->
    <Modal v-model="showGitSettings" title="Edit Git Deploy Settings" size="md">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Repository URL</label>
          <input
            v-model="gitEditForm.repo_url"
            type="text"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Branch</label>
          <input
            v-model="gitEditForm.branch"
            type="text"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Build Command</label>
          <input
            v-model="gitEditForm.build_command"
            type="text"
            placeholder="npm install && npm run build"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Post-Deploy Hook</label>
          <input
            v-model="gitEditForm.post_deploy_hook"
            type="text"
            placeholder="php artisan cache:clear"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
        <div class="flex items-center gap-3">
          <button
            class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
            :class="gitEditForm.auto_deploy ? 'bg-primary' : 'bg-[var(--border)]'"
            @click="gitEditForm.auto_deploy = !gitEditForm.auto_deploy"
          >
            <span
              class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
              :class="gitEditForm.auto_deploy ? 'translate-x-6' : 'translate-x-1'"
            />
          </button>
          <span class="text-sm text-[var(--text-primary)]">Auto-deploy on push</span>
        </div>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showGitSettings = false">Cancel</button>
        <button class="btn-primary" :disabled="gitSettingsSaving" @click="saveGitSettings">
          {{ gitSettingsSaving ? 'Saving...' : 'Save' }}
        </button>
      </template>
    </Modal>

    <!-- Remove Git Deploy Confirm -->
    <ConfirmDialog
      v-model="showRemoveGit"
      title="Remove Git Deployment"
      :message="`Remove push-to-deploy configuration for '${domain?.name}'? The deployed files will remain intact.`"
      confirm-text="Remove"
      :destructive="true"
      @confirm="removeGitDeploy"
    />

    <!-- Add/Edit Redirect Modal -->
    <Modal v-model="showRedirectModal" :title="editingRedirect ? 'Edit Redirect' : 'Add Redirect'" size="md">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Source Path</label>
          <input
            v-model="redirectForm.source_path"
            type="text"
            placeholder="/old-page"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] font-mono placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
          <p class="text-xs text-[var(--text-muted)] mt-1">The path to redirect from. Use regex patterns if regex is enabled.</p>
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Destination URL</label>
          <input
            v-model="redirectForm.destination_url"
            type="text"
            placeholder="https://example.com/new-page"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
          <p class="text-xs text-[var(--text-muted)] mt-1">The full URL to redirect to.</p>
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Redirect Type</label>
          <select
            v-model.number="redirectForm.redirect_type"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          >
            <option :value="301">301 - Permanent Redirect</option>
            <option :value="302">302 - Temporary Redirect</option>
            <option :value="307">307 - Temporary Redirect (preserve method)</option>
          </select>
        </div>
        <div class="flex items-center gap-3">
          <button
            class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
            :class="redirectForm.is_regex ? 'bg-primary' : 'bg-[var(--border)]'"
            @click="redirectForm.is_regex = !redirectForm.is_regex"
          >
            <span
              class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
              :class="redirectForm.is_regex ? 'translate-x-6' : 'translate-x-1'"
            />
          </button>
          <div>
            <span class="text-sm text-[var(--text-primary)]">Regex Pattern</span>
            <p class="text-xs text-[var(--text-muted)]">Enable to use regular expressions in the source path.</p>
          </div>
        </div>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showRedirectModal = false">Cancel</button>
        <button
          class="btn-primary"
          :disabled="redirectSaving || !redirectForm.source_path || !redirectForm.destination_url"
          @click="saveRedirect"
        >
          <span v-if="redirectSaving" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          {{ redirectSaving ? 'Saving...' : (editingRedirect ? 'Update' : 'Create') }}
        </button>
      </template>
    </Modal>

    <!-- Delete Redirect Confirm -->
    <ConfirmDialog
      v-model="showDeleteRedirect"
      title="Delete Redirect"
      :message="`Delete the redirect from '${deletingRedirect?.source_path}'? This will update your nginx configuration.`"
      confirm-text="Delete"
      :destructive="true"
      @confirm="deleteRedirect"
    />

    <!-- Protect Directory Modal -->
    <Modal v-model="showProtectDirModal" title="Protect Directory" size="sm">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Directory Path</label>
          <input
            v-model="dpForm.path"
            type="text"
            placeholder="/admin"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] font-mono placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
          <p class="text-xs text-[var(--text-muted)] mt-1">The path relative to document root (e.g. /admin, /secret, /members).</p>
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Realm Name</label>
          <input
            v-model="dpForm.auth_name"
            type="text"
            placeholder="Restricted Area"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
          <p class="text-xs text-[var(--text-muted)] mt-1">The message shown in the browser authentication dialog.</p>
        </div>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showProtectDirModal = false">Cancel</button>
        <button class="btn-primary" :disabled="dpCreating || !dpForm.path" @click="createDpRule">
          {{ dpCreating ? 'Creating...' : 'Protect' }}
        </button>
      </template>
    </Modal>

    <!-- Add User to Directory Modal -->
    <Modal v-model="showAddUserModal" title="Add User" size="sm">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Username</label>
          <input
            v-model="dpUserForm.username"
            type="text"
            placeholder="admin"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] font-mono placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Password</label>
          <input
            v-model="dpUserForm.password"
            type="password"
            placeholder="Enter password"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
      </div>
      <template #actions>
        <button class="btn-secondary" @click="showAddUserModal = false">Cancel</button>
        <button class="btn-primary" :disabled="dpAddingUser || !dpUserForm.username || !dpUserForm.password" @click="addDpUser">
          {{ dpAddingUser ? 'Adding...' : 'Add User' }}
        </button>
      </template>
    </Modal>

    <!-- Delete Directory Privacy Confirm -->
    <ConfirmDialog
      v-model="showDeleteDpDialog"
      title="Remove Directory Protection"
      :message="`Remove password protection from '${dpDeleteTarget?.path}'? Users will no longer need credentials to access this directory.`"
      confirm-text="Remove"
      :destructive="true"
      @confirm="deleteDpRule"
    />

    <!-- Delete Confirm -->
    <ConfirmDialog
      v-model="showDeleteDialog"
      title="Delete Domain"
      :message="`Permanently delete '${domain?.name}' and all associated data?`"
      confirm-text="Delete"
      :destructive="true"
      @confirm="handleDelete"
    />

    <!-- Add Subdomain Modal -->
    <Modal v-model="showAddSubdomain" title="Add Subdomain" size="md">
      <form @submit.prevent="handleAddSubdomain" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Subdomain Prefix</label>
          <div class="flex items-center gap-2">
            <input
              v-model="subdomainForm.subdomain_prefix"
              type="text"
              placeholder="blog"
              required
              class="flex-1 px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
              :class="{ 'border-error': subdomainFormErrors.subdomain_prefix }"
            />
            <span class="text-sm text-[var(--text-muted)] shrink-0">.{{ domain?.domain_name }}</span>
          </div>
          <p v-if="subdomainFormErrors.subdomain_prefix" class="mt-1 text-xs text-error">{{ subdomainFormErrors.subdomain_prefix }}</p>
          <p v-else class="mt-1 text-xs text-[var(--text-muted)]">Full address: <strong>{{ subdomainFullName }}</strong></p>
        </div>

        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Document Root</label>
          <input
            v-model="subdomainForm.document_root"
            type="text"
            :placeholder="subdomainDocRoot"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
          />
          <p class="mt-1 text-xs text-[var(--text-muted)]">Leave empty to use the default path.</p>
        </div>

        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">PHP Version</label>
          <select
            v-model="subdomainForm.php_version"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
          >
            <option v-for="v in phpVersions" :key="v" :value="v">PHP {{ v }}</option>
          </select>
        </div>

        <div class="flex items-center gap-3">
          <button
            type="button"
            class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
            :class="subdomainForm.enable_ssl ? 'bg-primary' : 'bg-[var(--border)]'"
            @click="subdomainForm.enable_ssl = !subdomainForm.enable_ssl"
          >
            <span
              class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
              :class="subdomainForm.enable_ssl ? 'translate-x-6' : 'translate-x-1'"
            />
          </button>
          <div>
            <span class="text-sm text-[var(--text-primary)]">Enable SSL</span>
            <p class="text-xs text-[var(--text-muted)]">Issue a Let's Encrypt certificate automatically</p>
          </div>
        </div>
      </form>

      <template #actions>
        <button class="btn-secondary" @click="showAddSubdomain = false">Cancel</button>
        <button class="btn-primary" :disabled="subdomainSubmitting" @click="handleAddSubdomain">
          <span v-if="subdomainSubmitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          {{ subdomainSubmitting ? 'Creating...' : 'Create Subdomain' }}
        </button>
      </template>
    </Modal>

    <!-- Delete Subdomain Confirm -->
    <ConfirmDialog
      v-model="showDeleteSubdomainDialog"
      title="Delete Subdomain"
      :message="`Are you sure you want to delete '${subdomainToDelete?.domain_name}'? The vhost configuration and DNS record will be removed.`"
      confirm-text="Delete Subdomain"
      :destructive="true"
      @confirm="handleDeleteSubdomain"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDomainsStore } from '@/stores/domains'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import client from '@/api/client'

const route = useRoute()
const router = useRouter()
const store = useDomainsStore()
const auth = useAuthStore()
const notifications = useNotificationsStore()

const phpVersions = ['8.5', '8.4', '8.3', '8.2', '8.1', '8.0', '7.4']

const tabs = [
  { key: 'overview', label: 'Overview' },
  { key: 'subdomains', label: 'Subdomains' },
  { key: 'ssl', label: 'SSL' },
  { key: 'caching', label: 'Caching' },
  { key: 'error-pages', label: 'Error Pages' },
  { key: 'privacy', label: 'Directory Privacy' },
  { key: 'redirects', label: 'Redirects' },
  { key: 'security', label: 'Security' },
  { key: 'git', label: 'Git Deploy' },
  { key: 'logs', label: 'Logs' },
  { key: 'stats', label: 'Stats' }
]

const activeTab = ref(route.query.tab || 'overview')
const domain = computed(() => store.currentDomain)

// Subdomains
const showAddSubdomain = ref(false)
const showDeleteSubdomainDialog = ref(false)
const subdomainToDelete = ref(null)
const subdomainSubmitting = ref(false)
const subdomainForm = ref({
  subdomain_prefix: '',
  php_version: '8.2',
  document_root: '',
  enable_ssl: false,
})
const subdomainFormErrors = ref({})

const subdomainFullName = computed(() => {
  const prefix = subdomainForm.value.subdomain_prefix || 'sub'
  const parent = domain.value?.domain_name || 'example.com'
  return `${prefix}.${parent}`
})

const subdomainDocRoot = computed(() => {
  const prefix = subdomainForm.value.subdomain_prefix || 'sub'
  const parent = domain.value?.domain_name || 'example.com'
  const username = auth.user?.username || 'user'
  return subdomainForm.value.document_root || `/home/${username}/web/${parent}/subdomains/${prefix}/public_html`
})

function validateSubdomainForm() {
  const errors = {}
  const prefix = subdomainForm.value.subdomain_prefix.trim()
  if (!prefix) {
    errors.subdomain_prefix = 'Subdomain prefix is required.'
  } else if (!/^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$/.test(prefix)) {
    errors.subdomain_prefix = 'Only letters, numbers, and hyphens allowed. Must start and end with a letter or number.'
  } else if (prefix.length > 63) {
    errors.subdomain_prefix = 'Prefix must be 63 characters or fewer.'
  }
  subdomainFormErrors.value = errors
  return Object.keys(errors).length === 0
}

async function handleAddSubdomain() {
  if (!validateSubdomainForm()) return
  subdomainSubmitting.value = true
  try {
    const payload = {
      subdomain_prefix: subdomainForm.value.subdomain_prefix.trim().toLowerCase(),
      php_version: subdomainForm.value.php_version,
      enable_ssl: subdomainForm.value.enable_ssl,
    }
    if (subdomainForm.value.document_root.trim()) {
      payload.document_root = subdomainForm.value.document_root.trim()
    }
    await store.createSubdomain(route.params.id, payload)
    notifications.success(`Subdomain '${subdomainFullName.value}' created successfully.`)
    showAddSubdomain.value = false
    subdomainForm.value = { subdomain_prefix: '', php_version: '8.2', document_root: '', enable_ssl: false }
    subdomainFormErrors.value = {}
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to create subdomain.')
  } finally {
    subdomainSubmitting.value = false
  }
}

function confirmDeleteSubdomain(sub) {
  subdomainToDelete.value = sub
  showDeleteSubdomainDialog.value = true
}

async function handleDeleteSubdomain() {
  if (!subdomainToDelete.value) return
  try {
    await store.removeSubdomain(route.params.id, subdomainToDelete.value.id)
    notifications.success(`Subdomain '${subdomainToDelete.value.domain_name}' deleted.`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete subdomain.')
  } finally {
    subdomainToDelete.value = null
  }
}

// SSL
const autoRenew = ref(true)
const issuingSSL = ref(false)
const showUploadCert = ref(false)
const certForm = ref({ certificate: '', private_key: '' })

const sslDaysRemaining = computed(() => {
  if (!domain.value?.ssl_expiry) return 0
  const diff = new Date(domain.value.ssl_expiry) - new Date()
  return Math.max(0, Math.ceil(diff / (1000 * 60 * 60 * 24)))
})

// PHP edit
const showEditPhp = ref(false)
const editPhpVersion = ref('8.2')

// Webserver edit
const showEditWebserver = ref(false)
const editWebserver = ref('nginx')

const webserverLabels = {
  nginx: 'Nginx',
  apache: 'Apache',
  nginx_apache: 'Nginx + Apache',
}
function webserverLabel(val) {
  return webserverLabels[val] || 'Nginx'
}

// Cache
const cacheForm = ref({
  cache_enabled: false,
  cache_type: 'fastcgi',
  cache_ttl: 3600,
  cache_bypass_cookie: 'wordpress_logged_in',
})
const cacheSaving = ref(false)
const cachePurging = ref(false)

// Hotlink Protection
const hotlinkForm = ref({
  hotlink_protection: false,
  hotlink_extensions: 'jpg,jpeg,png,gif,webp,svg,mp4,mp3',
  hotlink_allowed_domains: '',
  hotlink_redirect_url: '',
})
const hotlinkExtensionInput = ref('')
const hotlinkSaving = ref(false)

function hotlinkExtensionsAsArray() {
  const ext = hotlinkForm.value.hotlink_extensions || ''
  return ext.split(',').map(e => e.trim()).filter(Boolean)
}

function removeHotlinkExtension(ext) {
  const exts = hotlinkExtensionsAsArray().filter(e => e !== ext)
  hotlinkForm.value.hotlink_extensions = exts.join(',')
}

function addHotlinkExtension() {
  const val = hotlinkExtensionInput.value.trim().replace(/^\./, '').toLowerCase()
  if (!val) return
  const exts = hotlinkExtensionsAsArray()
  if (!exts.includes(val)) {
    exts.push(val)
    hotlinkForm.value.hotlink_extensions = exts.join(',')
  }
  hotlinkExtensionInput.value = ''
}

function hotlinkAllowedDomainsForDisplay() {
  const raw = hotlinkForm.value.hotlink_allowed_domains || ''
  return raw.replace(/,/g, '\n')
}


// Error Pages
const errorPagesSaving = ref(false)
const errorPageDefinitions = [
  { code: 403, label: 'Forbidden', description: 'Access denied', colorClass: 'bg-warning/10 text-warning' },
  { code: 404, label: 'Not Found', description: 'Page not found', colorClass: 'bg-primary/10 text-primary' },
  { code: 500, label: 'Server Error', description: 'Internal error', colorClass: 'bg-error/10 text-error' },
  { code: 502, label: 'Bad Gateway', description: 'Upstream error', colorClass: 'bg-[#8b5cf6]/10 text-[#8b5cf6]' },
  { code: 503, label: 'Unavailable', description: 'Service down', colorClass: 'bg-[#ec4899]/10 text-[#ec4899]' },
]

const errorPageEntries = ref(errorPageDefinitions.map(def => ({
  ...def,
  mode: 'default',
  value: '',
})))

function initErrorPagesFromDomain(d) {
  if (!d) return
  const saved = d.custom_error_pages || {}
  errorPageEntries.value = errorPageDefinitions.map(def => {
    const savedValue = saved[String(def.code)] || saved[def.code] || ''
    let mode = 'default'
    let value = ''
    if (savedValue) {
      if (savedValue.trim().startsWith('<')) {
        mode = 'html'
        value = savedValue
      } else {
        mode = 'url'
        value = savedValue
      }
    }
    return { ...def, mode, value }
  })
}

async function fetchErrorPages() {
  try {
    const { data } = await client.get(`/domains/${route.params.id}/error-pages`)
    const saved = data.error_pages || {}
    errorPageEntries.value = errorPageDefinitions.map(def => {
      const savedValue = saved[String(def.code)] || saved[def.code] || ''
      let mode = 'default'
      let value = ''
      if (savedValue) {
        if (savedValue.trim().startsWith('<')) {
          mode = 'html'
          value = savedValue
        } else {
          mode = 'url'
          value = savedValue
        }
      }
      return { ...def, mode, value }
    })
  } catch {
    // Keep defaults
  }
}

async function saveErrorPages() {
  errorPagesSaving.value = true
  try {
    const errorPages = {}
    for (const ep of errorPageEntries.value) {
      if (ep.mode !== 'default' && ep.value.trim()) {
        errorPages[ep.code] = ep.value.trim()
      }
    }
    await client.put(`/domains/${route.params.id}/error-pages`, { error_pages: errorPages })
    notifications.success('Error pages saved successfully.')
    await store.fetchOne(route.params.id)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to save error pages.')
  } finally {
    errorPagesSaving.value = false
  }
}

function previewErrorPage(ep) {
  if (!ep.value) return
  const win = window.open('', '_blank')
  if (win) {
    win.document.write(ep.value)
    win.document.close()
  }
}

const errorPageTemplates = {
  403: '<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="UTF-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>403 - Access Forbidden</title>\n    <style>\n        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }\n        body { font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #0f172a; color: #e2e8f0; overflow: hidden; }\n        @media (prefers-color-scheme: light) { body { background: #f1f5f9; color: #1e293b; } .card { background: rgba(255,255,255,0.7); border-color: rgba(0,0,0,0.08); } .card h1 { color: #0f172a; } .card p { color: #64748b; } .code { color: #f59e0b; } }\n        .bg-glow { position: fixed; width: 500px; height: 500px; border-radius: 50%; filter: blur(120px); opacity: 0.15; pointer-events: none; }\n        .bg-glow-1 { top: -150px; left: -100px; background: #f59e0b; }\n        .bg-glow-2 { bottom: -200px; right: -100px; background: #ef4444; }\n        .card { position: relative; text-align: center; padding: 3rem 2.5rem; max-width: 480px; width: 90%; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 1.25rem; backdrop-filter: blur(24px); -webkit-backdrop-filter: blur(24px); box-shadow: 0 25px 50px rgba(0,0,0,0.25); }\n        .code { font-size: 6rem; font-weight: 800; line-height: 1; letter-spacing: -0.04em; color: #fbbf24; margin-bottom: 0.5rem; }\n        .card h1 { font-size: 1.5rem; font-weight: 600; margin-bottom: 0.75rem; }\n        .card p { font-size: 0.95rem; color: #94a3b8; line-height: 1.6; margin-bottom: 2rem; }\n        .btn { display: inline-block; padding: 0.75rem 2rem; background: #f59e0b; color: #fff; border: none; border-radius: 0.625rem; font-size: 0.9rem; font-weight: 500; text-decoration: none; cursor: pointer; transition: background 0.2s, transform 0.15s; }\n        .btn:hover { background: #d97706; transform: translateY(-1px); }\n    </style>\n</head>\n<body>\n    <div class="bg-glow bg-glow-1"></div>\n    <div class="bg-glow bg-glow-2"></div>\n    <div class="card">\n        <div class="code">403</div>\n        <h1>Access Forbidden</h1>\n        <p>You do not have permission to access this resource.</p>\n        <a href="/" class="btn">Back to Home</a>\n    </div>\n</body>\n</html>',
  404: '<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="UTF-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>404 - Page Not Found</title>\n    <style>\n        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }\n        body { font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #0f172a; color: #e2e8f0; overflow: hidden; }\n        @media (prefers-color-scheme: light) { body { background: #f1f5f9; color: #1e293b; } .card { background: rgba(255,255,255,0.7); border-color: rgba(0,0,0,0.08); } .card h1 { color: #0f172a; } .card p { color: #64748b; } .code { color: #6366f1; } }\n        .bg-glow { position: fixed; width: 500px; height: 500px; border-radius: 50%; filter: blur(120px); opacity: 0.15; pointer-events: none; }\n        .bg-glow-1 { top: -150px; left: -100px; background: #6366f1; }\n        .bg-glow-2 { bottom: -200px; right: -100px; background: #ec4899; }\n        .card { position: relative; text-align: center; padding: 3rem 2.5rem; max-width: 480px; width: 90%; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 1.25rem; backdrop-filter: blur(24px); -webkit-backdrop-filter: blur(24px); box-shadow: 0 25px 50px rgba(0,0,0,0.25); }\n        .code { font-size: 6rem; font-weight: 800; line-height: 1; letter-spacing: -0.04em; color: #818cf8; margin-bottom: 0.5rem; }\n        .card h1 { font-size: 1.5rem; font-weight: 600; margin-bottom: 0.75rem; }\n        .card p { font-size: 0.95rem; color: #94a3b8; line-height: 1.6; margin-bottom: 2rem; }\n        .btn { display: inline-block; padding: 0.75rem 2rem; background: #6366f1; color: #fff; border: none; border-radius: 0.625rem; font-size: 0.9rem; font-weight: 500; text-decoration: none; cursor: pointer; transition: background 0.2s, transform 0.15s; }\n        .btn:hover { background: #4f46e5; transform: translateY(-1px); }\n    </style>\n</head>\n<body>\n    <div class="bg-glow bg-glow-1"></div>\n    <div class="bg-glow bg-glow-2"></div>\n    <div class="card">\n        <div class="code">404</div>\n        <h1>Page Not Found</h1>\n        <p>The page you are looking for does not exist or has been moved.</p>\n        <a href="/" class="btn">Back to Home</a>\n    </div>\n</body>\n</html>',
  500: '<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="UTF-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>500 - Server Error</title>\n    <style>\n        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }\n        body { font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #0f172a; color: #e2e8f0; overflow: hidden; }\n        @media (prefers-color-scheme: light) { body { background: #f1f5f9; color: #1e293b; } .card { background: rgba(255,255,255,0.7); border-color: rgba(0,0,0,0.08); } .card h1 { color: #0f172a; } .card p { color: #64748b; } .code { color: #ef4444; } }\n        .bg-glow { position: fixed; width: 500px; height: 500px; border-radius: 50%; filter: blur(120px); opacity: 0.15; pointer-events: none; }\n        .bg-glow-1 { top: -150px; left: -100px; background: #ef4444; }\n        .bg-glow-2 { bottom: -200px; right: -100px; background: #f97316; }\n        .card { position: relative; text-align: center; padding: 3rem 2.5rem; max-width: 480px; width: 90%; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 1.25rem; backdrop-filter: blur(24px); -webkit-backdrop-filter: blur(24px); box-shadow: 0 25px 50px rgba(0,0,0,0.25); }\n        .code { font-size: 6rem; font-weight: 800; line-height: 1; letter-spacing: -0.04em; color: #f87171; margin-bottom: 0.5rem; }\n        .card h1 { font-size: 1.5rem; font-weight: 600; margin-bottom: 0.75rem; }\n        .card p { font-size: 0.95rem; color: #94a3b8; line-height: 1.6; margin-bottom: 2rem; }\n        .btn { display: inline-block; padding: 0.75rem 2rem; background: #ef4444; color: #fff; border: none; border-radius: 0.625rem; font-size: 0.9rem; font-weight: 500; text-decoration: none; cursor: pointer; transition: background 0.2s, transform 0.15s; }\n        .btn:hover { background: #dc2626; transform: translateY(-1px); }\n    </style>\n</head>\n<body>\n    <div class="bg-glow bg-glow-1"></div>\n    <div class="bg-glow bg-glow-2"></div>\n    <div class="card">\n        <div class="code">500</div>\n        <h1>Server Error</h1>\n        <p>Something went wrong on our end. Please try again shortly.</p>\n        <a href="/" class="btn">Back to Home</a>\n    </div>\n</body>\n</html>',
  502: '<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="UTF-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>502 - Bad Gateway</title>\n    <style>\n        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }\n        body { font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #0f172a; color: #e2e8f0; overflow: hidden; }\n        @media (prefers-color-scheme: light) { body { background: #f1f5f9; color: #1e293b; } .card { background: rgba(255,255,255,0.7); border-color: rgba(0,0,0,0.08); } .card h1 { color: #0f172a; } .card p { color: #64748b; } .code { color: #8b5cf6; } }\n        .bg-glow { position: fixed; width: 500px; height: 500px; border-radius: 50%; filter: blur(120px); opacity: 0.15; pointer-events: none; }\n        .bg-glow-1 { top: -150px; left: -100px; background: #8b5cf6; }\n        .bg-glow-2 { bottom: -200px; right: -100px; background: #06b6d4; }\n        .card { position: relative; text-align: center; padding: 3rem 2.5rem; max-width: 480px; width: 90%; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 1.25rem; backdrop-filter: blur(24px); -webkit-backdrop-filter: blur(24px); box-shadow: 0 25px 50px rgba(0,0,0,0.25); }\n        .code { font-size: 6rem; font-weight: 800; line-height: 1; letter-spacing: -0.04em; color: #a78bfa; margin-bottom: 0.5rem; }\n        .card h1 { font-size: 1.5rem; font-weight: 600; margin-bottom: 0.75rem; }\n        .card p { font-size: 0.95rem; color: #94a3b8; line-height: 1.6; margin-bottom: 2rem; }\n        .btn { display: inline-block; padding: 0.75rem 2rem; background: #8b5cf6; color: #fff; border: none; border-radius: 0.625rem; font-size: 0.9rem; font-weight: 500; text-decoration: none; cursor: pointer; transition: background 0.2s, transform 0.15s; }\n        .btn:hover { background: #7c3aed; transform: translateY(-1px); }\n    </style>\n</head>\n<body>\n    <div class="bg-glow bg-glow-1"></div>\n    <div class="bg-glow bg-glow-2"></div>\n    <div class="card">\n        <div class="code">502</div>\n        <h1>Bad Gateway</h1>\n        <p>The server received an invalid response from an upstream server. Please try again in a few moments.</p>\n        <a href="/" class="btn">Back to Home</a>\n    </div>\n</body>\n</html>',
  503: '<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="UTF-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>503 - Service Unavailable</title>\n    <style>\n        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }\n        body { font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #0f172a; color: #e2e8f0; overflow: hidden; }\n        @media (prefers-color-scheme: light) { body { background: #f1f5f9; color: #1e293b; } .card { background: rgba(255,255,255,0.7); border-color: rgba(0,0,0,0.08); } .card h1 { color: #0f172a; } .card p { color: #64748b; } .code { color: #ec4899; } }\n        .bg-glow { position: fixed; width: 500px; height: 500px; border-radius: 50%; filter: blur(120px); opacity: 0.15; pointer-events: none; }\n        .bg-glow-1 { top: -150px; left: -100px; background: #ec4899; }\n        .bg-glow-2 { bottom: -200px; right: -100px; background: #8b5cf6; }\n        .card { position: relative; text-align: center; padding: 3rem 2.5rem; max-width: 480px; width: 90%; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 1.25rem; backdrop-filter: blur(24px); -webkit-backdrop-filter: blur(24px); box-shadow: 0 25px 50px rgba(0,0,0,0.25); }\n        .code { font-size: 6rem; font-weight: 800; line-height: 1; letter-spacing: -0.04em; color: #f472b6; margin-bottom: 0.5rem; }\n        .card h1 { font-size: 1.5rem; font-weight: 600; margin-bottom: 0.75rem; }\n        .card p { font-size: 0.95rem; color: #94a3b8; line-height: 1.6; margin-bottom: 2rem; }\n        .btn { display: inline-block; padding: 0.75rem 2rem; background: #ec4899; color: #fff; border: none; border-radius: 0.625rem; font-size: 0.9rem; font-weight: 500; text-decoration: none; cursor: pointer; transition: background 0.2s, transform 0.15s; }\n        .btn:hover { background: #db2777; transform: translateY(-1px); }\n    </style>\n</head>\n<body>\n    <div class="bg-glow bg-glow-1"></div>\n    <div class="bg-glow bg-glow-2"></div>\n    <div class="card">\n        <div class="code">503</div>\n        <h1>Service Unavailable</h1>\n        <p>The server is temporarily unable to handle your request. Please try again later.</p>\n        <a href="/" class="btn">Back to Home</a>\n    </div>\n</body>\n</html>',
}

function useErrorTemplate(ep) {
  const tpl = errorPageTemplates[ep.code]
  if (tpl) {
    ep.value = tpl
    notifications.success(`Template loaded for ${ep.code} error page.`)
  } else {
    notifications.error(`No template available for ${ep.code}.`)
  }
}


// Redirects
const redirects = ref([])
const redirectsLoading = ref(false)
const showRedirectModal = ref(false)
const showDeleteRedirect = ref(false)
const redirectSaving = ref(false)
const editingRedirect = ref(null)
const deletingRedirect = ref(null)
const redirectForm = ref({
  source_path: '',
  destination_url: '',
  redirect_type: 301,
  is_regex: false,
})

async function fetchRedirects() {
  redirectsLoading.value = true
  try {
    const { data } = await client.get(`/domains/${route.params.id}/redirects`)
    redirects.value = data.items || []
  } catch {
    redirects.value = []
  } finally {
    redirectsLoading.value = false
  }
}

function openAddRedirect() {
  editingRedirect.value = null
  redirectForm.value = {
    source_path: '',
    destination_url: '',
    redirect_type: 301,
    is_regex: false,
  }
  showRedirectModal.value = true
}

function openEditRedirect(r) {
  editingRedirect.value = r
  redirectForm.value = {
    source_path: r.source_path,
    destination_url: r.destination_url,
    redirect_type: r.redirect_type,
    is_regex: r.is_regex,
  }
  showRedirectModal.value = true
}

async function saveRedirect() {
  redirectSaving.value = true
  try {
    if (editingRedirect.value) {
      await client.put(
        `/domains/${route.params.id}/redirects/${editingRedirect.value.id}`,
        redirectForm.value
      )
      notifications.success('Redirect updated successfully.')
    } else {
      await client.post(`/domains/${route.params.id}/redirects`, redirectForm.value)
      notifications.success('Redirect created successfully.')
    }
    showRedirectModal.value = false
    await fetchRedirects()
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to save redirect.')
  } finally {
    redirectSaving.value = false
  }
}

async function toggleRedirectField(r, field) {
  try {
    await client.put(`/domains/${route.params.id}/redirects/${r.id}`, {
      [field]: !r[field],
    })
    r[field] = !r[field]
    notifications.success(`Redirect ${field === 'is_active' ? (r[field] ? 'activated' : 'deactivated') : 'updated'}.`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to update redirect.')
  }
}

function confirmDeleteRedirect(r) {
  deletingRedirect.value = r
  showDeleteRedirect.value = true
}

async function deleteRedirect() {
  if (!deletingRedirect.value) return
  try {
    await client.delete(`/domains/${route.params.id}/redirects/${deletingRedirect.value.id}`)
    notifications.success('Redirect deleted.')
    deletingRedirect.value = null
    await fetchRedirects()
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete redirect.')
  }
}

function setHotlinkAllowedDomains(text) {
  hotlinkForm.value.hotlink_allowed_domains = text.split('\n').map(d => d.trim()).filter(Boolean).join(',')
}

async function saveHotlinkSettings() {
  hotlinkSaving.value = true
  try {
    await client.put(`/domains/${route.params.id}/hotlink`, {
      hotlink_protection: hotlinkForm.value.hotlink_protection,
      hotlink_extensions: hotlinkForm.value.hotlink_extensions || null,
      hotlink_allowed_domains: hotlinkForm.value.hotlink_allowed_domains || null,
      hotlink_redirect_url: hotlinkForm.value.hotlink_redirect_url || null,
    })
    notifications.success('Hotlink protection settings saved.')
    await store.fetchOne(route.params.id)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to save hotlink settings.')
  } finally {
    hotlinkSaving.value = false
  }
}

function cacheTypeLabel(val) {
  const labels = { fastcgi: 'FastCGI', proxy: 'Proxy', none: 'None' }
  return labels[val] || 'FastCGI'
}

function formatTTL(seconds) {
  if (!seconds && seconds !== 0) return '--'
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)}h`
  if (seconds >= 60) return `${Math.round(seconds / 60)}m`
  return `${seconds}s`
}

async function saveCacheSettings() {
  cacheSaving.value = true
  try {
    await client.put(`/domains/${route.params.id}/cache`, cacheForm.value)
    notifications.success('Cache settings saved successfully.')
    await store.fetchOne(route.params.id)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to save cache settings.')
  } finally {
    cacheSaving.value = false
  }
}

async function purgeCache() {
  cachePurging.value = true
  try {
    await client.post(`/domains/${route.params.id}/cache/purge`)
    notifications.success('Cache purged successfully.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to purge cache.')
  } finally {
    cachePurging.value = false
  }
}

// Git Deploy
const gitDeploy = ref(null)
const gitForm = ref({
  repo_url: '',
  branch: 'main',
  auto_deploy: true,
  build_command: '',
  post_deploy_hook: '',
})
const gitEditForm = ref({
  repo_url: '',
  branch: 'main',
  auto_deploy: true,
  build_command: '',
  post_deploy_hook: '',
})
const gitSetupLoading = ref(false)
const gitDeploying = ref(false)
const gitDeployOutput = ref('')
const gitLogs = ref([])
const gitLogsLoading = ref(false)
const expandedLog = ref(null)
const showGitSettings = ref(false)
const showRemoveGit = ref(false)
const gitSettingsSaving = ref(false)

async function fetchGitStatus() {
  try {
    const { data } = await client.get(`/domains/${route.params.id}/git/status`)
    gitDeploy.value = data
  } catch {
    gitDeploy.value = null
  }
}

async function fetchGitLogs() {
  gitLogsLoading.value = true
  try {
    const { data } = await client.get(`/domains/${route.params.id}/git/logs`)
    gitLogs.value = data.items || []
  } catch {
    gitLogs.value = []
  } finally {
    gitLogsLoading.value = false
  }
}

async function setupGitDeploy() {
  gitSetupLoading.value = true
  try {
    const payload = { ...gitForm.value }
    if (!payload.build_command) delete payload.build_command
    if (!payload.post_deploy_hook) delete payload.post_deploy_hook
    const { data } = await client.post(`/domains/${route.params.id}/git/setup`, payload)
    gitDeploy.value = data
    notifications.success('Git deployment configured. Add the deploy key to your repository.')
    fetchGitLogs()
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to set up git deployment.')
  } finally {
    gitSetupLoading.value = false
  }
}

async function triggerGitDeploy() {
  gitDeploying.value = true
  gitDeployOutput.value = ''
  try {
    const { data } = await client.post(`/domains/${route.params.id}/git/deploy`)
    gitDeployOutput.value = data.output || ''
    if (data.success) {
      notifications.success('Deployment completed successfully.')
    } else {
      notifications.error('Deployment failed. Check the output below.')
    }
    await fetchGitStatus()
    await fetchGitLogs()
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to trigger deployment.')
  } finally {
    gitDeploying.value = false
  }
}

async function saveGitSettings() {
  gitSettingsSaving.value = true
  try {
    const payload = {}
    if (gitEditForm.value.repo_url !== gitDeploy.value?.repo_url) payload.repo_url = gitEditForm.value.repo_url
    if (gitEditForm.value.branch !== gitDeploy.value?.branch) payload.branch = gitEditForm.value.branch
    if (gitEditForm.value.auto_deploy !== gitDeploy.value?.auto_deploy) payload.auto_deploy = gitEditForm.value.auto_deploy
    payload.build_command = gitEditForm.value.build_command || null
    payload.post_deploy_hook = gitEditForm.value.post_deploy_hook || null
    await client.put(`/domains/${route.params.id}/git/update`, payload)
    notifications.success('Git deploy settings updated.')
    showGitSettings.value = false
    await fetchGitStatus()
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to update settings.')
  } finally {
    gitSettingsSaving.value = false
  }
}

async function removeGitDeploy() {
  try {
    await client.delete(`/domains/${route.params.id}/git/remove`)
    gitDeploy.value = null
    gitLogs.value = []
    gitDeployOutput.value = ''
    notifications.success('Git deployment removed.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to remove git deployment.')
  }
}

function copyToClipboard(text, message) {
  navigator.clipboard.writeText(text).then(() => {
    notifications.success(message || 'Copied to clipboard.')
  }).catch(() => {
    notifications.error('Failed to copy to clipboard.')
  })
}

// Directory Privacy
const dpRules = ref([])
const dpLoading = ref(false)
const dpExpandedRule = ref(null)
const dpCreating = ref(false)
const dpAddingUser = ref(false)
const showProtectDirModal = ref(false)
const showAddUserModal = ref(false)
const showDeleteDpDialog = ref(false)
const dpDeleteTarget = ref(null)
const dpCurrentRule = ref(null)
const dpForm = ref({ path: '', auth_name: 'Restricted Area' })
const dpUserForm = ref({ username: '', password: '' })

async function fetchDpRules() {
  dpLoading.value = true
  try {
    const { data } = await client.get(`/domains/${route.params.id}/directory-privacy`)
    dpRules.value = data.items || []
  } catch {
    dpRules.value = []
  } finally {
    dpLoading.value = false
  }
}

async function createDpRule() {
  dpCreating.value = true
  try {
    await client.post(`/domains/${route.params.id}/directory-privacy`, dpForm.value)
    notifications.success(`Directory ${dpForm.value.path} is now protected.`)
    showProtectDirModal.value = false
    dpForm.value = { path: '', auth_name: 'Restricted Area' }
    await fetchDpRules()
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to protect directory.')
  } finally {
    dpCreating.value = false
  }
}

async function toggleDpActive(rule) {
  try {
    const { data } = await client.put(`/domains/${route.params.id}/directory-privacy/${rule.id}`, {
      is_active: !rule.is_active,
    })
    const idx = dpRules.value.findIndex(r => r.id === rule.id)
    if (idx !== -1) dpRules.value[idx] = data
    notifications.success(`Protection ${data.is_active ? 'enabled' : 'disabled'} for ${rule.path}.`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to toggle protection.')
  }
}

function confirmDeleteDp(rule) {
  dpDeleteTarget.value = rule
  showDeleteDpDialog.value = true
}

async function deleteDpRule() {
  if (!dpDeleteTarget.value) return
  try {
    await client.delete(`/domains/${route.params.id}/directory-privacy/${dpDeleteTarget.value.id}`)
    notifications.success(`Protection removed from ${dpDeleteTarget.value.path}.`)
    dpDeleteTarget.value = null
    await fetchDpRules()
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to remove protection.')
  }
}

function openAddUserModal(rule) {
  dpCurrentRule.value = rule
  dpUserForm.value = { username: '', password: '' }
  showAddUserModal.value = true
}

async function addDpUser() {
  if (!dpCurrentRule.value) return
  dpAddingUser.value = true
  try {
    const { data } = await client.post(
      `/domains/${route.params.id}/directory-privacy/${dpCurrentRule.value.id}/users`,
      dpUserForm.value
    )
    const idx = dpRules.value.findIndex(r => r.id === dpCurrentRule.value.id)
    if (idx !== -1) dpRules.value[idx] = data
    notifications.success(`User ${dpUserForm.value.username} added.`)
    showAddUserModal.value = false
    dpUserForm.value = { username: '', password: '' }
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to add user.')
  } finally {
    dpAddingUser.value = false
  }
}

async function removeDpUser(rule, username) {
  try {
    const { data } = await client.delete(
      `/domains/${route.params.id}/directory-privacy/${rule.id}/users/${username}`
    )
    const idx = dpRules.value.findIndex(r => r.id === rule.id)
    if (idx !== -1) dpRules.value[idx] = data
    notifications.success(`User ${username} removed.`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to remove user.')
  }
}

// Logs
const logType = ref('access')
const logLines = ref([])
const logsLoading = ref(false)
const logContainer = ref(null)

// Stats
const bandwidthData = ref([])
const requestsData = ref([])
const statsLoading = ref(false)

// Delete
const showDeleteDialog = ref(false)

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return '--'
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

function formatDate(dateStr) {
  if (!dateStr) return '--'
  return new Date(dateStr).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
}

function formatShortDate(dateStr) {
  if (!dateStr) return '--'
  return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function bandwidthPercent(bytes) {
  const max = Math.max(...bandwidthData.value.map(d => d.bytes), 1)
  return Math.round((bytes / max) * 100)
}

function requestsPercent(count) {
  const max = Math.max(...requestsData.value.map(d => d.count), 1)
  return Math.round((count / max) * 100)
}

async function fetchLogs() {
  logsLoading.value = true
  try {
    const { data } = await client.get(`/domains/${route.params.id}/logs`, {
      params: { type: logType.value, lines: 100 }
    })
    logLines.value = data.lines || []
    await nextTick()
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  } catch {
    logLines.value = []
  } finally {
    logsLoading.value = false
  }
}

async function fetchStats() {
  statsLoading.value = true
  try {
    const { data } = await client.get(`/domains/${route.params.id}/stats`)
    bandwidthData.value = data.bandwidth || []
    requestsData.value = data.requests || []
  } catch {
    bandwidthData.value = []
    requestsData.value = []
  } finally {
    statsLoading.value = false
  }
}

async function issueSSL() {
  issuingSSL.value = true
  try {
    await client.post(`/ssl/issue/${route.params.id}`)
    notifications.success('SSL certificate issued successfully.')
    await store.fetchOne(route.params.id)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to issue SSL certificate.')
  } finally {
    issuingSSL.value = false
  }
}

async function uploadCert() {
  try {
    await client.post(`/ssl/install/${route.params.id}`, certForm.value)
    notifications.success('Certificate uploaded successfully.')
    showUploadCert.value = false
    certForm.value = { certificate: '', private_key: '' }
    await store.fetchOne(route.params.id)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to upload certificate.')
  }
}

function toggleAutoRenew() {
  autoRenew.value = !autoRenew.value
  client.put(`/ssl/auto-renew/${route.params.id}`, { enabled: autoRenew.value })
    .then(() => notifications.success(`Auto-renew ${autoRenew.value ? 'enabled' : 'disabled'}.`))
    .catch(() => {
      autoRenew.value = !autoRenew.value
      notifications.error('Failed to update auto-renew setting.')
    })
}

function updatePhp() {
  store.update(route.params.id, { php_version: editPhpVersion.value })
    .then(() => {
      notifications.success(`PHP version changed to ${editPhpVersion.value}.`)
      showEditPhp.value = false
      store.fetchOne(route.params.id)
    })
    .catch(err => notifications.error(err.response?.data?.detail || 'Failed to update PHP version.'))
}

function updateWebserver() {
  store.update(route.params.id, { webserver: editWebserver.value })
    .then(() => {
      notifications.success(`Web server changed to ${webserverLabel(editWebserver.value)}.`)
      showEditWebserver.value = false
      store.fetchOne(route.params.id)
    })
    .catch(err => notifications.error(err.response?.data?.detail || 'Failed to change web server.'))
}

async function handleDelete() {
  try {
    await store.remove(route.params.id)
    notifications.success('Domain deleted.')
    router.push({ name: 'domains' })
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete domain.')
  }
}

// Tab watchers
watch(activeTab, (tab) => {
  if (tab === 'logs') fetchLogs()
  if (tab === 'stats') fetchStats()
  if (tab === 'redirects') fetchRedirects()
  if (tab === 'error-pages') fetchErrorPages()
  if (tab === 'privacy') fetchDpRules()
  if (tab === 'subdomains') store.fetchSubdomains(route.params.id)
  if (tab === 'git') {
    fetchGitStatus()
    fetchGitLogs()
  }
})

watch(logType, () => {
  if (activeTab.value === 'logs') fetchLogs()
})

watch(showGitSettings, (open) => {
  if (open && gitDeploy.value) {
    gitEditForm.value = {
      repo_url: gitDeploy.value.repo_url || '',
      branch: gitDeploy.value.branch || 'main',
      auto_deploy: gitDeploy.value.auto_deploy ?? true,
      build_command: gitDeploy.value.build_command || '',
      post_deploy_hook: gitDeploy.value.post_deploy_hook || '',
    }
  }
})

watch(() => domain.value, (d) => {
  if (d) {
    editPhpVersion.value = d.php_version
    editWebserver.value = d.webserver || 'nginx'
    autoRenew.value = d.ssl_auto_renew !== false
    cacheForm.value = {
      cache_enabled: d.cache_enabled || false,
      cache_type: d.cache_type || 'fastcgi',
      cache_ttl: d.cache_ttl ?? 3600,
      cache_bypass_cookie: d.cache_bypass_cookie || 'wordpress_logged_in',
    }
    hotlinkForm.value = {
      hotlink_protection: d.hotlink_protection || false,
      hotlink_extensions: d.hotlink_extensions || 'jpg,jpeg,png,gif,webp,svg,mp4,mp3',
      hotlink_allowed_domains: d.hotlink_allowed_domains || '',
      hotlink_redirect_url: d.hotlink_redirect_url || '',
    }
    initErrorPagesFromDomain(d)
  }
})

// Reset subdomain form when modal closes
watch(showAddSubdomain, (val) => {
  if (!val) {
    subdomainForm.value = { subdomain_prefix: '', php_version: '8.2', document_root: '', enable_ssl: false }
    subdomainFormErrors.value = {}
  }
})

onMounted(async () => {
  await store.fetchOne(route.params.id)
  if (activeTab.value === 'logs') fetchLogs()
  if (activeTab.value === 'stats') fetchStats()
  if (activeTab.value === 'redirects') fetchRedirects()
  if (activeTab.value === 'error-pages') fetchErrorPages()
  if (activeTab.value === 'privacy') fetchDpRules()
  if (activeTab.value === 'subdomains') store.fetchSubdomains(route.params.id)
  if (activeTab.value === 'git') {
    fetchGitStatus()
    fetchGitLogs()
  }
})
</script>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
