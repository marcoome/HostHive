<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <h1 class="text-2xl font-semibold text-[var(--text-primary)]">Email</h1>
      <button
        v-if="activeTab === 'mailboxes' || activeTab === 'aliases' || activeTab === 'mailing-lists'"
        class="btn-primary inline-flex items-center gap-2"
        @click="activeTab === 'aliases' ? openAddAlias() : activeTab === 'mailing-lists' ? openCreateList() : openAddMailbox()"
      >
        <span class="text-lg leading-none">+</span>
        {{ activeTab === 'aliases' ? 'Add Alias' : activeTab === 'mailing-lists' ? 'Create List' : 'Add Mailbox' }}
      </button>
    </div>

    <!-- Tabs -->
    <div class="flex border-b border-[var(--border)] overflow-x-auto">
      <button
        v-for="tab in visibleTabs"
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

    <!-- Search (mailboxes / aliases / filters) -->
    <div v-if="activeTab !== 'queue' && activeTab !== 'catch-all' && activeTab !== 'filters' && activeTab !== 'deliverability' && activeTab !== 'mailing-lists'" class="glass rounded-2xl p-6">
      <div class="relative">
        <span class="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]">&#128269;</span>
        <input
          v-model="search"
          type="text"
          :placeholder="activeTab === 'mailboxes' ? 'Search mailboxes...' : 'Search aliases...'"
          class="w-full pl-10 pr-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
        />
      </div>
    </div>

    <!-- Mailboxes Tab -->
    <Transition name="fade" mode="out-in">
      <div v-if="activeTab === 'mailboxes'" key="mailboxes" class="glass rounded-2xl p-0 overflow-hidden">
        <DataTable
          :columns="mailboxColumns"
          :rows="filteredMailboxes"
          :loading="emailStore.loading"
          empty-text="No mailboxes yet. Create your first email account."
        >
          <template #cell-address="{ row }">
            <span class="font-medium text-[var(--text-primary)]">{{ row.address }}</span>
          </template>

          <template #cell-domain="{ value }">
            <span class="text-sm text-[var(--text-muted)]">{{ value }}</span>
          </template>

          <template #cell-quota="{ row }">
            <div class="flex items-center gap-3 min-w-[180px]">
              <div class="flex-1 bg-[var(--background)] rounded-full h-2 overflow-hidden">
                <div
                  class="h-full rounded-full transition-all duration-500"
                  :class="quotaBarColor(row)"
                  :style="{ width: quotaPercent(row) + '%' }"
                />
              </div>
              <span class="text-xs whitespace-nowrap" :class="quotaPercent(row) > 90 ? 'text-error font-semibold' : quotaPercent(row) > 70 ? 'text-warning' : 'text-[var(--text-muted)]'">
                {{ (row.quota_used_mb || 0).toFixed(1) }} / {{ row.quota_mb }} MB
              </span>
            </div>
          </template>

          <template #cell-status="{ row }">
            <StatusBadge
              :status="row.status || 'active'"
              :label="row.status || 'active'"
            />
          </template>

          <template #actions="{ row }">
            <div class="flex items-center justify-end gap-1 flex-wrap">
              <button
                class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] text-primary hover:text-primary whitespace-nowrap"
                :disabled="ssoLoading === row.id"
                @click="openWebmail(row)"
              >
                <span v-if="ssoLoading === row.id" class="inline-block w-3 h-3 border-2 border-primary/30 border-t-primary rounded-full animate-spin mr-1"></span>
                Open Webmail
              </button>
              <button
                class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] whitespace-nowrap"
                :class="row.autoresponder_enabled ? 'text-warning' : ''"
                @click="openAutoresponder(row)"
              >
                Autoresponder{{ row.autoresponder_enabled ? ' (On)' : '' }}
              </button>
              <button class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] whitespace-nowrap" @click="openFilters(row)">
                Filters
              </button>
              <button
                class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] whitespace-nowrap"
                :class="row.spam_filter_enabled === false ? 'text-[var(--text-muted)]' : ''"
                @click="openSpamFilter(row)"
              >
                Spam Filter
              </button>
              <button class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] whitespace-nowrap" @click="openChangePassword(row)">
                Password
              </button>
              <button class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] whitespace-nowrap" @click="editMailbox(row)">
                Edit
              </button>
              <button class="btn-ghost text-xs px-2 py-1.5 min-h-[36px] text-error hover:text-error whitespace-nowrap" @click="confirmDeleteMailbox(row)">
                Delete
              </button>
            </div>
          </template>
        </DataTable>
      </div>

      <!-- Aliases Tab -->
      <div v-else-if="activeTab === 'aliases'" key="aliases" class="glass rounded-2xl p-0 overflow-hidden">
        <DataTable
          :columns="aliasColumns"
          :rows="filteredAliases"
          :loading="emailStore.loading"
          empty-text="No email aliases yet."
        >
          <template #cell-from_address="{ row }">
            <span class="font-mono text-sm text-[var(--text-primary)]">{{ row.source || row.from_address }}</span>
          </template>

          <template #cell-to_address="{ row }">
            <div class="flex flex-col gap-0.5">
              <span
                v-for="(d, i) in (row.destinations && row.destinations.length ? row.destinations : [row.destination || row.to_address])"
                :key="i"
                class="font-mono text-sm text-[var(--text-muted)]"
              >{{ d }}</span>
              <span v-if="row.keep_local_copy" class="text-xs text-primary">(+ local copy)</span>
            </div>
          </template>

          <template #actions="{ row }">
            <div class="flex items-center justify-end gap-1 flex-wrap">
              <button class="btn-ghost text-xs px-3 py-1.5 min-h-[36px]" @click="editAlias(row)">
                Edit
              </button>
              <button class="btn-ghost text-xs px-3 py-1.5 min-h-[36px] text-error hover:text-error" @click="confirmDeleteAlias(row)">
                Delete
              </button>
            </div>
          </template>
        </DataTable>
      </div>

      <!-- Mailing Lists Tab -->
      <div v-else-if="activeTab === 'mailing-lists'" key="mailing-lists" class="space-y-4">
        <div v-if="emailStore.loading" class="glass rounded-2xl p-6">
          <div class="skeleton h-6 w-48 rounded mb-4"></div>
          <div class="skeleton h-10 w-full rounded"></div>
        </div>

        <!-- List Detail View -->
        <div v-else-if="mlDetailView" class="space-y-4">
          <button class="btn-ghost text-sm inline-flex items-center gap-1" @click="mlDetailView = null">
            <span>&larr;</span> Back to Lists
          </button>

          <div class="glass rounded-2xl p-6">
            <div class="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
              <div>
                <h2 class="text-lg font-semibold text-[var(--text-primary)]">{{ mlDetailView.name }}</h2>
                <p class="text-sm text-[var(--text-muted)] font-mono mt-1">{{ mlDetailView.list_address }}</p>
                <p v-if="mlDetailView.description" class="text-sm text-[var(--text-muted)] mt-2">{{ mlDetailView.description }}</p>
              </div>
              <div class="flex items-center gap-2 flex-shrink-0">
                <button class="btn-ghost text-xs px-3 py-1.5" @click="mlShowSettings = !mlShowSettings">
                  Settings
                </button>
                <button class="btn-primary text-xs px-3 py-1.5" @click="mlShowAddMembers = true">
                  Add Members
                </button>
              </div>
            </div>

            <!-- Expandable Settings Section -->
            <div v-if="mlShowSettings" class="mt-4 pt-4 border-t border-[var(--border)] space-y-4">
              <h3 class="text-sm font-semibold text-[var(--text-primary)]">List Settings</h3>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label class="block text-xs font-medium text-[var(--text-muted)] mb-1">Description</label>
                  <input
                    v-model="mlSettingsForm.description"
                    type="text"
                    class="w-full px-3 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
                <div>
                  <label class="block text-xs font-medium text-[var(--text-muted)] mb-1">Owner Email</label>
                  <input
                    v-model="mlSettingsForm.owner_email"
                    type="email"
                    class="w-full px-3 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
                <div>
                  <label class="block text-xs font-medium text-[var(--text-muted)] mb-1">Max Message Size (KB)</label>
                  <input
                    v-model.number="mlSettingsForm.max_message_size_kb"
                    type="number"
                    min="1"
                    max="102400"
                    class="w-full px-3 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
              </div>
              <div class="flex flex-wrap gap-6">
                <label class="flex items-center gap-2 text-sm text-[var(--text-primary)] cursor-pointer">
                  <button
                    type="button"
                    role="switch"
                    :aria-checked="mlSettingsForm.is_moderated"
                    class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors"
                    :class="mlSettingsForm.is_moderated ? 'bg-primary' : 'bg-[var(--border)]'"
                    @click="mlSettingsForm.is_moderated = !mlSettingsForm.is_moderated"
                  >
                    <span class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition" :class="mlSettingsForm.is_moderated ? 'translate-x-4' : 'translate-x-0'" />
                  </button>
                  Moderated
                </label>
                <label class="flex items-center gap-2 text-sm text-[var(--text-primary)] cursor-pointer">
                  <button
                    type="button"
                    role="switch"
                    :aria-checked="mlSettingsForm.archive_enabled"
                    class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors"
                    :class="mlSettingsForm.archive_enabled ? 'bg-primary' : 'bg-[var(--border)]'"
                    @click="mlSettingsForm.archive_enabled = !mlSettingsForm.archive_enabled"
                  >
                    <span class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition" :class="mlSettingsForm.archive_enabled ? 'translate-x-4' : 'translate-x-0'" />
                  </button>
                  Archive
                </label>
                <label class="flex items-center gap-2 text-sm text-[var(--text-primary)] cursor-pointer">
                  <button
                    type="button"
                    role="switch"
                    :aria-checked="mlSettingsForm.reply_to_list"
                    class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors"
                    :class="mlSettingsForm.reply_to_list ? 'bg-primary' : 'bg-[var(--border)]'"
                    @click="mlSettingsForm.reply_to_list = !mlSettingsForm.reply_to_list"
                  >
                    <span class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition" :class="mlSettingsForm.reply_to_list ? 'translate-x-4' : 'translate-x-0'" />
                  </button>
                  Reply-To List
                </label>
              </div>
              <div class="flex justify-end">
                <button class="btn-primary text-xs px-4 py-2" :disabled="mlSettingsSaving" @click="handleSaveListSettings">
                  <span v-if="mlSettingsSaving" class="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin mr-1"></span>
                  Save Settings
                </button>
              </div>
            </div>
          </div>

          <!-- Members Table -->
          <div class="glass rounded-2xl p-0 overflow-hidden">
            <DataTable
              :columns="mlMemberColumns"
              :rows="mlDetailView.members || []"
              :loading="false"
              empty-text="No members yet. Add members to this mailing list."
            >
              <template #cell-email="{ row }">
                <span class="font-mono text-sm text-[var(--text-primary)]">{{ row.email }}</span>
              </template>

              <template #cell-name="{ row }">
                <span class="text-sm text-[var(--text-muted)]">{{ row.name || '--' }}</span>
              </template>

              <template #cell-role="{ row }">
                <span
                  v-if="row.is_admin"
                  class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-primary/10 text-primary"
                >
                  Admin
                </span>
                <span v-else class="text-xs text-[var(--text-muted)]">Member</span>
              </template>

              <template #cell-subscribed_at="{ row }">
                <span class="text-xs text-[var(--text-muted)]">{{ formatTimeAgo(row.subscribed_at) }}</span>
              </template>

              <template #actions="{ row }">
                <button class="btn-ghost text-xs px-2 py-1 text-error hover:text-error" @click="confirmRemoveMember(row)">
                  Remove
                </button>
              </template>
            </DataTable>
          </div>
        </div>

        <!-- Lists Overview -->
        <template v-else>
          <div v-if="emailStore.mailingLists.length === 0 && !emailStore.loading" class="glass rounded-2xl p-12 text-center">
            <p class="text-[var(--text-muted)] text-sm">No mailing lists yet. Create your first mailing list.</p>
          </div>
          <div v-else class="space-y-3">
            <div
              v-for="ml in emailStore.mailingLists"
              :key="ml.id"
              class="glass rounded-2xl p-5 cursor-pointer hover:border-primary/30 transition-colors"
              @click="openListDetail(ml)"
            >
              <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2">
                    <h3 class="text-sm font-semibold text-[var(--text-primary)] truncate">{{ ml.name }}</h3>
                    <span
                      class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                      :class="ml.is_active ? 'bg-green-500/10 text-green-400' : 'bg-[var(--border)] text-[var(--text-muted)]'"
                    >
                      {{ ml.is_active ? 'Active' : 'Inactive' }}
                    </span>
                    <span v-if="ml.is_moderated" class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-warning/10 text-warning">
                      Moderated
                    </span>
                  </div>
                  <p class="text-xs text-[var(--text-muted)] font-mono mt-0.5">{{ ml.list_address }}</p>
                  <p v-if="ml.description" class="text-xs text-[var(--text-muted)] mt-1 truncate">{{ ml.description }}</p>
                </div>
                <div class="flex items-center gap-4 flex-shrink-0">
                  <div class="text-center">
                    <span class="text-lg font-semibold text-[var(--text-primary)]">{{ ml.member_count || 0 }}</span>
                    <p class="text-xs text-[var(--text-muted)]">members</p>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    :aria-checked="ml.is_active"
                    class="relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors"
                    :class="ml.is_active ? 'bg-primary' : 'bg-[var(--border)]'"
                    @click.stop="toggleListActive(ml)"
                  >
                    <span
                      class="pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition"
                      :class="ml.is_active ? 'translate-x-5' : 'translate-x-0'"
                    />
                  </button>
                  <button class="btn-ghost text-xs px-2 py-1 text-error hover:text-error" @click.stop="confirmDeleteList(ml)">
                    Delete
                  </button>
                </div>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- Catch-All Tab -->
      <div v-else-if="activeTab === 'catch-all'" key="catch-all" class="space-y-4">
        <div v-if="catchAllLoading" class="glass rounded-2xl p-6">
          <div class="skeleton h-6 w-48 rounded mb-4"></div>
          <div class="skeleton h-10 w-full rounded"></div>
        </div>
        <div v-else-if="catchAllDomains.length === 0" class="glass rounded-2xl p-12 text-center">
          <p class="text-[var(--text-muted)] text-sm">No domains available. Add a domain first to configure catch-all email.</p>
        </div>
        <div v-else class="space-y-4">
          <div
            v-for="d in catchAllDomains"
            :key="d.name"
            class="glass rounded-2xl p-5"
          >
            <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div>
                <h3 class="text-sm font-semibold text-[var(--text-primary)]">{{ d.name }}</h3>
                <p class="text-xs text-[var(--text-muted)] mt-0.5">
                  {{ d.catch_all_address ? 'Catch-all active: *@' + d.name + ' -> ' + d.catch_all_address : 'Catch-all disabled' }}
                </p>
              </div>
              <div class="flex items-center gap-2">
                <button
                  type="button"
                  role="switch"
                  :aria-checked="!!d.catch_all_address"
                  class="relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-primary/50"
                  :class="d.catch_all_address ? 'bg-primary' : 'bg-[var(--border)]'"
                  @click="toggleCatchAll(d)"
                >
                  <span
                    class="pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
                    :class="d.catch_all_address ? 'translate-x-5' : 'translate-x-0'"
                  />
                </button>
              </div>
            </div>

            <div v-if="d.catch_all_address || d._editing" class="mt-3 flex gap-2">
              <input
                v-model="d._catchAllInput"
                type="email"
                :placeholder="'catchall@' + d.name"
                class="flex-1 px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
              />
              <button
                class="btn-primary text-xs px-4"
                :disabled="!d._catchAllInput?.trim()"
                @click="saveCatchAll(d)"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Filters Tab -->
      <div v-else-if="activeTab === 'filters'" key="filters" class="space-y-4">
        <div v-if="emailStore.loading" class="glass rounded-2xl p-6">
          <div class="skeleton h-6 w-48 rounded mb-4"></div>
          <div class="skeleton h-10 w-full rounded"></div>
        </div>
        <div v-else-if="emailStore.mailboxes.length === 0" class="glass rounded-2xl p-12 text-center">
          <p class="text-[var(--text-muted)] text-sm">No mailboxes. Create an email account first to manage filters.</p>
        </div>
        <div v-else class="space-y-3">
          <p class="text-sm text-[var(--text-muted)]">Configure Sieve mail filters per mailbox. Filters automatically sort, forward, or discard incoming messages.</p>
          <div
            v-for="mb in emailStore.mailboxes"
            :key="mb.id"
            class="glass rounded-2xl p-4 flex items-center justify-between"
          >
            <div>
              <span class="font-medium text-[var(--text-primary)]">{{ mb.address }}</span>
            </div>
            <button class="btn-primary text-xs px-4 py-2" @click="openFilters(mb)">
              Manage Filters
            </button>
          </div>
        </div>
      </div>

      <!-- Deliverability Tab -->
      <div v-else-if="activeTab === 'deliverability'" key="deliverability" class="space-y-6">
        <!-- Domain Selector & Run Test -->
        <div class="glass rounded-2xl p-6">
          <div class="flex flex-col sm:flex-row gap-4 items-end">
            <div class="flex-1">
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Domain</label>
              <select
                v-model="deliverabilityDomain"
                class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
              >
                <option value="" disabled>Select a domain...</option>
                <option v-for="d in availableDomains" :key="d" :value="d">{{ d }}</option>
              </select>
            </div>
            <button
              class="btn-primary inline-flex items-center gap-2 px-6 py-2 whitespace-nowrap"
              :disabled="deliverabilityLoading || !deliverabilityDomain"
              @click="runDeliverabilityTest"
            >
              <span v-if="deliverabilityLoading" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
              <span v-if="!deliverabilityLoading">Run Test</span>
            </button>
          </div>
        </div>

        <!-- Loading -->
        <div v-if="deliverabilityLoading" class="glass rounded-2xl p-12 text-center">
          <div class="inline-block w-10 h-10 border-3 border-primary/30 border-t-primary rounded-full animate-spin mb-4"></div>
          <p class="text-sm text-[var(--text-muted)]">Running deliverability checks...</p>
        </div>

        <!-- Results -->
        <template v-if="deliverabilityReport && !deliverabilityLoading">
          <!-- Score Gauge -->
          <div class="glass rounded-2xl p-8 flex flex-col items-center">
            <div class="relative w-40 h-40 mb-4">
              <svg class="w-40 h-40 transform -rotate-90" viewBox="0 0 160 160">
                <circle
                  cx="80" cy="80" r="70"
                  stroke="var(--border)"
                  stroke-width="12"
                  fill="none"
                />
                <circle
                  cx="80" cy="80" r="70"
                  :stroke="deliverabilityScoreRingColor(deliverabilityReport.score)"
                  stroke-width="12"
                  fill="none"
                  stroke-linecap="round"
                  :stroke-dasharray="2 * Math.PI * 70"
                  :stroke-dashoffset="2 * Math.PI * 70 * (1 - deliverabilityReport.score / 100)"
                  class="transition-all duration-1000 ease-out"
                />
              </svg>
              <div class="absolute inset-0 flex flex-col items-center justify-center">
                <span
                  class="text-4xl font-bold"
                  :class="deliverabilityScoreColor(deliverabilityReport.score)"
                >{{ deliverabilityReport.score }}</span>
                <span class="text-xs text-[var(--text-muted)]">/ 100</span>
              </div>
            </div>
            <p class="text-sm text-[var(--text-muted)]">
              Deliverability Score for <span class="font-medium text-[var(--text-primary)]">{{ deliverabilityReport.domain }}</span>
            </p>
            <p class="text-xs text-[var(--text-muted)] mt-1">
              Tested {{ formatTimeAgo(deliverabilityReport.tested_at) }}
            </p>
          </div>

          <!-- Check Cards -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div
              v-for="(check, idx) in deliverabilityReport.checks"
              :key="idx"
              class="glass rounded-2xl p-5"
            >
              <div class="flex items-start gap-3">
                <div
                  class="flex-shrink-0 w-8 h-8 rounded-lg border flex items-center justify-center text-sm font-bold"
                  :class="deliverabilityCheckIcon(check.status).cls"
                >
                  {{ deliverabilityCheckIcon(check.status).symbol }}
                </div>
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2 mb-1">
                    <h4 class="text-sm font-semibold text-[var(--text-primary)]">{{ check.name }}</h4>
                    <span
                      class="text-[10px] font-medium uppercase px-1.5 py-0.5 rounded-full"
                      :class="{
                        'bg-green-500/10 text-green-400': check.status === 'pass',
                        'bg-yellow-500/10 text-yellow-400': check.status === 'warn',
                        'bg-red-500/10 text-red-400': check.status === 'fail'
                      }"
                    >{{ check.status }}</span>
                  </div>
                  <p class="text-xs text-[var(--text-muted)] leading-relaxed break-all">{{ check.details }}</p>
                  <p v-if="check.recommendation" class="text-xs text-yellow-400/80 mt-2 leading-relaxed">
                    Recommendation: {{ check.recommendation }}
                  </p>
                </div>
              </div>
            </div>
          </div>

          <!-- Expected DNS Records -->
          <div v-if="deliverabilityReport.expected_records" class="glass rounded-2xl p-6">
            <h3 class="text-sm font-semibold text-[var(--text-primary)] mb-4">Expected DNS Records</h3>
            <div class="space-y-4">
              <!-- SPF -->
              <div class="p-4 bg-[var(--surface)] border border-[var(--border)] rounded-lg">
                <div class="flex items-center justify-between mb-2">
                  <div>
                    <span class="text-xs font-medium text-primary">SPF (TXT Record)</span>
                    <p class="text-xs text-[var(--text-muted)] mt-0.5">Name: <span class="font-mono">{{ deliverabilityReport.expected_records.SPF_name }}</span></p>
                  </div>
                  <button
                    class="btn-ghost text-xs px-3 py-1"
                    @click="copyToClipboard(deliverabilityReport.expected_records.SPF, 'SPF')"
                  >
                    {{ copiedRecord === 'SPF' ? 'Copied!' : 'Copy' }}
                  </button>
                </div>
                <code class="block text-xs text-[var(--text-muted)] font-mono bg-[var(--background)] p-2 rounded break-all">{{ deliverabilityReport.expected_records.SPF }}</code>
              </div>

              <!-- DKIM -->
              <div class="p-4 bg-[var(--surface)] border border-[var(--border)] rounded-lg">
                <div class="flex items-center justify-between mb-2">
                  <div>
                    <span class="text-xs font-medium text-primary">DKIM (TXT Record)</span>
                    <p class="text-xs text-[var(--text-muted)] mt-0.5">Name: <span class="font-mono">{{ deliverabilityReport.expected_records.DKIM_name }}</span></p>
                  </div>
                  <button
                    class="btn-ghost text-xs px-3 py-1"
                    @click="copyToClipboard(deliverabilityReport.expected_records.DKIM_name, 'DKIM_name')"
                  >
                    {{ copiedRecord === 'DKIM_name' ? 'Copied!' : 'Copy Name' }}
                  </button>
                </div>
                <code class="block text-xs text-[var(--text-muted)] font-mono bg-[var(--background)] p-2 rounded break-all">{{ deliverabilityReport.expected_records.DKIM }}</code>
              </div>

              <!-- DMARC -->
              <div class="p-4 bg-[var(--surface)] border border-[var(--border)] rounded-lg">
                <div class="flex items-center justify-between mb-2">
                  <div>
                    <span class="text-xs font-medium text-primary">DMARC (TXT Record)</span>
                    <p class="text-xs text-[var(--text-muted)] mt-0.5">Name: <span class="font-mono">{{ deliverabilityReport.expected_records.DMARC_name }}</span></p>
                  </div>
                  <button
                    class="btn-ghost text-xs px-3 py-1"
                    @click="copyToClipboard(deliverabilityReport.expected_records.DMARC, 'DMARC')"
                  >
                    {{ copiedRecord === 'DMARC' ? 'Copied!' : 'Copy' }}
                  </button>
                </div>
                <code class="block text-xs text-[var(--text-muted)] font-mono bg-[var(--background)] p-2 rounded break-all">{{ deliverabilityReport.expected_records.DMARC }}</code>
              </div>
            </div>
          </div>
        </template>

        <!-- No results yet -->
        <div v-if="!deliverabilityReport && !deliverabilityLoading" class="glass rounded-2xl p-12 text-center">
          <p class="text-[var(--text-muted)] text-sm">Select a domain and click "Run Test" to check email deliverability.</p>
          <p class="text-[var(--text-muted)] text-xs mt-2">Tests SPF, DKIM, DMARC, MX, PTR, blacklists, TLS, and HELO/EHLO.</p>
        </div>
      </div>

      <!-- Queue Tab (admin only) -->
      <div v-else-if="activeTab === 'queue'" key="queue" class="space-y-4">
        <div class="flex justify-end">
          <button class="btn-danger inline-flex items-center gap-2" @click="showFlushDialog = true">
            Flush Queue
          </button>
        </div>
        <div class="glass rounded-2xl p-0 overflow-hidden">
          <DataTable
            :columns="queueColumns"
            :rows="queueItems"
            :loading="queueLoading"
            empty-text="Mail queue is empty."
          >
            <template #cell-message_id="{ value }">
              <span class="font-mono text-xs text-[var(--text-muted)]">{{ value }}</span>
            </template>

            <template #cell-from="{ value }">
              <span class="text-sm text-[var(--text-primary)]">{{ value }}</span>
            </template>

            <template #cell-to="{ value }">
              <span class="text-sm text-[var(--text-primary)]">{{ value }}</span>
            </template>

            <template #cell-subject="{ value }">
              <span class="text-sm text-[var(--text-muted)] truncate block max-w-[200px]">{{ value || '(no subject)' }}</span>
            </template>

            <template #cell-queued_at="{ value }">
              <span class="text-sm text-[var(--text-muted)]">{{ formatTimeAgo(value) }}</span>
            </template>

            <template #actions="{ row }">
              <button class="btn-ghost text-xs px-2 py-1 text-error hover:text-error" @click="confirmDeleteQueueItem(row)">
                Remove
              </button>
            </template>
          </DataTable>
        </div>
      </div>
    </Transition>

    <!-- Add/Edit Mailbox Modal -->
    <Modal v-model="showMailboxModal" :title="editingMailbox ? 'Edit Mailbox' : 'Add Mailbox'" size="md">
      <form @submit.prevent="handleSaveMailbox" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Email Address</label>
          <div class="flex gap-0">
            <input
              v-model="mailboxForm.prefix"
              type="text"
              placeholder="user"
              required
              :disabled="!!editingMailbox"
              class="flex-1 px-4 py-2 bg-[var(--surface)] border border-r-0 border-[var(--border)] rounded-l-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors disabled:bg-[var(--background)] disabled:cursor-not-allowed"
            />
            <span class="inline-flex items-center px-3 bg-[var(--background)] border-y border-[var(--border)] text-sm text-[var(--text-muted)]">@</span>
            <select
              v-model="mailboxForm.domain"
              :disabled="!!editingMailbox"
              class="px-4 py-2 bg-[var(--surface)] border border-l-0 border-[var(--border)] rounded-r-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors disabled:bg-[var(--background)] disabled:cursor-not-allowed"
            >
              <option v-for="d in availableDomains" :key="d" :value="d">{{ d }}</option>
            </select>
          </div>
        </div>

        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Password</label>
          <input
            v-model="mailboxForm.password"
            type="password"
            :placeholder="editingMailbox ? 'Leave blank to keep current' : 'Password'"
            :required="!editingMailbox"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
            Quota: {{ mailboxForm.quota }} MB
          </label>
          <input
            v-model.number="mailboxForm.quota"
            type="range"
            min="50"
            max="10240"
            step="50"
            class="w-full accent-primary"
          />
          <div class="flex justify-between text-xs text-[var(--text-muted)] mt-1">
            <span>50 MB</span>
            <span>10 GB</span>
          </div>
        </div>
      </form>

      <template #actions>
        <button class="btn-secondary" @click="showMailboxModal = false">Cancel</button>
        <button class="btn-primary" :disabled="mailboxSubmitting" @click="handleSaveMailbox">
          <span v-if="mailboxSubmitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          {{ editingMailbox ? 'Save Changes' : 'Create Mailbox' }}
        </button>
      </template>
    </Modal>

    <!-- Add/Edit Alias Modal (multi-target forwarding) -->
    <Modal v-model="showAliasModal" :title="editingAlias ? 'Edit Alias' : 'Add Alias'" size="md">
      <form @submit.prevent="handleSaveAlias" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">From Address</label>
          <input
            v-model="aliasForm.from_address"
            type="email"
            placeholder="alias@example.com"
            required
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Destination Addresses</label>
          <div
            v-for="(dest, idx) in aliasForm.destinations"
            :key="idx"
            class="flex gap-2 mb-2"
          >
            <input
              v-model="aliasForm.destinations[idx]"
              type="email"
              :placeholder="'destination' + (idx + 1) + '@example.com'"
              required
              class="flex-1 px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
            />
            <button
              v-if="aliasForm.destinations.length > 1"
              type="button"
              class="btn-ghost text-error text-xs px-2"
              @click="removeDestination(idx)"
            >
              Remove
            </button>
          </div>
          <button type="button" class="btn-ghost text-xs text-primary mt-1" @click="addDestination">
            + Add another destination
          </button>
        </div>

        <div class="flex items-center gap-3 pt-1">
          <button
            type="button"
            role="switch"
            :aria-checked="aliasForm.keep_local_copy"
            class="relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-primary/50"
            :class="aliasForm.keep_local_copy ? 'bg-primary' : 'bg-[var(--border)]'"
            @click="aliasForm.keep_local_copy = !aliasForm.keep_local_copy"
          >
            <span
              class="pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
              :class="aliasForm.keep_local_copy ? 'translate-x-5' : 'translate-x-0'"
            />
          </button>
          <div>
            <span class="text-sm font-medium text-[var(--text-primary)]">Keep local copy</span>
            <p class="text-xs text-[var(--text-muted)]">Deliver a copy to the original mailbox in addition to forwarding</p>
          </div>
        </div>
      </form>

      <template #actions>
        <button class="btn-secondary" @click="showAliasModal = false">Cancel</button>
        <button class="btn-primary" :disabled="aliasSubmitting" @click="handleSaveAlias">
          <span v-if="aliasSubmitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          {{ editingAlias ? 'Save Changes' : 'Create Alias' }}
        </button>
      </template>
    </Modal>

    <!-- Autoresponder Modal -->
    <Modal v-model="showAutoresponderModal" title="Autoresponder" size="md">
      <div class="space-y-4">
        <div v-if="autoresponderLoading" class="flex justify-center py-8">
          <span class="inline-block w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin"></span>
        </div>
        <template v-else>
          <div class="flex items-center justify-between">
            <label class="text-sm font-medium text-[var(--text-primary)]">Enable Autoresponder</label>
            <button
              class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
              :class="autoresponderForm.enabled ? 'bg-primary' : 'bg-[var(--border)]'"
              @click="autoresponderForm.enabled = !autoresponderForm.enabled"
            >
              <span
                class="inline-block h-4 w-4 rounded-full bg-white transition-transform"
                :class="autoresponderForm.enabled ? 'translate-x-6' : 'translate-x-1'"
              />
            </button>
          </div>

          <div v-if="autoresponderForm.enabled" class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Subject</label>
              <input
                v-model="autoresponderForm.subject"
                type="text"
                placeholder="e.g. Out of Office"
                class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Message Body</label>
              <textarea
                v-model="autoresponderForm.body"
                rows="5"
                placeholder="Thank you for your email. I am currently out of the office..."
                class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors resize-y"
              />
            </div>

            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Start Date</label>
                <input
                  v-model="autoresponderForm.start_date"
                  type="datetime-local"
                  class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
                />
              </div>
              <div>
                <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">End Date</label>
                <input
                  v-model="autoresponderForm.end_date"
                  type="datetime-local"
                  class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
                />
              </div>
            </div>
            <p class="text-xs text-[var(--text-muted)]">
              Leave dates empty for an always-active autoresponder. The system sends at most one reply per day per sender.
            </p>
          </div>
        </template>
      </div>

      <template #actions>
        <button class="btn-secondary" @click="showAutoresponderModal = false">Cancel</button>
        <button
          class="btn-primary"
          :disabled="autoresponderSubmitting || autoresponderLoading"
          @click="handleSaveAutoresponder"
        >
          <span v-if="autoresponderSubmitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          Save
        </button>
      </template>
    </Modal>

    <!-- Change Password Modal -->
    <Modal v-model="showPasswordModal" title="Change Password" size="md">
      <form @submit.prevent="handleChangePassword" class="space-y-4">
        <p class="text-sm text-[var(--text-muted)]">
          Changing password for <span class="font-medium text-[var(--text-primary)]">{{ passwordTarget?.address }}</span>
        </p>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">New Password</label>
          <input
            v-model="passwordForm.new_password"
            type="password"
            placeholder="Enter new password (min 8 characters)"
            required
            minlength="8"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Confirm Password</label>
          <input
            v-model="passwordForm.confirm_password"
            type="password"
            placeholder="Confirm new password"
            required
            minlength="8"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
          />
        </div>
      </form>

      <template #actions>
        <button class="btn-secondary" @click="showPasswordModal = false">Cancel</button>
        <button class="btn-primary" :disabled="passwordSubmitting" @click="handleChangePassword">
          <span v-if="passwordSubmitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          Change Password
        </button>
      </template>
    </Modal>

    <!-- Sieve Filters Modal -->
    <Modal v-model="showFiltersModal" :title="'Mail Filters' + (filtersMailbox ? ' - ' + filtersMailbox.address : '')" size="lg">
      <div class="space-y-4">
        <div v-if="filtersLoading" class="flex justify-center py-8">
          <span class="inline-block w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin"></span>
        </div>
        <template v-else>
          <!-- Templates -->
          <div>
            <label class="block text-sm font-medium text-[var(--text-primary)] mb-2">Quick Templates</label>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="tpl in sieveTemplates"
                :key="tpl.name"
                class="btn-ghost text-xs px-3 py-1.5 border border-[var(--border)] rounded-lg hover:border-primary"
                @click="applyTemplate(tpl)"
              >
                {{ tpl.name }}
              </button>
            </div>
          </div>

          <!-- Mode Toggle -->
          <div class="flex items-center justify-between border-b border-[var(--border)] pb-3">
            <span class="text-sm font-medium text-[var(--text-primary)]">
              {{ filtersAdvanced ? 'Advanced (Raw Sieve)' : 'Rule Builder' }}
            </span>
            <button
              class="btn-ghost text-xs px-3 py-1"
              @click="filtersAdvanced = !filtersAdvanced; if (!filtersAdvanced && filterRules.length === 0) filterRules.push(newEmptyRule())"
            >
              {{ filtersAdvanced ? 'Switch to Rule Builder' : 'Switch to Advanced' }}
            </button>
          </div>

          <!-- Rule Builder Mode -->
          <div v-if="!filtersAdvanced" class="space-y-3">
            <div
              v-for="(rule, idx) in filterRules"
              :key="idx"
              class="p-3 bg-[var(--surface)] border border-[var(--border)] rounded-lg space-y-2"
            >
              <div class="flex items-center gap-2 text-xs text-[var(--text-muted)]">
                <span class="font-medium">Rule {{ idx + 1 }}</span>
                <button
                  v-if="filterRules.length > 1"
                  class="ml-auto text-error hover:text-error"
                  @click="removeFilterRule(idx)"
                >
                  Remove
                </button>
              </div>

              <!-- Condition -->
              <div class="flex flex-wrap gap-2">
                <span class="text-sm text-[var(--text-muted)] self-center">If</span>
                <select
                  v-model="rule.field"
                  class="px-3 py-1.5 bg-[var(--background)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                >
                  <option value="from">From</option>
                  <option value="to">To</option>
                  <option value="subject">Subject</option>
                  <option value="cc">Cc</option>
                </select>
                <select
                  v-model="rule.match_type"
                  class="px-3 py-1.5 bg-[var(--background)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                >
                  <option value="contains">contains</option>
                  <option value="is">is exactly</option>
                  <option value="matches">matches (wildcard)</option>
                  <option value="regex">matches (regex)</option>
                </select>
                <input
                  v-model="rule.value"
                  type="text"
                  placeholder="Value..."
                  class="flex-1 min-w-[150px] px-3 py-1.5 bg-[var(--background)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
              </div>

              <!-- Action -->
              <div class="flex flex-wrap gap-2">
                <span class="text-sm text-[var(--text-muted)] self-center">Then</span>
                <select
                  v-model="rule.action"
                  class="px-3 py-1.5 bg-[var(--background)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                >
                  <option value="fileinto">Move to folder</option>
                  <option value="redirect">Forward to</option>
                  <option value="discard">Discard</option>
                  <option value="addflag">Mark as read</option>
                </select>
                <input
                  v-if="rule.action === 'fileinto'"
                  v-model="rule.action_value"
                  type="text"
                  placeholder="Folder name (e.g. Junk, Archive)"
                  class="flex-1 min-w-[150px] px-3 py-1.5 bg-[var(--background)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
                <input
                  v-if="rule.action === 'redirect'"
                  v-model="rule.action_value"
                  type="email"
                  placeholder="Forward to address"
                  class="flex-1 min-w-[150px] px-3 py-1.5 bg-[var(--background)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
                <span v-if="rule.action === 'addflag'" class="text-xs text-[var(--text-muted)] self-center">(flags message as \\Seen)</span>
              </div>
            </div>

            <button class="btn-ghost text-xs text-primary" @click="addFilterRule">
              + Add another rule
            </button>
          </div>

          <!-- Advanced Mode (raw Sieve) -->
          <div v-else class="space-y-2">
            <textarea
              v-model="filtersScript"
              rows="14"
              placeholder="require [&quot;fileinto&quot;];&#10;&#10;if header :contains &quot;Subject&quot; &quot;[SPAM]&quot; {&#10;    fileinto &quot;Junk&quot;;&#10;}"
              class="w-full px-4 py-3 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors font-mono resize-y"
            />
          </div>

          <!-- Test Result -->
          <div v-if="filtersTestResult" class="p-3 rounded-lg text-sm" :class="filtersTestResult.valid ? 'bg-green-500/10 border border-green-500/30 text-green-400' : 'bg-red-500/10 border border-red-500/30 text-red-400'">
            <p v-if="filtersTestResult.valid" class="font-medium">Sieve script is valid.</p>
            <template v-else>
              <p class="font-medium">Sieve validation failed:</p>
              <pre class="mt-1 text-xs whitespace-pre-wrap">{{ filtersTestResult.errors }}</pre>
            </template>
          </div>
        </template>
      </div>

      <template #actions>
        <button class="btn-secondary" @click="showFiltersModal = false">Cancel</button>
        <button
          class="btn-ghost border border-[var(--border)]"
          :disabled="filtersTesting || filtersLoading"
          @click="handleTestSieve"
        >
          <span v-if="filtersTesting" class="inline-block w-4 h-4 border-2 border-primary/30 border-t-primary rounded-full animate-spin mr-2"></span>
          Test Syntax
        </button>
        <button
          class="btn-primary"
          :disabled="filtersSubmitting || filtersLoading"
          @click="handleSaveFilters"
        >
          <span v-if="filtersSubmitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          Save Filters
        </button>
      </template>
    </Modal>

    <!-- Spam Filter Modal -->
    <Modal v-model="showSpamModal" :title="'Spam Filter' + (spamMailbox ? ' - ' + spamMailbox.address : '')" size="md">
      <div class="space-y-4">
        <div v-if="spamLoading" class="flex justify-center py-8">
          <span class="inline-block w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin"></span>
        </div>
        <template v-else>
          <!-- Enable/Disable Toggle -->
          <div class="flex items-center justify-between">
            <label class="text-sm font-medium text-[var(--text-primary)]">Enable Spam Filter</label>
            <button
              class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
              :class="spamForm.enabled ? 'bg-primary' : 'bg-[var(--border)]'"
              @click="spamForm.enabled = !spamForm.enabled"
            >
              <span
                class="inline-block h-4 w-4 rounded-full bg-white transition-transform"
                :class="spamForm.enabled ? 'translate-x-6' : 'translate-x-1'"
              />
            </button>
          </div>

          <div v-if="spamForm.enabled" class="space-y-4">
            <!-- Sensitivity Slider -->
            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">
                Sensitivity: {{ spamSensitivityLabel }}
              </label>
              <input
                v-model.number="spamForm.sensitivity"
                type="range"
                min="1"
                max="10"
                step="1"
                class="w-full accent-primary"
              />
              <div class="flex justify-between text-xs text-[var(--text-muted)] mt-1">
                <span>1 - Very Aggressive</span>
                <span>10 - Very Permissive</span>
              </div>
              <p class="text-xs text-[var(--text-muted)] mt-1">
                SpamAssassin score threshold: {{ spamScoreFromSensitivity(spamForm.sensitivity).toFixed(1) }}
                (lower = catches more spam but may have false positives)
              </p>
            </div>

            <!-- Action Dropdown -->
            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Action on Spam</label>
              <select
                v-model="spamForm.action"
                class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
              >
                <option value="move">Move to Junk</option>
                <option value="delete">Delete</option>
                <option value="tag_only">Tag Only</option>
              </select>
              <p class="text-xs text-[var(--text-muted)] mt-1">
                {{ spamForm.action === 'move' ? 'Spam messages are moved to the Junk/Spam folder.' : spamForm.action === 'delete' ? 'Spam messages are permanently deleted.' : 'Spam messages are tagged but stay in the inbox.' }}
              </p>
            </div>

            <!-- Whitelist -->
            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Whitelist (bypass spam filter)</label>
              <textarea
                v-model="spamForm.whitelist"
                rows="3"
                placeholder="One email address per line, e.g.&#10;friend@example.com&#10;newsletter@trusted.com"
                class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors font-mono resize-y"
              />
            </div>

            <!-- Blacklist -->
            <div>
              <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Blacklist (always mark as spam)</label>
              <textarea
                v-model="spamForm.blacklist"
                rows="3"
                placeholder="One email address per line, e.g.&#10;spammer@example.com&#10;*@spamdomain.com"
                class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors font-mono resize-y"
              />
            </div>
          </div>
        </template>
      </div>

      <template #actions>
        <button class="btn-secondary" @click="showSpamModal = false">Cancel</button>
        <button
          class="btn-primary"
          :disabled="spamSubmitting || spamLoading"
          @click="handleSaveSpamFilter"
        >
          <span v-if="spamSubmitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          Save
        </button>
      </template>
    </Modal>

    <!-- Delete Mailbox Confirm -->
    <ConfirmDialog
      v-model="showDeleteMailboxDialog"
      title="Delete Mailbox"
      :message="`Permanently delete '${itemToDelete?.address}'? All emails in this mailbox will be lost.`"
      confirm-text="Delete Mailbox"
      :destructive="true"
      @confirm="handleDeleteMailbox"
    />

    <!-- Delete Alias Confirm -->
    <ConfirmDialog
      v-model="showDeleteAliasDialog"
      title="Delete Alias"
      :message="`Remove alias '${itemToDelete?.from_address}'?`"
      confirm-text="Delete Alias"
      :destructive="true"
      @confirm="handleDeleteAlias"
    />

    <!-- Flush Queue Confirm -->
    <ConfirmDialog
      v-model="showFlushDialog"
      title="Flush Mail Queue"
      message="This will attempt to deliver all queued messages immediately. Continue?"
      confirm-text="Flush Queue"
      :destructive="false"
      @confirm="handleFlushQueue"
    />

    <!-- Delete Queue Item Confirm -->
    <ConfirmDialog
      v-model="showDeleteQueueDialog"
      title="Remove from Queue"
      :message="`Remove message '${queueItemToDelete?.message_id}' from the mail queue?`"
      confirm-text="Remove"
      :destructive="true"
      @confirm="handleDeleteQueueItem"
    />

    <!-- Create Mailing List Modal -->
    <Modal v-model="mlShowCreateModal" title="Create Mailing List" size="md">
      <form @submit.prevent="handleCreateList" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">List Name</label>
          <div class="flex gap-0">
            <input
              v-model="mlCreateForm.name"
              type="text"
              placeholder="announcements"
              required
              class="flex-1 px-4 py-2 bg-[var(--surface)] border border-r-0 border-[var(--border)] rounded-l-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
            />
            <span class="inline-flex items-center px-3 bg-[var(--background)] border-y border-[var(--border)] text-sm text-[var(--text-muted)]">@</span>
            <select
              v-model="mlCreateForm.domain"
              class="px-4 py-2 bg-[var(--surface)] border border-l-0 border-[var(--border)] rounded-r-lg text-sm text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
            >
              <option v-for="d in availableDomains" :key="d" :value="d">{{ d }}</option>
            </select>
          </div>
          <p class="text-xs text-[var(--text-muted)] mt-1">List address will be: {{ mlCreateForm.name || 'name' }}@{{ mlCreateForm.domain || 'example.com' }}</p>
        </div>

        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Description</label>
          <input
            v-model="mlCreateForm.description"
            type="text"
            placeholder="Brief description of this mailing list"
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Owner Email</label>
          <input
            v-model="mlCreateForm.owner_email"
            type="email"
            placeholder="admin@example.com"
            required
            class="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors"
          />
        </div>

        <div class="flex items-center gap-6 pt-1">
          <label class="flex items-center gap-2 text-sm text-[var(--text-primary)] cursor-pointer">
            <button
              type="button"
              role="switch"
              :aria-checked="mlCreateForm.is_moderated"
              class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors"
              :class="mlCreateForm.is_moderated ? 'bg-primary' : 'bg-[var(--border)]'"
              @click="mlCreateForm.is_moderated = !mlCreateForm.is_moderated"
            >
              <span class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition" :class="mlCreateForm.is_moderated ? 'translate-x-4' : 'translate-x-0'" />
            </button>
            Moderated
          </label>
          <label class="flex items-center gap-2 text-sm text-[var(--text-primary)] cursor-pointer">
            <button
              type="button"
              role="switch"
              :aria-checked="mlCreateForm.reply_to_list"
              class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors"
              :class="mlCreateForm.reply_to_list ? 'bg-primary' : 'bg-[var(--border)]'"
              @click="mlCreateForm.reply_to_list = !mlCreateForm.reply_to_list"
            >
              <span class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition" :class="mlCreateForm.reply_to_list ? 'translate-x-4' : 'translate-x-0'" />
            </button>
            Reply-To List
          </label>
        </div>
      </form>

      <template #actions>
        <button class="btn-secondary" @click="mlShowCreateModal = false">Cancel</button>
        <button class="btn-primary" :disabled="mlCreateSubmitting" @click="handleCreateList">
          <span v-if="mlCreateSubmitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          Create List
        </button>
      </template>
    </Modal>

    <!-- Add Members Modal -->
    <Modal v-model="mlShowAddMembers" title="Add Members" size="md">
      <div class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-[var(--text-primary)] mb-1">Email Addresses</label>
          <textarea
            v-model="mlAddMembersText"
            rows="8"
            placeholder="Enter one email address per line:&#10;user1@example.com&#10;user2@example.com&#10;user3@example.com"
            class="w-full px-4 py-3 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-primary/50 transition-colors font-mono resize-y"
          />
          <p class="text-xs text-[var(--text-muted)] mt-1">One email address per line. Duplicates will be skipped.</p>
        </div>
        <div class="flex items-center gap-3">
          <label class="flex items-center gap-2 text-sm text-[var(--text-primary)] cursor-pointer">
            <button
              type="button"
              role="switch"
              :aria-checked="mlAddMembersAdmin"
              class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors"
              :class="mlAddMembersAdmin ? 'bg-primary' : 'bg-[var(--border)]'"
              @click="mlAddMembersAdmin = !mlAddMembersAdmin"
            >
              <span class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition" :class="mlAddMembersAdmin ? 'translate-x-4' : 'translate-x-0'" />
            </button>
            Add as admin
          </label>
        </div>
      </div>

      <template #actions>
        <button class="btn-secondary" @click="mlShowAddMembers = false">Cancel</button>
        <button class="btn-primary" :disabled="mlAddMembersSubmitting" @click="handleAddMembers">
          <span v-if="mlAddMembersSubmitting" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></span>
          Add Members
        </button>
      </template>
    </Modal>

    <!-- Delete Mailing List Confirm -->
    <ConfirmDialog
      v-model="mlShowDeleteDialog"
      title="Delete Mailing List"
      :message="`Permanently delete mailing list '${mlListToDelete?.list_address}'? All members will be removed.`"
      confirm-text="Delete List"
      :destructive="true"
      @confirm="handleDeleteList"
    />

    <!-- Remove Member Confirm -->
    <ConfirmDialog
      v-model="mlShowRemoveMemberDialog"
      title="Remove Member"
      :message="`Remove '${mlMemberToRemove?.email}' from this mailing list?`"
      confirm-text="Remove"
      :destructive="true"
      @confirm="handleRemoveMember"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useEmailStore } from '@/stores/email'
