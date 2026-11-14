/**
 * Admin API service layer.
 *
 * Mode A (Mock UPI):
 *  - Admin sessions NEVER call /api/v2/payments directly as a payer.
 *  - Admin calls isolated mock-admin endpoints (/__pauseguard/demo/admin/*) with the admin token
 *    to obtain an explicitly authorized synthetic test-payer context and read synthetic audit evidence.
 *  - Payment execution still passes through the canonical /api/v2/payments endpoints under that
 *    synthetic payer context, preserving Safe-Lock, warnings, guardian review, and confirmation.
 *
 * Mode B (Razorpay Test Mode):
 *  - Admin-only isolated merchant sandbox connected to /api/v2/sandbox/razorpay/*.
 *  - Uses only backend-supplied public Test Mode keys (rzp_test_*); rejects rzp_live_* fail-closed.
 *  - Server-side HMAC signature verification & provider reconciliation are required before verified state.
 *  - Completely decoupled from PauseGuard P2P / Mock UPI payment state and ledger.
 *
 * Security invariants:
 *  - Razorpay key_secret must NEVER appear in this file or any frontend source.
 *  - Signature verification is performed server-side only.
 *  - Client-side Razorpay callbacks are forwarded to the backend for verification.
 *  - Payment state is never updated based on a client-only success signal.
 */

import { demoAccountPath } from '../types/account.ts'
import type { DemoSession } from '../types/account.ts'
import type {
  AdminAuditResponse,
  AuditVerifyResult,
  RazorpayConfigResult,
  RazorpayOrderStatusResult,
} from '../types/admin.ts'
import { AccountError, sessionExpired } from './accountApi.ts'
import { API_TIMEOUT_MS, apiUrl, isRealBackendMode } from './backendMode.ts'

export class AdminApiError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'AdminApiError'
  }
}

export {
  ApiError,
  createPayment as adminCreatePayment,
  getPayment as adminGetPayment,
  payerAction as adminPayerAction,
  paymentError,
} from './paymentApi.ts'

async function adminRequest<T>(
  url: string,
  adminToken: string,
  body?: object,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const headers = new Headers({ Authorization: `Bearer ${adminToken}` })
  if (body) headers.set('Content-Type', 'application/json')
  if (extraHeaders) {
    for (const [k, v] of Object.entries(extraHeaders)) headers.set(k, v)
  }

  let response: Response
  try {
    const targetUrl = url.startsWith('/api/') ? apiUrl(url) : url
    response = await fetch(targetUrl, {
      method: body ? 'POST' : 'GET',
      headers,
      body: body ? JSON.stringify(body) : undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
    })
  } catch {
    throw new AccountError(0, 'Demo service unavailable. Check your connection and try again.')
  }

  const data = await response.json().catch(() => undefined)
  if (response.status === 401 && adminToken && typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(sessionExpired, { detail: adminToken }))
  }
  if (!response.ok || !data) {
    const fallbackMessage =
      response.status === 404 && url.startsWith('/__pauseguard/demo')
        ? 'Demo service endpoint is not available on this host. Run locally with Vite mock middleware or configure the FastAPI backend.'
        : 'Admin service could not complete this action.'
    throw new AccountError(
      response.status,
      typeof data?.detail === 'string' ? data.detail : fallbackMessage,
    )
  }
  return data as T
}

export const adminMockApi = {
  /**
   * Obtains or updates the explicitly authorized synthetic payer session for admin Mode A testing.
   * Requires a valid admin bearer token; rejected (403) for payer/guardian tokens.
   */
  getSyntheticPayerSession: async (adminToken: string, safeLock?: boolean) => {
    if (isRealBackendMode()) {
      throw new AccountError(
        501,
        'Synthetic admin test-payer minting is only available in local mock mode. Sign in with a payer account or bearer token in real-backend mode.',
      )
    }
    return adminRequest<DemoSession>(`${demoAccountPath}/admin/test-payer`, adminToken,
      typeof safeLock === 'boolean' ? { safeLock } : {})
  },

  /**
   * Fetches synthetic test payments and hash-chained audit events created in the admin sandbox.
   * Requires a valid admin bearer token.
   */
  getAudit: async (adminToken: string, paymentId?: string): Promise<AdminAuditResponse> => {
    if (isRealBackendMode()) {
      if (!paymentId) return { payments: [], events: [] }
      const events = await adminRequest<AdminAuditResponse['events']>(
        `/api/v2/payments/${encodeURIComponent(paymentId)}/events`,
        adminToken,
      )
      return { payments: [], events: Array.isArray(events) ? events : [] }
    }
    const query = paymentId ? `?paymentId=${encodeURIComponent(paymentId)}` : ''
    return adminRequest<AdminAuditResponse>(`${demoAccountPath}/admin/audit${query}`, adminToken)
  },

  /**
   * Verifies the local mock audit hash chain via GET /api/v2/audit/verify (Admin-only).
   */
  verifyAuditChain: (adminToken: string) =>
    adminRequest<AuditVerifyResult>('/api/v2/audit/verify', adminToken),
}

