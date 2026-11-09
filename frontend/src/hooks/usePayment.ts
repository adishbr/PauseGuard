import { useEffect, useRef, useState } from 'react'
import { ApiError, getPayment } from '../services/paymentApi.ts'
import { terminalStatuses } from '../types/payment.ts'
import type { Role } from '../types/payment.ts'

type Snapshot = Awaited<ReturnType<typeof getPayment>>
const pollMs = 1_000

export function usePayment(role: Role, id: string) {
  const [snapshot, setSnapshot] = useState<Snapshot>()
  const [error, setError] = useState<{ message: string; status?: number }>()
  const [checking, setChecking] = useState(true)
  const [retry, setRetry] = useState(0)
  const generation = useRef(0)
  const current = useRef<Snapshot | undefined>(undefined)

  function accept(next: Snapshot) {
    generation.current += 1
    current.current = next
    setSnapshot(next)
    setError(undefined)
    setChecking(false)
  }

  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    let reading = false

    async function poll() {
      if (!active || reading) return
      clearTimeout(timer)
      if (!navigator.onLine) {
        setChecking(false)
        setError({ message: 'You are offline. Reconnect to check payment status.' })
        return
      }

      reading = true
      const started = generation.current
      let retryRead = true
      try {
        const next = await getPayment(role, id)
        if (active && generation.current === started) accept(next)
        retryRead = !terminalStatuses.has((current.current ?? next).payment.status)
      } catch (failure) {
        if (active && generation.current === started) {
          setError({
            message: failure instanceof Error ? failure.message : 'Could not check payment status.',
            status: failure instanceof ApiError ? failure.status : undefined,
          })
          setChecking(false)
        }
        retryRead = !(failure instanceof ApiError && [401, 403, 404].includes(failure.status))
      } finally {
        reading = false
        if (active && retryRead) timer = setTimeout(poll, pollMs)
      }
    }

    function offline() {
      if (current.current && terminalStatuses.has(current.current.payment.status)) return
      generation.current += 1
      clearTimeout(timer)
      setChecking(false)
      setError({ message: 'You are offline. Reconnect to check payment status.' })
    }

    function reconnect() {
      if (!navigator.onLine) return
      if (current.current && terminalStatuses.has(current.current.payment.status)) return
      setChecking(true)
      setRetry((count) => count + 1)
    }

    void poll()
    window.addEventListener('online', reconnect)
    window.addEventListener('offline', offline)
    window.addEventListener('focus', reconnect)
    return () => {
      active = false
      clearTimeout(timer)
      window.removeEventListener('online', reconnect)
      window.removeEventListener('offline', offline)
      window.removeEventListener('focus', reconnect)
    }
  }, [role, id, retry])

  function refresh() {
    setChecking(true)
    setRetry((count) => count + 1)
  }

  return { snapshot, error, checking, accept, refresh }
}