import { useDomainsStore } from '@/stores/domains'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'
import DataTable from '@/components/DataTable.vue'
import Modal from '@/components/Modal.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import client from '@/api/client'

const emailStore = useEmailStore()
const domainsStore = useDomainsStore()
const auth = useAuthStore()
const notifications = useNotificationsStore()

const allTabs = [
  { key: 'mailboxes', label: 'Mailboxes' },
  { key: 'aliases', label: 'Aliases' },
  { key: 'mailing-lists', label: 'Mailing Lists' },
  { key: 'catch-all', label: 'Catch-All' },
  { key: 'filters', label: 'Filters' },
  { key: 'deliverability', label: 'Deliverability' },
  { key: 'queue', label: 'Queue' }
]

const visibleTabs = computed(() => {
  if (auth.isAdmin) return allTabs
  return allTabs.filter(t => t.key !== 'queue')
})

const mailboxColumns = [
  { key: 'address', label: 'Email' },
  { key: 'domain', label: 'Domain' },
  { key: 'quota', label: 'Quota' },
  { key: 'status', label: 'Status' }
]

const aliasColumns = [
  { key: 'from_address', label: 'From' },
  { key: 'to_address', label: 'To' }
]

const queueColumns = [
  { key: 'message_id', label: 'Message ID' },
  { key: 'from', label: 'From' },
  { key: 'to', label: 'To' },
  { key: 'subject', label: 'Subject' },
  { key: 'queued_at', label: 'Time in Queue' }
]

