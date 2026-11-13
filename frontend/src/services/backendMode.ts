/**
 * Runtime mode helpers distinguishing standalone local mock mode from
 * FastAPI real-backend integration mode (`VITE_USE_REAL_BACKEND=true`).
 */
export function isRealBackendMode(): boolean {
  try {
    return import.meta.env?.VITE_USE_REAL_BACKEND === 'true'
  } catch {
    return false
  }
}

export function isLoopbackHost(): boolean {
  if (typeof window === 'undefined') return false
  const host = window.location.hostname
  return host === 'localhost' || host === '127.0.0.1' || host === '::1' || host === '[::1]'
}
