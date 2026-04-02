import axios from 'axios'
import router from '@/router'

const client = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json'
  }
})

let isRefreshing = false
let failedQueue = []

function processQueue(error, token = null) {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) {
      reject(error)
    } else {
      resolve(token)
    }
  })
  failedQueue = []
}

client.interceptors.request.use((config) => {
  const tokens = JSON.parse(localStorage.getItem('hosthive_tokens') || '{}')
  if (tokens.access) {
    config.headers.Authorization = `Bearer ${tokens.access}`
  }
  return config
})

client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`
          return client(originalRequest)
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const tokens = JSON.parse(localStorage.getItem('hosthive_tokens') || '{}')
        if (!tokens.refresh) throw new Error('No refresh token')

        const { data } = await axios.post('/api/v1/auth/refresh', {
          refresh_token: tokens.refresh
        })

        const newTokens = { access: data.access_token, refresh: data.refresh_token }
        localStorage.setItem('hosthive_tokens', JSON.stringify(newTokens))

        processQueue(null, data.access_token)
        originalRequest.headers.Authorization = `Bearer ${data.access_token}`
        return client(originalRequest)
      } catch (refreshError) {
        processQueue(refreshError, null)
        localStorage.removeItem('hosthive_tokens')
        localStorage.removeItem('hosthive_user')
        router.push({ name: 'login' })
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    return Promise.reject(error)
  }
)

export default client