const activeTab = ref('mailboxes')
const search = ref('')

// SSO state
const ssoLoading = ref(null)

// Mailbox state
const showMailboxModal = ref(false)
const editingMailbox = ref(null)
const mailboxSubmitting = ref(false)
const mailboxForm = ref({ prefix: '', domain: '', password: '', quota: 500 })

// Alias state
const showAliasModal = ref(false)
const editingAlias = ref(null)
const aliasSubmitting = ref(false)
const aliasForm = ref({ from_address: '', destinations: [''], keep_local_copy: false })

// Delete state
const showDeleteMailboxDialog = ref(false)
const showDeleteAliasDialog = ref(false)
const itemToDelete = ref(null)

// Catch-all state
const catchAllDomains = ref([])
const catchAllLoading = ref(false)

// Mailing list state
const mlDetailView = ref(null)
const mlShowSettings = ref(false)
const mlShowCreateModal = ref(false)
const mlCreateSubmitting = ref(false)
const mlCreateForm = ref({ name: '', domain: '', description: '', owner_email: '', is_moderated: false, reply_to_list: false })
const mlSettingsForm = ref({})
const mlSettingsSaving = ref(false)
const mlShowAddMembers = ref(false)
const mlAddMembersText = ref('')
const mlAddMembersAdmin = ref(false)
const mlAddMembersSubmitting = ref(false)
const mlShowDeleteDialog = ref(false)
const mlListToDelete = ref(null)
const mlShowRemoveMemberDialog = ref(false)
const mlMemberToRemove = ref(null)

