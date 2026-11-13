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
 *  - All functions are stubs that reject with AdminApiError until Komal's FastAPI backend
 *    provides the required sandbox endpoints.
 *
 * Security invariants:
 *  - Razorpay key_secret must NEVER appear in this file or any frontend source.
 *  - Signature verification is performed server-side only.
 *  - Client-side Razorpay callbacks are forwarded to the backend for verification.
 *  - Payment state is never updated based on a client-only success signal.
 */

import { demoAccountPath } from '../types/account.ts'
import type { DemoSession } from '../types/account.ts'
import type { AdminAuditResponse, AuditVerifyResult } from '../types/admin.ts'
import { AccountError, sessionExpired } from './accountApi.ts'
import { isRealBackendMode } from './backendMode.ts'

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

async function adminRequest<T>(url: string, adminToken: string, body?: object): Promise<T> {
  const headers = new Headers({ Authorization: `Bearer ${adminToken}` })
  if (body) headers.set('Content-Type', 'application/json')

  let response: Response
  try {
    response = await fetch(url, {
      method: body ? 'POST' : 'GET',
      headers,
      body: body ? JSON.stringify(body) : undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(5_000),
    })
  } catch {
    throw new AccountError(0, 'Demo service unavailable. Check your connection and try again.')
  }

  const data = await response.json().catch(() => undefined)
  if (response.status === 401 && adminToken) {
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

export interface RazorpayOrderResult {
  id: string
  razorpay_order_id: string
  amount_paise: number
  currency: string
  status: string
  receipt?: string | null
  key_id?: string
  created_at: string
}

export interface RazorpayVerifyResult {
  order_id: string
  razorpay_order_id: string
  razorpay_payment_id: string
  status: string
  amount_paise: number
  currency: string
}

export const razorpayApi = {
  /**
   * Creates an isolated Razorpay test merchant order via POST /api/v2/sandbox/razorpay/orders (Admin only).
   */
  createOrder: async (token: string, amountPaise: number, notes?: Record<string, string>): Promise<RazorpayOrderResult> => {
    return adminRequest<RazorpayOrderResult>('/api/v2/sandbox/razorpay/orders', token, {
      amount_paise: amountPaise,
      currency: 'INR',
      notes,
    })
  },

  /**
   * Retrieves the Razorpay public test key_id (Admin only).
   * key_secret is never sent to the frontend.
   */
  getConfig: async (_token: string): Promise<{ key_id: string }> => {
    return { key_id: 'rzp_test_mock_key' }
  },

  /**
   * Verifies checkout payment signature via POST /api/v2/sandbox/razorpay/verify (Admin only).
   * HMAC signature verification happens server-side only.
   */
  verifyPayment: async (
    token: string,
    payload: { razorpay_payment_id: string; razorpay_order_id: string; razorpay_signature: string },
  ): Promise<RazorpayVerifyResult> => {
    return adminRequest<RazorpayVerifyResult>('/api/v2/sandbox/razorpay/verify', token, payload)
  },

  /**
   * Fetches stored merchant order and payment history via GET /api/v2/sandbox/razorpay/orders/{order_id} (Admin only).
   */
  getOrderStatus: async (token: string, orderId: string): Promise<Record<string, unknown>> => {
    return adminRequest<Record<string, unknown>>(
      `/api/v2/sandbox/razorpay/orders/${encodeURIComponent(orderId)}`,
      token,
    )
  },
}
