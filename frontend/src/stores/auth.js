import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import client from '@/api/client'
import router from '@/router'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(JSON.parse(localStorage.getItem('hosthive_user') || 'null'))
  const tokens = ref(JSON.parse(localStorage.getItem('hosthive_tokens') || '{}'))

  // 2FA partial authentication state
  const partialToken = ref(null)
  const requires2FA = ref(false)

  // Impersonation state
  const impersonating = ref(!!sessionStorage.getItem('hosthive_admin_token'))
  const impersonatedUser = ref(JSON.parse(sessionStorage.getItem('hosthive_impersonated_user') || 'null'))

  const isAuthenticated = computed(() => !!tokens.value.access)
  const isAdmin = computed(() => user.value?.role === 'admin' && !impersonating.value)
  // True for resellers AND admins (admins inherit reseller capabilities)
  const isReseller = computed(() => user.value?.role === 'reseller' || user.value?.role === 'admin')
  // True ONLY for resellers (NOT admins). Use this to render reseller-exclusive UI.
  const isResellerOnly = computed(() => user.value?.role === 'reseller')

  async function login(username, password) {
    const { data } = await client.post('/auth/login', { username, password })

    // If 2FA is required, store partial token and signal the login flow
    if (data.requires_2fa) {
      partialToken.value = data.partial_token
      requires2FA.value = true
      return data
    }

    _setSession(data)
    return data
  }

  async function verify2FA(code, isBackupCode = false) {
    const payload = isBackupCode
      ? { partial_token: partialToken.value, backup_code: code }
      : { partial_token: partialToken.value, code }
    const { data } = await client.post('/auth/2fa/authenticate', payload)
    partialToken.value = null
    requires2FA.value = false
    _setSession(data)
    return data
  }

  async function webauthnLogin(credential) {
    const { data } = await client.post('/auth/webauthn/authenticate', credential)

    // WebAuthn may also require 2FA in some configurations
    if (data.requires_2fa) {
      partialToken.value = data.partial_token
      requires2FA.value = true
      return data
    }

    _setSession(data)
    return data
  }

  function clear2FAState() {
    partialToken.value = null
    requires2FA.value = false
  }

  function _setSession(data) {
    tokens.value = { access: data.access_token, refresh: data.refresh_token }
    user.value = data.user
    localStorage.setItem('hosthive_tokens', JSON.stringify(tokens.value))
    localStorage.setItem('hosthive_user', JSON.stringify(user.value))
  }

  async function logout() {
    try {
      await client.post('/auth/logout', { refresh_token: tokens.value.refresh })
    } catch {
      // Ignore logout API errors
    } finally {
      // Clear impersonation state too
      sessionStorage.removeItem('hosthive_admin_token')
      sessionStorage.removeItem('hosthive_impersonated_user')
      impersonating.value = false
      impersonatedUser.value = null

      tokens.value = {}
      user.value = null
      localStorage.removeItem('hosthive_tokens')
      localStorage.removeItem('hosthive_user')
      router.push({ name: 'login' })
    }
  }

  async function refresh() {
    const { data } = await client.post('/auth/refresh', {
      refresh_token: tokens.value.refresh
    })
    tokens.value = { access: data.access_token, refresh: data.refresh_token }
    localStorage.setItem('hosthive_tokens', JSON.stringify(tokens.value))
    return data
  }

  async function fetchProfile() {
    const { data } = await client.get('/auth/me')
    user.value = data
    localStorage.setItem('hosthive_user', JSON.stringify(data))
    return data
  }

  async function impersonate(userId) {
    if (!userId) throw new Error('User ID is required for impersonation')
    if (!isAdmin.value) throw new Error('Only admins can impersonate users')

    // Store original admin token
    sessionStorage.setItem('hosthive_admin_token', tokens.value.access)

    const { data } = await client.post(`/users/${userId}/impersonate`)

    // Set impersonated user token
    tokens.value = { access: data.access_token, refresh: data.refresh_token || tokens.value.refresh }
    localStorage.setItem('hosthive_tokens', JSON.stringify(tokens.value))

    // Store impersonated user info
    impersonatedUser.value = data.user
    sessionStorage.setItem('hosthive_impersonated_user', JSON.stringify(data.user))

    // Update user ref to impersonated user
    user.value = data.user
    localStorage.setItem('hosthive_user', JSON.stringify(data.user))

    impersonating.value = true

    router.push('/dashboard')
  }

  async function stopImpersonation() {
    const adminToken = sessionStorage.getItem('hosthive_admin_token')
    if (!adminToken) return

    try {
      await client.post('/auth/stop-impersonate')
    } catch {
      // Continue with restoration even if API call fails
    }

    // Restore admin token
    tokens.value = { access: adminToken, refresh: tokens.value.refresh }
    localStorage.setItem('hosthive_tokens', JSON.stringify(tokens.value))

    // Clear impersonation state
    sessionStorage.removeItem('hosthive_admin_token')
    sessionStorage.removeItem('hosthive_impersonated_user')
    impersonating.value = false
    impersonatedUser.value = null

    // Refetch admin profile
    await fetchProfile()

    router.push('/dashboard')
  }

  return {
    user,
    tokens,
    isAuthenticated,
    isAdmin,
    isReseller,
    isResellerOnly,
    impersonating,
    impersonatedUser,
    partialToken,
    requires2FA,
    login,
    verify2FA,
    webauthnLogin,
    clear2FAState,
    logout,
    refresh,
    fetchProfile,
    impersonate,
    stopImpersonation
  }
})
