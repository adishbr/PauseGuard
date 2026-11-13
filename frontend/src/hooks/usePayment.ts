import { useCallback, useEffect, useRef, useState } from 'react'
import { sessionExpired } from '../services/accountApi.ts'
import { isRealBackendMode } from '../services/backendMode.ts'
import { ApiError, getPayment, issueWsTicket, paymentError } from '../services/paymentApi.ts'
import { terminalStatuses } from '../types/payment.ts'
import type { Role } from '../types/payment.ts'

type Snapshot = Awaited<ReturnType<typeof getPayment>>
const pollMs = 1_000
const wsSafetyPollMs = 10_000
const wsPingMs = 25_000
const maxWsRetries = 5

function buildWebSocketUrl(ticket: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/api/v2/ws?ticket=${encodeURIComponent(ticket)}`
}

export function usePayment(role: Role, token: string, id: string) {
  const [snapshot, setSnapshot] = useState<Snapshot>()
  const [error, setError] = useState<ApiError>()
  const [checking, setChecking] = useState(true)
  const [retry, setRetry] = useState(0)
  const generation = useRef(0)
  const current = useRef<Snapshot | undefined>(undefined)

  const accept = useCallback((next: Snapshot) => {
    const previous = current.current?.payment
    if (previous && 'version' in previous && 'version' in next.payment && next.payment.version < previous.version) return
    generation.current += 1
    current.current = next
    setSnapshot(next)
    setError(undefined)
    setChecking(false)
  }, [])

  const refresh = useCallback(() => {
    generation.current += 1
    setChecking(true)
    setRetry((count) => count + 1)
  }, [])

  useEffect(() => {
    let active = true
    let authRevoked = false
    let timer: ReturnType<typeof setTimeout>
    let wsRetryTimer: ReturnType<typeof setTimeout>
    let heartbeatTimer: ReturnType<typeof setInterval>
    let request: AbortController | undefined
    let socket: WebSocket | undefined
    let wsConnected = false
    let wsConnecting = false
    let wsFailures = 0
    let failures = 0

    function isTerminal(): boolean {
      return Boolean(current.current && terminalStatuses.has(current.current.payment.status))
    }

    function stopWebSocket() {
      clearTimeout(wsRetryTimer)
      clearInterval(heartbeatTimer)
      wsConnected = false
      wsConnecting = false
      if (socket) {
        socket.onopen = null
        socket.onmessage = null
        socket.onerror = null
        socket.onclose = null
        socket.close()
        socket = undefined
      }
    }

    async function poll() {
      if (!active || authRevoked || request || isTerminal()) return
      if (!navigator.onLine) {
        offline()
        return
      }

      const controller = new AbortController()
      request = controller
      const started = generation.current
      let retryRead = true
      try {
        const next = await getPayment(role, token, id, controller.signal)
        if (active && !controller.signal.aborted && generation.current === started) accept(next)
        failures = 0
      } catch (failure) {
        if (active && !controller.signal.aborted && generation.current === started) {
          const problem = paymentError(failure)
          setError(problem)
          setChecking(false)
          failures += 1
          retryRead = ![401, 403, 404].includes(problem.status)
          if (!retryRead) {
            if (problem.status === 401 || problem.status === 403) authRevoked = true
            stopWebSocket()
            current.current = undefined
            setSnapshot(undefined)
          }
        }
      } finally {
        if (request === controller) request = undefined
        if (active && !authRevoked && retryRead && navigator.onLine && !controller.signal.aborted && !isTerminal()) {
          const interval = wsConnected ? wsSafetyPollMs : pollMs * 2 ** Math.min(failures, 3)
          timer = setTimeout(poll, interval)
        }
      }
    }

    async function connectWebSocket() {
      if (!active || authRevoked || !isRealBackendMode() || !token || isTerminal() || !navigator.onLine) return
      if (typeof WebSocket === 'undefined') return
      if (wsConnecting || (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING))) return

      wsConnecting = true
      try {
        const ticketRes = await issueWsTicket(token)
        if (!active || authRevoked || isTerminal() || !navigator.onLine) return
        const ws = new WebSocket(buildWebSocketUrl(ticketRes.ticket))
        socket = ws

        ws.onopen = () => {
          if (!active || socket !== ws) return
          wsConnected = true
          wsFailures = 0
          clearInterval(heartbeatTimer)
          heartbeatTimer = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'PING' }))
            }
          }, wsPingMs)
        }

        ws.onmessage = (event) => {
          if (!active || socket !== ws) return
          try {
            const data = JSON.parse(String(event.data)) as { type?: string; payment_id?: string }
            if (data.type === 'PONG' || data.type === 'CONNECTION_ESTABLISHED') return
            if (data.payment_id === id) {
              clearTimeout(timer)
              void poll()
            }
          } catch {
            // Ignore malformed frames
          }
        }

        ws.onerror = () => {
          // Close handler manages bounded reconnect; HTTP polling fallback remains active.
        }

        ws.onclose = (event) => {
          if (socket === ws) socket = undefined
          wsConnected = false
          clearInterval(heartbeatTimer)
          // 1008 = policy violation (invalid/expired ticket); do not reconnect automatically without re-ticket.
          if (event.code === 1008) {
            return
          }
          if (!active || authRevoked || isTerminal() || !navigator.onLine) return
          wsFailures += 1
          if (wsFailures > maxWsRetries) return
          const delay = Math.min(10_000, 1_000 * 2 ** (wsFailures - 1))
          clearTimeout(wsRetryTimer)
          wsRetryTimer = setTimeout(() => void connectWebSocket(), delay)
        }
      } catch (err) {
        wsConnected = false
        const statusCode = err instanceof ApiError ? err.status : 0
        if (statusCode === 401 || statusCode === 403) {
          authRevoked = true
        }
      } finally {
        wsConnecting = false
      }
    }

    function handleSessionExpired(event: Event) {
      if ((event as CustomEvent<string>).detail === token) {
        authRevoked = true
        clearTimeout(timer)
        request?.abort()
        stopWebSocket()
      }
    }

    function offline() {
      if (isTerminal()) return
      generation.current += 1
      clearTimeout(timer)
      request?.abort()
      stopWebSocket()
      setChecking(false)
      setError(new ApiError('offline'))
    }

    function reconnect() {
      if (!navigator.onLine || authRevoked || isTerminal()) return
      wsFailures = 0
      void connectWebSocket()
      refresh()
    }

    void poll()
    void connectWebSocket()
    window.addEventListener(sessionExpired, handleSessionExpired)
    window.addEventListener('online', reconnect)
    window.addEventListener('offline', offline)
    window.addEventListener('focus', reconnect)
    return () => {
      active = false
      request?.abort()
      clearTimeout(timer)
      stopWebSocket()
      window.removeEventListener(sessionExpired, handleSessionExpired)
      window.removeEventListener('online', reconnect)
      window.removeEventListener('offline', offline)
      window.removeEventListener('focus', reconnect)
    }
  }, [accept, refresh, role, token, id, retry])

  return { snapshot, error, checking, accept, refresh }
}