const mlMemberColumns = [
  { key: 'email', label: 'Email' },
  { key: 'name', label: 'Name' },
  { key: 'role', label: 'Role' },
  { key: 'subscribed_at', label: 'Subscribed' }
]

// Queue state
const queueItems = ref([])
const queueLoading = ref(false)
const showFlushDialog = ref(false)
const showDeleteQueueDialog = ref(false)
const queueItemToDelete = ref(null)

// Autoresponder state
const showAutoresponderModal = ref(false)
const autoresponderLoading = ref(false)
const autoresponderSubmitting = ref(false)
const autoresponderMailbox = ref(null)
const autoresponderForm = ref({
  enabled: false,
  subject: '',
  body: '',
  start_date: '',
  end_date: ''
})

// Sieve filter state
const showFiltersModal = ref(false)
const filtersLoading = ref(false)
const filtersSubmitting = ref(false)
const filtersTesting = ref(false)
const filtersMailbox = ref(null)
const filtersAdvanced = ref(false)
const filtersScript = ref('')
const filtersTestResult = ref(null)
const filterRules = ref([])

// Spam filter state
const showSpamModal = ref(false)
const spamLoading = ref(false)
const spamSubmitting = ref(false)
const spamMailbox = ref(null)
const spamForm = ref({
  enabled: true,
  sensitivity: 5,
  action: 'move',
  whitelist: '',
  blacklist: ''
})

