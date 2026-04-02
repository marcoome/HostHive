import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true }
  },
  {
    path: '/forgot-password',
    name: 'forgot-password',
    component: () => import('@/views/ForgotPasswordView.vue'),
    meta: { public: true }
  },
  {
    path: '/',
    component: () => import('@/components/AppLayout.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue')
      },
      {
        path: 'domains',
        name: 'domains',
        component: () => import('@/views/DomainsView.vue')
      },
      {
        path: 'domains/:id',
        name: 'domain-detail',
        component: () => import('@/views/DomainDetailView.vue')
      },
      {
        path: 'databases',
        name: 'databases',
        component: () => import('@/views/DatabasesView.vue')
      },
      {
        path: 'email',
        name: 'email',
        component: () => import('@/views/EmailView.vue')
      },
      {
        path: 'dns',
        name: 'dns',
        component: () => import('@/views/DnsView.vue')
      },
      {
        path: 'dns/:id',
        name: 'dns-zone-detail',
        component: () => import('@/views/DnsZoneDetailView.vue')
      },
      {
        path: 'ftp',
        name: 'ftp',
        component: () => import('@/views/FtpView.vue')
      },
      {
        path: 'cron',
        name: 'cron',
        component: () => import('@/views/CronView.vue')
      },
      {
        path: 'ssl',
        name: 'ssl',
        component: () => import('@/views/SslView.vue')
      },
      {
        path: 'backups',
        name: 'backups',
        component: () => import('@/views/BackupsView.vue')
      },
      {
        path: 'files',
        name: 'files',
        component: () => import('@/views/FileManagerView.vue')
      },
      {
        path: 'packages',
        name: 'packages',
        component: () => import('@/views/PackagesView.vue'),
        meta: { admin: true }
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('@/views/UsersView.vue'),
        meta: { admin: true }
      },
      {
        path: 'users/:id',
        name: 'user-detail',
        component: () => import('@/views/UserDetailView.vue'),
        meta: { admin: true }
      },
      {
        path: 'server',
        name: 'server',
        component: () => import('@/views/ServerView.vue'),
        meta: { admin: true }
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SettingsView.vue')
      },
      {
        path: 'integrations',
        name: 'integrations',
        component: () => import('@/views/IntegrationsView.vue'),
        meta: { admin: true }
      },
      {
        path: 'audit-log',
        name: 'audit-log',
        component: () => import('@/views/AuditLogView.vue'),
        meta: { admin: true }
      },
      {
        path: 'api-keys',
        name: 'api-keys',
        component: () => import('@/views/ApiKeysView.vue')
      },
      {
        path: 'ai',
        name: 'ai',
        component: () => import('@/views/AiDashboardView.vue')
      },
      {
        path: 'docker',
        name: 'docker',
        component: () => import('@/views/DockerView.vue')
      },
      {
        path: 'wordpress',
        name: 'wordpress',
        component: () => import('@/views/WordPressView.vue')
      },
      {
        path: 'monitoring',
        name: 'monitoring',
        component: () => import('@/views/MonitoringView.vue'),
        meta: { admin: true }
      },
      {
        path: 'settings/mcp',
        name: 'settings-mcp',
        component: () => import('@/views/McpSettingsView.vue'),
        meta: { admin: true }
      },
      {
        path: 'settings/ai',
        name: 'settings-ai',
        component: () => import('@/views/AiSettingsView.vue'),
        meta: { admin: true }
      },
      {
        path: 'reseller',
        name: 'reseller-dashboard',
        component: () => import('@/views/ResellerDashboardView.vue'),
        meta: { reseller: true }
      },
      {
        path: 'reseller/users',
        name: 'reseller-users',
        component: () => import('@/views/ResellerUsersView.vue'),
        meta: { reseller: true }
      },
      {
        path: 'reseller/branding',
        name: 'reseller-branding',
        component: () => import('@/views/ResellerBrandingView.vue'),
        meta: { reseller: true }
      }
    ]
  },
  {
    path: '/status',
    name: 'status',
    component: () => import('@/views/StatusPageView.vue'),
    meta: { public: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  const auth = useAuthStore()

  if (to.meta.public) {
    if (auth.isAuthenticated && to.name === 'login') {
      return next('/dashboard')
    }
    return next()
  }

  if (!auth.isAuthenticated) {
    return next({ name: 'login', query: { redirect: to.fullPath } })
  }

  if (to.meta.admin && !auth.isAdmin) {
    return next('/dashboard')
  }

  if (to.meta.reseller && !auth.isReseller) {
    return next('/dashboard')
  }

  next()
})

export default router