// ---------------------------------------------------------------------------
// Mode B — Razorpay Test Mode
// ---------------------------------------------------------------------------

export const RAZORPAY_CHECKOUT_SCRIPT_URL = 'https://checkout.razorpay.com/v1/checkout.js'

export interface RazorpayOrderCreateOptions {
  receipt?: string
  notes?: Record<string, string>
  idempotencyKey?: string
}

export interface RazorpayOrderResult {
  id: string
  razorpay_order_id: string
  amount_paise: number
  currency: string
  status: string
  receipt?: string | null
  key_id: string
  created_at: string
}

export interface RazorpayVerifyResult {
  verified: boolean
  status: string
  order_id: string
  razorpay_order_id: string
  razorpay_payment_id: string
  amount_paise: number
  currency: string
  reconciled_with_provider: boolean
  verified_at: string
}

/**
 * Validates that a Razorpay key ID is strictly a Test Mode public key (`rzp_test_*`).
 * Rejects live keys (`rzp_live_*`), empty strings, and unexpected formats fail-closed.
 */
export function validateRazorpayTestKey(keyId: unknown): string {
  if (typeof keyId !== 'string') {
    throw new AdminApiError('Razorpay Test Mode public key is missing.')
  }
  const trimmed = keyId.trim()
  if (trimmed.startsWith('rzp_live_')) {
    throw new AdminApiError('Security block: live Razorpay keys (rzp_live_*) are strictly prohibited.')
  }
  if (!trimmed.startsWith('rzp_test_') || trimmed.length <= 'rzp_test_'.length) {
    throw new AdminApiError('Invalid Razorpay key format: only Test Mode keys (rzp_test_*) are allowed.')
  }
  return trimmed
}

let razorpayScriptPromise: Promise<void> | null = null

/**
 * Dynamically loads the Razorpay Checkout SDK only when an admin initiates Test Mode checkout.
 * Rejects cleanly if offline, blocked, or running outside a browser document context.
 */
export function loadRazorpayCheckoutScript(scriptUrl = RAZORPAY_CHECKOUT_SCRIPT_URL): Promise<void> {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return Promise.reject(new AdminApiError('Razorpay Checkout requires a browser environment.'))
  }
  const win = window as unknown as { Razorpay?: unknown }
  if (typeof win.Razorpay === 'function') {
    return Promise.resolve()
  }
  if (razorpayScriptPromise) return razorpayScriptPromise

  razorpayScriptPromise = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${scriptUrl}"]`)
    if (existing) {
      if (typeof win.Razorpay === 'function') {
        resolve()
        return
      }
      existing.addEventListener('load', () => resolve(), { once: true })
      existing.addEventListener('error', () => {
        razorpayScriptPromise = null
        reject(new AdminApiError('Could not load Razorpay Checkout SDK from checkout.razorpay.com.'))
      }, { once: true })
      return
    }

    const script = document.createElement('script')
    script.src = scriptUrl
    script.async = true
    script.onload = () => {
      if (typeof win.Razorpay === 'function') {
        resolve()
      } else {
        razorpayScriptPromise = null
        reject(new AdminApiError('Razorpay Checkout SDK loaded without exposing window.Razorpay.'))
      }
    }
    script.onerror = () => {
      script.remove()
      razorpayScriptPromise = null
      reject(new AdminApiError('Could not load Razorpay Checkout SDK. Check network access to checkout.razorpay.com.'))
    }
    document.head.appendChild(script)
  })
  return razorpayScriptPromise
}

