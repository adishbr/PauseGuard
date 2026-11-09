import { demoTokens } from '../../mocks/scenarios.ts'
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

async function request<R extends Role>(role: R, path: string, options: {
  body?: object
  id?: string
  signal?: AbortSignal
} = {}) {
  const { body, id, signal } = options
  const timeout = AbortSignal.timeout(5_000)
  const startedAt = Date.now()
  try {
    const headers = new Headers({ Authorization: `Bearer ${demoTokens[role]}` })
    if (body) headers.set('Content-Type', 'application/json')
    const response = await fetch(`/api/v2${path}`, {
      method: body ? 'POST' : 'GET',
      headers,
      body: body ? JSON.stringify(body) : undefined,
      cache: 'no-store',
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    })
    if (!response.ok) throw httpError(response.status)

    // HTTP Date has second precision. The midpoint limits skew from request latency.
    const serverDate = Date.parse(response.headers.get('Date') ?? '')
    const measuredOffset = serverDate + 500 - (startedAt + Date.now()) / 2
    const serverOffset = Number.isFinite(measuredOffset) && Math.abs(measuredOffset) >= 1_000 ? measuredOffset : 0
    const payload: unknown = await response.json().catch(() => undefined)
    if (timeout.aborted) throw new ApiError('requestTimeout')
    const payment = parsePayment(payload, role, id)
    if (!payment) throw new ApiError('invalidResponse')
    return { payment: payment as R extends 'payer' ? PayerPayment : GuardianPayment, serverOffset }
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError(timeout.aborted ? 'requestTimeout' : 'networkError')
  }
}

const paymentPath = (id: string) => `/payments/${encodeURIComponent(id)}`

export const createPayment = (input: CreatePayment) => request('payer', '/payments', { body: input })
export const getPayment = (role: Role, id: string, signal: AbortSignal) => request(role, paymentPath(id), { id, signal })
export const payerAction = (id: string, action: 'warning/acknowledge' | 'cancel' | 'confirm') =>
  request('payer', `${paymentPath(id)}/${action}`, {
    id, body: action === 'confirm' ? { idempotency_key: `confirm:${id}` } : {},
  })
export const guardianDecision = (id: string, decision: 'approve' | 'reject') =>
  request('guardian', `${paymentPath(id)}/guardian/decision`, { id, body: { decision } })