const spamSensitivityLabel = computed(() => {
  const s = spamForm.value.sensitivity
  if (s <= 2) return 'Very Aggressive'
  if (s <= 4) return 'Aggressive'
  if (s <= 6) return 'Moderate'
  if (s <= 8) return 'Permissive'
  return 'Very Permissive'
})

function spamScoreFromSensitivity(sensitivity) {
  // Map 1-10 slider inversely to SpamAssassin score:
  // 1 (very aggressive) -> 1.0, 10 (very permissive) -> 10.0
  return sensitivity
}

function sensitivityFromScore(score) {
  // Inverse: SpamAssassin score -> slider value
  return Math.max(1, Math.min(10, Math.round(score)))
}

const sieveTemplates = [
  {
    name: 'Move spam to Junk',
    rules: [{ field: 'subject', match_type: 'contains', value: '[SPAM]', action: 'fileinto', action_value: 'Junk' }],
    script: 'require ["fileinto"];\n\nif header :contains "Subject" "[SPAM]" {\n    fileinto "Junk";\n}\n'
  },
  {
    name: 'Forward specific sender',
    rules: [{ field: 'from', match_type: 'contains', value: 'alerts@example.com', action: 'redirect', action_value: 'admin@example.com' }],
    script: 'if header :contains "From" "alerts@example.com" {\n    redirect "admin@example.com";\n}\n'
  },
  {
    name: 'Auto-file by subject',
    rules: [
      { field: 'subject', match_type: 'contains', value: '[Invoice]', action: 'fileinto', action_value: 'Billing' },
      { field: 'subject', match_type: 'contains', value: '[Support]', action: 'fileinto', action_value: 'Support' }
    ],
    script: 'require ["fileinto"];\n\nif header :contains "Subject" "[Invoice]" {\n    fileinto "Billing";\n}\nif header :contains "Subject" "[Support]" {\n    fileinto "Support";\n}\n'
  }
]