export const razorpayApi = {
  /**
   * Retrieves the Razorpay Test Mode availability and public key_id (Admin only).
   * key_secret and webhook_secret are never returned to the frontend.
   */
  getConfig: async (token: string, baseUrl = ''): Promise<RazorpayConfigResult> => {
    const result = await adminRequest<RazorpayConfigResult>(
      `${baseUrl}/api/v2/sandbox/razorpay/config`,
      token,
    )
    if (!result.enabled || result.mode !== 'test') {
      throw new AdminApiError('Razorpay Test Mode sandbox is currently disabled on the backend.')
    }
    const safeKeyId = validateRazorpayTestKey(result.key_id)
    return {
      enabled: true,
      mode: 'test',
      key_id: safeKeyId,
    }
  },

  /**
   * Creates an isolated Razorpay test merchant order via POST /api/v2/sandbox/razorpay/orders (Admin only).
   */
  createOrder: async (
    token: string,
    amountPaise: number,
    options?: RazorpayOrderCreateOptions | Record<string, string>,
    baseUrl = '',
  ): Promise<RazorpayOrderResult> => {
    const isStructured =
      options &&
      ('receipt' in options || 'notes' in options || 'idempotencyKey' in options)
    const opts: RazorpayOrderCreateOptions = isStructured
      ? (options as RazorpayOrderCreateOptions)
      : { notes: options as Record<string, string> | undefined }

    const body: Record<string, unknown> = {
      amount_paise: amountPaise,
      currency: 'INR',
    }
    if (opts.receipt) body.receipt = opts.receipt
    if (opts.notes && Object.keys(opts.notes).length > 0) body.notes = opts.notes
    if (opts.idempotencyKey) body.idempotency_key = opts.idempotencyKey

    const headers = opts.idempotencyKey ? { 'Idempotency-Key': opts.idempotencyKey } : undefined
    const order = await adminRequest<RazorpayOrderResult>(
      `${baseUrl}/api/v2/sandbox/razorpay/orders`,
      token,
      body,
      headers,
    )
    return {
      ...order,
      key_id: validateRazorpayTestKey(order.key_id),
    }
  },

  /**
   * Verifies checkout payment signature via POST /api/v2/sandbox/razorpay/verify (Admin only).
   * HMAC signature verification and provider reconciliation happen server-side only.
   */
  verifyPayment: async (
    token: string,
    payload: { razorpay_payment_id: string; razorpay_order_id: string; razorpay_signature: string },
    baseUrl = '',
  ): Promise<RazorpayVerifyResult> => {
    return adminRequest<RazorpayVerifyResult>(
      `${baseUrl}/api/v2/sandbox/razorpay/verify`,
      token,
      payload,
    )
  },

  /**
   * Fetches stored merchant order and payment history via GET /api/v2/sandbox/razorpay/orders/{order_id} (Admin only).
   */
  getOrderStatus: async (token: string, orderId: string, baseUrl = ''): Promise<RazorpayOrderStatusResult> => {
    return adminRequest<RazorpayOrderStatusResult>(
      `${baseUrl}/api/v2/sandbox/razorpay/orders/${encodeURIComponent(orderId)}`,
      token,
    )
  },
}

export interface PolicyLabSimulationResult {
  seed: number
  dataset_split: string
  total_scenarios_evaluated: number
  evaluation_latency_ms: number
  is_synthetic: boolean
  declaration: string
  calibration?: {
    baseline_a_threshold_paise: number
    personal_deviation_threshold: number
    business_deviation_threshold: number
  }
  policy_metrics: Record<string, {
    policy_name: string
    total_scenarios: number
    friction_cost_score?: number
    precision: { rate: number | null; numerator: number; denominator: number }
    recall: { rate: number | null; numerator: number; denominator: number }
    false_positive_rate: { rate: number | null; numerator: number; denominator: number }
    business_disruption_rate: { rate: number | null; numerator: number; denominator: number }
  }>
  scam_category_breakdown?: Record<string, {
    total: number
    policies: Record<string, { flagged_count: number; flag_rate: number | null }>
  }>
}

export const policyLabApi = {
  simulate: async (
    token: string,
    payload: {
      sample_size: number
      seed: number
      baseline_a_threshold_paise: number
      personal_deviation_threshold?: number
      business_deviation_threshold?: number
    },
    baseUrl = '',
  ): Promise<PolicyLabSimulationResult> => {
    return adminRequest<PolicyLabSimulationResult>(
      `${baseUrl}/api/v2/policy-lab/simulate`,
      token,
      payload,
    )
  },
}
