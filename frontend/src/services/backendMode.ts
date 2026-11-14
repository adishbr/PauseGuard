/**
 * Runtime mode helpers distinguishing standalone local mock mode from
 * FastAPI real-backend integration mode (`VITE_USE_REAL_BACKEND=true`).
 */
export const API_TIMEOUT_MS = 45_000

export function isRealBackendMode(): boolean {
  try {
    return import.meta.env?.VITE_USE_REAL_BACKEND === 'true'
  } catch {
    return false
  }
}

export function apiBaseUrl(): string {
  try {
    const raw = import.meta.env?.VITE_API_BASE_URL
    return typeof raw === 'string' ? raw.trim().replace(/\/+$/, '') : ''
  } catch {
    return ''
  }
}

export function apiUrl(path: string): string {
  const base = apiBaseUrl()
  return base ? `${base}${path}` : path
}

export function apiWsUrl(pathAndQuery: string): string {
  const base = apiBaseUrl()
  if (base) {
    const wsBase = base.replace(/^https:/i, 'wss:').replace(/^http:/i, 'ws:')
    return `${wsBase}${pathAndQuery}`
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${pathAndQuery}`
}

export function isLoopbackHost(): boolean {
  if (typeof window === 'undefined') return false
  const host = window.location.hostname
  return host === 'localhost' || host === '127.0.0.1' || host === '::1' || host === '[::1]'
}
