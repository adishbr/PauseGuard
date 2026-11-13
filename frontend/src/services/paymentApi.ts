import { demoReviewDurationHeader, parseReviewDuration } from '../../mocks/reviewPreference.ts'
import type { ReviewDuration } from '../../mocks/reviewPreference.ts'
import { sessionExpired } from './accountApi.ts'
import { isRealBackendMode } from './backendMode.ts'
import type { MessageKey } from '../locales/en.ts'
import type { Role } from '../types/payment.ts'
import type { CreatePayment, GuardianPayment, PayerPayment } from '../types/payment.ts'
import { parsePayment } from './paymentResponse.ts'

export class ApiError extends Error {
  readonly key: MessageKey
  readonly status: number

  constructor(key: MessageKey, status = 0) {
    super(key)
    this.key = key
    this.status = status
  }
}

export function paymentError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError('requestFailed')
}

function httpError(status: number) {
  if (status === 401 || status === 403) return new ApiError('accessError', status)
  if (status === 404) return new ApiError('notFound', status)
  if (status === 409) return new ApiError('conflict', status)
  if ([400, 413, 422].includes(status)) return new ApiError('invalidRequest', status)
  return new ApiError('requestFailed', status)
}

function isActionAck(payload: unknown, expectedId?: string): payload is { payment_id: string; status: string } {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return false
  const record = payload as Record<string, unknown>
  return (
    typeof record.payment_id === 'string' &&
    typeof record.status === 'string' &&
    (!expectedId || record.payment_id === expectedId)
  )
}

async function fetchRiskReasons(token: string, id: string, signal?: AbortSignal): Promise<string[]> {
  try {
    const response = await fetch(`/api/v2/payments/${encodeURIComponent(id)}/risk`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
      signal,
    })
    if (!response.ok) return []
    const data = (await response.json().catch(() => undefined)) as { reasons?: unknown } | undefined
    if (data && Array.isArray(data.reasons)) {
      return data.reasons.filter((item): item is string => typeof item === 'string')
    }
  } catch {
    // Risk explanation is advisory metadata; do not fail payment retrieval if unavailable.
  }
  return []
}

async function request<R extends Role>(role: R, token: string, path: string, options: {
  body?: object
  id?: string
  signal?: AbortSignal
  demoReviewDuration?: ReviewDuration
} = {}): Promise<{
  payment: R extends 'payer' ? PayerPayment : GuardianPayment
  serverOffset: number
  reviewDuration: ReviewDuration | undefined
}> {
  const { body, id, signal, demoReviewDuration } = options
  const timeout = AbortSignal.timeout(5_000)
  const startedAt = Date.now()
  try {
    const headers = new Headers({ Authorization: `Bearer ${token}` })
    if (body) headers.set('Content-Type', 'application/json')
    if (demoReviewDuration && !isRealBackendMode()) headers.set(demoReviewDurationHeader, String(demoReviewDuration))
    const response = await fetch(`/api/v2${path}`, {
      method: body ? 'POST' : 'GET',
      headers,
      body: body ? JSON.stringify(body) : undefined,
      cache: 'no-store',
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    })
    if (response.status === 401) window.dispatchEvent(new CustomEvent(sessionExpired, { detail: token }))
    if (!response.ok) throw httpError(response.status)

    // HTTP Date has second precision. The midpoint limits skew from request latency.
    const serverDate = Date.parse(response.headers.get('Date') ?? '')
    const measuredOffset = serverDate + 500 - (startedAt + Date.now()) / 2
    const serverOffset = Number.isFinite(measuredOffset) && Math.abs(measuredOffset) >= 1_000 ? measuredOffset : 0
    const payload: unknown = await response.json().catch(() => undefined)
    if (timeout.aborted) throw new ApiError('requestTimeout')

    let payment = parsePayment(payload, role, id)
    if (!payment && body && id && isActionAck(payload, id)) {
      return await request(role, token, paymentPath(id), { id, signal })
    }
    if (!payment) throw new ApiError('invalidResponse')

    if (
      isRealBackendMode() &&
      role === 'payer' &&
      'reason_codes' in payment &&
      payment.reason_codes.length === 0 &&
      payment.tier > 0
    ) {
      const reasons = await fetchRiskReasons(token, payment.id, signal)
      if (reasons.length > 0) {
        payment = { ...payment, reason_codes: reasons }
      }
    }

    const reviewDuration = parseReviewDuration(response.headers.get(demoReviewDurationHeader))
    return { payment: payment as R extends 'payer' ? PayerPayment : GuardianPayment, serverOffset, reviewDuration }
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError(timeout.aborted ? 'requestTimeout' : 'networkError')
  }
}

const paymentPath = (id: string) => `/payments/${encodeURIComponent(id)}`

export const createPayment = (token: string, input: CreatePayment, demoReviewDuration: ReviewDuration) =>
  request('payer', token, '/payments', { body: input, demoReviewDuration })

export const getPayment = (role: Role, token: string, id: string, signal: AbortSignal) =>
  request(role, token, paymentPath(id), { id, signal })

export const payerAction = (token: string, id: string, action: 'warning/acknowledge' | 'cancel' | 'confirm') =>
  request('payer', token, `${paymentPath(id)}/${action}`, {
    id, body: action === 'confirm' ? { idempotency_key: `confirm:${id}` } : {},
  })

export const activateFallback = (token: string, id: string) =>
  request('payer', token, `${paymentPath(id)}/fallback/activate`, { id, body: {} })

export const guardianDecision = (token: string, id: string, decision: 'approve' | 'reject') =>
  request('guardian', token, `${paymentPath(id)}/guardian/decision`, {
    id,
    body: isRealBackendMode() ? { approved: decision === 'approve' } : { decision },
  })
