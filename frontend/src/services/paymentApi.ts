import { demoTokens } from '../../mocks/scenarios.ts'
import type { CreatePayment, GuardianPayment, PayerPayment, Role } from '../types/payment.ts'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(role: Role, path: string, body?: object) {
  const signal = AbortSignal.timeout(5_000)
  const startedAt = Date.now()
  try {
    const headers = new Headers({ Authorization: `Bearer ${demoTokens[role]}` })
    if (body) headers.set('Content-Type', 'application/json')
    const response = await fetch(`/api/v2${path}`, {
      method: body ? 'POST' : 'GET',
      headers,
      body: body ? JSON.stringify(body) : undefined,
      cache: 'no-store',
      signal,
    })
    const serverDate = Date.parse(response.headers.get('Date') ?? '')
    // The local fixture emits a standard HTTP Date header (whole seconds).
    const measuredOffset = serverDate - startedAt
    const serverOffset = Number.isFinite(measuredOffset) && Math.abs(measuredOffset) >= 1_000 ? measuredOffset : 0
    const payload = await response.json()
    if (!response.ok) {
      throw new ApiError(typeof payload.detail === 'string' ? payload.detail : 'The request could not be completed.', response.status)
    }
    return { payment: payload as T, serverOffset }
  } catch (error) {
    if (error instanceof ApiError) throw error
    const message = signal.aborted ? 'The request timed out. Retry to check what happened.' :
      'The demo API is unavailable. Reconnect to check payment status.'
    throw new ApiError(message, 0)
  }
}

const paymentPath = (id: string) => `/payments/${encodeURIComponent(id)}`

export const createPayment = (input: CreatePayment) => request<PayerPayment>('payer', '/payments', input)
export const getPayment = (role: Role, id: string) => request<PayerPayment | GuardianPayment>(role, paymentPath(id))
export const payerAction = (id: string, action: 'warning/acknowledge' | 'cancel' | 'confirm') =>
  request<PayerPayment>('payer', `${paymentPath(id)}/${action}`, action === 'confirm' ? { idempotency_key: `confirm:${id}` } : {})
export const guardianDecision = (id: string, decision: 'approve' | 'reject') =>
  request<GuardianPayment>('guardian', `${paymentPath(id)}/guardian/decision`, { decision })