function newEmptyRule() {
  return { field: 'from', match_type: 'contains', value: '', action: 'fileinto', action_value: '' }
}

// Deliverability state
const deliverabilityDomain = ref('')
const deliverabilityReport = ref(null)
const deliverabilityLoading = ref(false)
const copiedRecord = ref('')

// Password change state
const showPasswordModal = ref(false)
const passwordSubmitting = ref(false)
const passwordTarget = ref(null)
const passwordForm = ref({ new_password: '', confirm_password: '' })

const availableDomains = computed(() => {
  const list = Array.isArray(domainsStore.domains) ? domainsStore.domains : []
  return list.map(d => d.name)
})

const filteredMailboxes = computed(() => {
  const list = Array.isArray(emailStore.mailboxes) ? emailStore.mailboxes : []
  if (!search.value) return list
  const q = search.value.toLowerCase()
  return list.filter(m =>
    m.address?.toLowerCase().includes(q) || m.domain?.toLowerCase().includes(q)
  )
})

const filteredAliases = computed(() => {
  const list = Array.isArray(emailStore.aliases) ? emailStore.aliases : []
  if (!search.value) return list
  const q = search.value.toLowerCase()
  return list.filter(a => {
    const src = (a.source || a.from_address || '').toLowerCase()
    const dst = (a.destination || a.to_address || '').toLowerCase()
    return src.includes(q) || dst.includes(q)
  })
})

function quotaPercent(row) {
  if (!row.quota_mb) return 0
  return Math.min(100, Math.round(((row.quota_used_mb || 0) / row.quota_mb) * 100))
}

function quotaBarColor(row) {
  const pct = quotaPercent(row)
  if (pct > 90) return 'bg-error'
  if (pct > 70) return 'bg-warning'
  return 'bg-primary'
}

function formatMB(bytes) {
  if (!bytes && bytes !== 0) return '0 MB'
  if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + ' KB'
  return Math.round(bytes / (1024 * 1024)) + ' MB'
}

function formatTimeAgo(dateStr) {
  if (!dateStr) return '--'
  const diff = Date.now() - new Date(dateStr).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

// SSO -- open webmail via Roundcube auto-login
async function openWebmail(row) {
  ssoLoading.value = row.id
  try {
    const { data } = await client.post(`/email/${row.id}/sso`)
    if (data.sso_url) {
      window.open(data.sso_url, '_blank', 'noopener,noreferrer')
    }
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to open webmail. The mailbox password may need to be re-set.')
  } finally {
    ssoLoading.value = null
  }
}

// Password change
function openChangePassword(row) {
  passwordTarget.value = row
  passwordForm.value = { new_password: '', confirm_password: '' }
  showPasswordModal.value = true
}

async function handleChangePassword() {
  if (!passwordForm.value.new_password || passwordForm.value.new_password.length < 8) {
    notifications.error('Password must be at least 8 characters.')
    return
  }
  if (passwordForm.value.new_password !== passwordForm.value.confirm_password) {
    notifications.error('Passwords do not match.')
    return
  }
  passwordSubmitting.value = true
  try {
    await emailStore.changePassword(passwordTarget.value.id, passwordForm.value.new_password)
    notifications.success(`Password changed for '${passwordTarget.value.address}'.`)
    showPasswordModal.value = false
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to change password.')
  } finally {
    passwordSubmitting.value = false
  }
}

// Mailbox CRUD
function openAddMailbox() {
  editingMailbox.value = null
  mailboxForm.value = {
    prefix: '',
    domain: availableDomains.value[0] || '',
    password: '',
    quota: 500
  }
  showMailboxModal.value = true
}

function editMailbox(row) {
  editingMailbox.value = row
  const parts = row.address.split('@')
  mailboxForm.value = {
    prefix: parts[0],
    domain: parts[1] || row.domain,
    password: '',
    quota: row.quota_mb || 500
  }
  showMailboxModal.value = true
}

async function handleSaveMailbox() {
  if (!mailboxForm.value.prefix.trim()) {
    notifications.error('Email address is required.')
    return
  }
  mailboxSubmitting.value = true
  try {
    const payload = {
      address: `${mailboxForm.value.prefix}@${mailboxForm.value.domain}`,
      domain: mailboxForm.value.domain,
      quota_total: mailboxForm.value.quota * 1024 * 1024
    }
    if (mailboxForm.value.password) {
      payload.password = mailboxForm.value.password
    }

    if (editingMailbox.value) {
      await emailStore.updateMailbox(editingMailbox.value.id, payload)
      notifications.success('Mailbox updated.')
    } else {
      payload.password = mailboxForm.value.password
      await emailStore.createMailbox(payload)
      notifications.success(`Mailbox '${payload.address}' created.`)
    }
    showMailboxModal.value = false
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to save mailbox.')
  } finally {
    mailboxSubmitting.value = false
  }
}

function confirmDeleteMailbox(row) {
  itemToDelete.value = row
  showDeleteMailboxDialog.value = true
}

async function handleDeleteMailbox() {
  if (!itemToDelete.value) return
  try {
    await emailStore.removeMailbox(itemToDelete.value.id)
    notifications.success(`Mailbox '${itemToDelete.value.address}' deleted.`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete mailbox.')
  } finally {
    itemToDelete.value = null
  }
}

// Autoresponder
async function openAutoresponder(row) {
  autoresponderMailbox.value = row
  autoresponderLoading.value = true
  autoresponderForm.value = {
    enabled: false,
    subject: '',
    body: '',
    start_date: '',
    end_date: ''
  }
  showAutoresponderModal.value = true

  try {
    const data = await emailStore.getAutoresponder(row.id)
    autoresponderForm.value = {
      enabled: data.enabled || false,
      subject: data.subject || '',
      body: data.body || '',
      start_date: data.start_date ? data.start_date.slice(0, 16) : '',
      end_date: data.end_date ? data.end_date.slice(0, 16) : ''
    }
  } catch {
    // If fetching fails, start with defaults (already set above)
  } finally {
    autoresponderLoading.value = false
  }
}

async function handleSaveAutoresponder() {
  if (!autoresponderMailbox.value) return

  if (autoresponderForm.value.enabled) {
    if (!autoresponderForm.value.subject?.trim() || !autoresponderForm.value.body?.trim()) {
      notifications.error('Subject and message body are required.')
      return
    }
  }

  autoresponderSubmitting.value = true
  try {
    if (!autoresponderForm.value.enabled) {
      await emailStore.disableAutoresponder(autoresponderMailbox.value.id)
      notifications.success('Autoresponder disabled.')
    } else {
      const payload = {
        enabled: true,
        subject: autoresponderForm.value.subject,
        body: autoresponderForm.value.body,
        start_date: autoresponderForm.value.start_date ? new Date(autoresponderForm.value.start_date).toISOString() : null,
        end_date: autoresponderForm.value.end_date ? new Date(autoresponderForm.value.end_date).toISOString() : null
      }
      await emailStore.updateAutoresponder(autoresponderMailbox.value.id, payload)
      notifications.success('Autoresponder saved.')
    }
    showAutoresponderModal.value = false
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to save autoresponder.')
  } finally {
    autoresponderSubmitting.value = false
  }
}

// Alias CRUD
function openAddAlias() {
  editingAlias.value = null
  aliasForm.value = { from_address: '', destinations: [''], keep_local_copy: false }
  showAliasModal.value = true
}

function editAlias(row) {
  editingAlias.value = row
  const dests = row.destinations && row.destinations.length
    ? [...row.destinations]
    : (row.to_address ? row.to_address.split(',').map(d => d.trim()) : [''])
  aliasForm.value = {
    from_address: row.from_address || row.source || '',
    destinations: dests.length ? dests : [''],
    keep_local_copy: row.keep_local_copy || false
  }
  showAliasModal.value = true
}

function addDestination() {
  aliasForm.value.destinations.push('')
}

function removeDestination(idx) {
  if (aliasForm.value.destinations.length > 1) {
    aliasForm.value.destinations.splice(idx, 1)
  }
}

async function handleSaveAlias() {
  const validDests = aliasForm.value.destinations.filter(d => d.trim())
  if (!aliasForm.value.from_address.trim() || validDests.length === 0) {
    notifications.error('Source address and at least one destination are required.')
    return
  }
  aliasSubmitting.value = true
  try {
    const payload = {
      source: aliasForm.value.from_address,
      destinations: validDests,
      keep_local_copy: aliasForm.value.keep_local_copy
    }
    if (editingAlias.value) {
      await emailStore.updateAlias(editingAlias.value.id, payload)
      notifications.success('Alias updated.')
    } else {
      await emailStore.createAlias(payload)
      notifications.success('Alias created.')
    }
    showAliasModal.value = false
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to save alias.')
  } finally {
    aliasSubmitting.value = false
  }
}

// Sieve Filters
function openFilters(row) {
  filtersMailbox.value = row
  filtersAdvanced.value = false
  filtersScript.value = ''
  filtersTestResult.value = null
  filterRules.value = []
  showFiltersModal.value = true
  loadFilters(row)
}

async function loadFilters(row) {
  filtersLoading.value = true
  try {
    const data = await emailStore.getSieveFilters(row.id)
    filtersScript.value = data.script || ''
    filterRules.value = data.rules && data.rules.length ? data.rules : [newEmptyRule()]
  } catch {
    filtersScript.value = ''
    filterRules.value = [newEmptyRule()]
  } finally {
    filtersLoading.value = false
  }
}

function addFilterRule() {
  filterRules.value.push(newEmptyRule())
}

function removeFilterRule(idx) {
  filterRules.value.splice(idx, 1)
  if (filterRules.value.length === 0) filterRules.value.push(newEmptyRule())
}

function applyTemplate(tpl) {
  filterRules.value = tpl.rules.map(r => ({ ...r }))
  filtersScript.value = tpl.script
  notifications.success(`Template "${tpl.name}" applied.`)
}

async function handleTestSieve() {
  if (!filtersMailbox.value) return
  filtersTesting.value = true
  filtersTestResult.value = null
  try {
    const scriptToTest = filtersAdvanced.value ? filtersScript.value : buildScriptFromRules()
    const result = await emailStore.testSieveScript(filtersMailbox.value.id, scriptToTest)
    filtersTestResult.value = result
  } catch (err) {
    filtersTestResult.value = { valid: false, errors: err.response?.data?.detail || 'Validation failed.' }
  } finally {
    filtersTesting.value = false
  }
}

function buildScriptFromRules() {
  // Simple client-side compilation for preview
  const requires = new Set()
  const blocks = []
  for (const rule of filterRules.value) {
    if (!rule.value.trim()) continue
    if (rule.action === 'fileinto') requires.add('"fileinto"')
    if (rule.action === 'addflag') requires.add('"imap4flags"')
    const header = { from: '"From"', to: '"To"', subject: '"Subject"', cc: '"Cc"' }[rule.field] || `"${rule.field}"`
    const match = { contains: ':contains', matches: ':matches', is: ':is', regex: ':regex' }[rule.match_type] || ':contains'
    const val = rule.value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
    let action = 'keep;'
    if (rule.action === 'fileinto') action = `fileinto "${rule.action_value || 'INBOX'}";`
    else if (rule.action === 'redirect') action = `redirect "${rule.action_value || ''}";`
    else if (rule.action === 'discard') action = 'discard;'
    else if (rule.action === 'addflag') action = `addflag "${rule.action_value || '\\\\Seen'}";`
    blocks.push(`if header ${match} ${header} "${val}" {\n    ${action}\n}`)
  }
  let script = ''
  if (requires.size) script += `require [${[...requires].sort().join(', ')}];\n\n`
  script += blocks.join('\n') + '\n'
  return script
}

async function handleSaveFilters() {
  if (!filtersMailbox.value) return
  filtersSubmitting.value = true
  try {
    const payload = filtersAdvanced.value
      ? { script: filtersScript.value }
      : { rules: filterRules.value.filter(r => r.value.trim()) }
    await emailStore.saveSieveFilters(filtersMailbox.value.id, payload)
    notifications.success('Sieve filters saved.')
    showFiltersModal.value = false
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to save filters.')
  } finally {
    filtersSubmitting.value = false
  }
}

// Spam Filter
async function openSpamFilter(row) {
  spamMailbox.value = row
  spamLoading.value = true
  spamForm.value = {
    enabled: true,
    sensitivity: 5,
    action: 'move',
    whitelist: '',
    blacklist: ''
  }
  showSpamModal.value = true

  try {
    const data = await emailStore.fetchSpamSettings(row.id)
    spamForm.value = {
      enabled: data.enabled !== false,
      sensitivity: sensitivityFromScore(data.threshold || 5.0),
      action: data.action || 'move',
      whitelist: data.whitelist || '',
      blacklist: data.blacklist || ''
    }
  } catch {
    // If fetching fails, start with defaults (already set above)
  } finally {
    spamLoading.value = false
  }
}

async function handleSaveSpamFilter() {
  if (!spamMailbox.value) return

  spamSubmitting.value = true
  try {
    const payload = {
      enabled: spamForm.value.enabled,
      threshold: spamScoreFromSensitivity(spamForm.value.sensitivity),
      action: spamForm.value.action,
      whitelist: spamForm.value.whitelist || null,
      blacklist: spamForm.value.blacklist || null
    }
    await emailStore.updateSpamSettings(spamMailbox.value.id, payload)
    notifications.success('Spam filter settings saved.')
    showSpamModal.value = false
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to save spam filter settings.')
  } finally {
    spamSubmitting.value = false
  }
}

function confirmDeleteAlias(row) {
  itemToDelete.value = row
  showDeleteAliasDialog.value = true
}

async function handleDeleteAlias() {
  if (!itemToDelete.value) return
  try {
    await emailStore.removeAlias(itemToDelete.value.id)
    notifications.success('Alias deleted.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete alias.')
  } finally {
    itemToDelete.value = null
  }
}

// Catch-All
async function fetchCatchAll() {
  catchAllLoading.value = true
  try {
    const domains = Array.isArray(domainsStore.domains) ? domainsStore.domains : []
    const results = []
    for (const d of domains) {
      try {
        const { data } = await client.get(`/email/domains/${d.domain_name || d.name}/catch-all`)
        results.push({
          name: d.domain_name || d.name,
          catch_all_address: data.catch_all_address || null,
          _catchAllInput: data.catch_all_address || '',
          _editing: false,
        })
      } catch {
        results.push({
          name: d.domain_name || d.name,
          catch_all_address: null,
          _catchAllInput: '',
          _editing: false,
        })
      }
    }
    catchAllDomains.value = results
  } catch {
    catchAllDomains.value = []
  } finally {
    catchAllLoading.value = false
  }
}

function toggleCatchAll(d) {
  if (d.catch_all_address) {
    disableCatchAll(d)
  } else {
    d._editing = true
    d._catchAllInput = d._catchAllInput || ''
  }
}

async function saveCatchAll(d) {
  if (!d._catchAllInput?.trim()) return
  try {
    await client.put(`/email/domains/${d.name}/catch-all`, { address: d._catchAllInput.trim() })
    d.catch_all_address = d._catchAllInput.trim()
    d._editing = false
    notifications.success(`Catch-all enabled for ${d.name}`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to set catch-all.')
  }
}

async function disableCatchAll(d) {
  try {
    await client.delete(`/email/domains/${d.name}/catch-all`)
    d.catch_all_address = null
    d._catchAllInput = ''
    d._editing = false
    notifications.success(`Catch-all disabled for ${d.name}`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to disable catch-all.')
  }
}

// Queue
async function fetchQueue() {
  queueLoading.value = true
  try {
    const { data } = await client.get('/email/queue')
    queueItems.value = data
  } catch {
    queueItems.value = []
  } finally {
    queueLoading.value = false
  }
}

async function handleFlushQueue() {
  try {
    await client.post('/email/queue/flush')
    notifications.success('Mail queue flushed.')
    await fetchQueue()
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to flush queue.')
  }
}

function confirmDeleteQueueItem(row) {
  queueItemToDelete.value = row
  showDeleteQueueDialog.value = true
}

async function handleDeleteQueueItem() {
  if (!queueItemToDelete.value || !queueItemToDelete.value.message_id) return
  try {
    await client.delete(`/email/queue/${queueItemToDelete.value.message_id}`)
    queueItems.value = queueItems.value.filter(q => q.message_id !== queueItemToDelete.value.message_id)
    notifications.success('Message removed from queue.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to remove message.')
  } finally {
    queueItemToDelete.value = null
  }
}

// Deliverability
async function runDeliverabilityTest() {
  if (!deliverabilityDomain.value) {
    notifications.error('Please select a domain first.')
    return
  }
  deliverabilityLoading.value = true
  deliverabilityReport.value = null
  try {
    const data = await emailStore.runDeliverabilityTest(deliverabilityDomain.value)
    deliverabilityReport.value = data
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Deliverability test failed.')
  } finally {
    deliverabilityLoading.value = false
  }
}

async function fetchDeliverabilityReport() {
  if (!deliverabilityDomain.value) return
  deliverabilityLoading.value = true
  try {
    const data = await emailStore.fetchDeliverabilityReport(deliverabilityDomain.value)
    deliverabilityReport.value = data
  } catch {
    // No cached report -- that's OK
    deliverabilityReport.value = null
  } finally {
    deliverabilityLoading.value = false
  }
}

function deliverabilityScoreColor(score) {
  if (score >= 80) return 'text-green-400'
  if (score >= 50) return 'text-yellow-400'
  return 'text-red-400'
}

function deliverabilityScoreRingColor(score) {
  if (score >= 80) return '#4ade80'
  if (score >= 50) return '#facc15'
  return '#f87171'
}

function deliverabilityCheckIcon(status) {
  if (status === 'pass') return { symbol: '\u2713', cls: 'text-green-400 bg-green-500/10 border-green-500/30' }
  if (status === 'warn') return { symbol: '!', cls: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30' }
  return { symbol: '\u2717', cls: 'text-red-400 bg-red-500/10 border-red-500/30' }
}

function copyToClipboard(text, label) {
  navigator.clipboard.writeText(text).then(() => {
    copiedRecord.value = label
    setTimeout(() => { copiedRecord.value = '' }, 2000)
  })
}

// ------------------------------------------------------------------
// Mailing List functions
// ------------------------------------------------------------------

function openCreateList() {
  mlCreateForm.value = {
    name: '',
    domain: availableDomains.value[0] || '',
    description: '',
    owner_email: '',
    is_moderated: false,
    reply_to_list: false
  }
  mlShowCreateModal.value = true
}

async function handleCreateList() {
  if (!mlCreateForm.value.name.trim()) {
    notifications.error('List name is required.')
    return
  }
  if (!mlCreateForm.value.owner_email.trim()) {
    notifications.error('Owner email is required.')
    return
  }

  mlCreateSubmitting.value = true
  try {
    // Find domain_id from the selected domain name
    const domains = Array.isArray(domainsStore.domains) ? domainsStore.domains : []
    const domainObj = domains.find(d => (d.domain_name || d.name) === mlCreateForm.value.domain)
    if (!domainObj) {
      notifications.error('Please select a valid domain.')
      return
    }

    await emailStore.createMailingList({
      domain_id: domainObj.id,
      name: mlCreateForm.value.name.trim(),
      description: mlCreateForm.value.description.trim() || null,
      owner_email: mlCreateForm.value.owner_email.trim(),
      is_moderated: mlCreateForm.value.is_moderated,
      reply_to_list: mlCreateForm.value.reply_to_list
    })
    notifications.success(`Mailing list '${mlCreateForm.value.name}@${mlCreateForm.value.domain}' created.`)
    mlShowCreateModal.value = false
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to create mailing list.')
  } finally {
    mlCreateSubmitting.value = false
  }
}

async function openListDetail(ml) {
  try {
    const detail = await emailStore.getMailingList(ml.id)
    mlDetailView.value = detail
    mlShowSettings.value = false
    mlSettingsForm.value = {
      description: detail.description || '',
      owner_email: detail.owner_email || '',
      is_moderated: detail.is_moderated || false,
      archive_enabled: detail.archive_enabled !== false,
      max_message_size_kb: detail.max_message_size_kb || 10240,
      reply_to_list: detail.reply_to_list || false
    }
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to load mailing list details.')
  }
}

async function handleSaveListSettings() {
  if (!mlDetailView.value) return
  mlSettingsSaving.value = true
  try {
    const updated = await emailStore.updateMailingList(mlDetailView.value.id, mlSettingsForm.value)
    // Refresh detail view
    const detail = await emailStore.getMailingList(mlDetailView.value.id)
    mlDetailView.value = detail
    notifications.success('List settings saved.')
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to save settings.')
  } finally {
    mlSettingsSaving.value = false
  }
}

async function toggleListActive(ml) {
  try {
    await emailStore.updateMailingList(ml.id, { is_active: !ml.is_active })
    notifications.success(`List '${ml.list_address}' ${!ml.is_active ? 'activated' : 'deactivated'}.`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to toggle list status.')
  }
}

function confirmDeleteList(ml) {
  mlListToDelete.value = ml
  mlShowDeleteDialog.value = true
}

async function handleDeleteList() {
  if (!mlListToDelete.value) return
  try {
    await emailStore.removeMailingList(mlListToDelete.value.id)
    notifications.success(`Mailing list '${mlListToDelete.value.list_address}' deleted.`)
    mlDetailView.value = null
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to delete mailing list.')
  } finally {
    mlListToDelete.value = null
  }
}

async function handleAddMembers() {
  if (!mlDetailView.value || !mlAddMembersText.value.trim()) {
    notifications.error('Enter at least one email address.')
    return
  }
  mlAddMembersSubmitting.value = true
  try {
    const emails = mlAddMembersText.value
      .split('\n')
      .map(e => e.trim())
      .filter(e => e && e.includes('@'))

    if (emails.length === 0) {
      notifications.error('No valid email addresses found.')
      return
    }

    const added = await emailStore.addListMembers(mlDetailView.value.id, {
      emails,
      is_admin: mlAddMembersAdmin.value
    })

    // Refresh detail view
    const detail = await emailStore.getMailingList(mlDetailView.value.id)
    mlDetailView.value = detail

    notifications.success(`${added.length} member(s) added.`)
    mlShowAddMembers.value = false
    mlAddMembersText.value = ''
    mlAddMembersAdmin.value = false
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to add members.')
  } finally {
    mlAddMembersSubmitting.value = false
  }
}

function confirmRemoveMember(member) {
  mlMemberToRemove.value = member
  mlShowRemoveMemberDialog.value = true
}

async function handleRemoveMember() {
  if (!mlDetailView.value || !mlMemberToRemove.value) return
  try {
    await emailStore.removeListMember(mlDetailView.value.id, mlMemberToRemove.value.id)

    // Refresh detail view
    const detail = await emailStore.getMailingList(mlDetailView.value.id)
    mlDetailView.value = detail

    notifications.success(`Member '${mlMemberToRemove.value.email}' removed.`)
  } catch (err) {
    notifications.error(err.response?.data?.detail || 'Failed to remove member.')
  } finally {
    mlMemberToRemove.value = null
  }
}

watch(activeTab, (tab) => {
  search.value = ''
  mlDetailView.value = null
  if (tab === 'mailboxes') emailStore.fetchMailboxes()
  if (tab === 'aliases') emailStore.fetchAliases()
  if (tab === 'mailing-lists') emailStore.fetchMailingLists()
  if (tab === 'catch-all') fetchCatchAll()
  if (tab === 'filters') emailStore.fetchMailboxes()
  if (tab === 'deliverability') {
    domainsStore.fetchAll()
    const domains = Array.isArray(domainsStore.domains) ? domainsStore.domains : []
    if (domains.length && !deliverabilityDomain.value) {
      deliverabilityDomain.value = domains[0].domain_name || domains[0].name
    }
  }
  if (tab === 'queue') fetchQueue()
})

onMounted(() => {
  emailStore.fetchMailboxes()
  emailStore.fetchAliases()
  domainsStore.fetchAll()
  if (auth.isAdmin) fetchQueue()
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
