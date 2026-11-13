// Admin Payment Testing Dashboard — type definitions
// These types are admin-UI-only and do not affect canonical V2 payment-domain contracts.
import type { PayerPayment, Status } from './payment.ts'

/** The two selectable testing modes in the Admin dashboard. */
export type AdminTestMode = 'mock-upi' | 'razorpay'

/** Configuration for a single Mock UPI test run. */
export interface MockUpiTestConfig {
  beneficiary_id: string
  amount_paise: number
  purpose: string
}

/** Single hash-chained mock audit event for admin test payments. */
export interface AdminAuditEntry {
  seq: number
  paymentId: string
  actorRole: string
  event: string
  fromStatus: Status | null
  toStatus: Status
  version: number
  timestamp: string
  prevHash: string
  hash: string
}

/** Response from GET /__pauseguard/demo/admin/audit (isolated to admin synthetic payer). */
export interface AdminAuditResponse {
  payments: PayerPayment[]
  events: AdminAuditEntry[]
}

/** Response from GET /api/v2/audit/verify (Admin-only). */
export interface AuditVerifyResult {
  valid: boolean
  total_events: number
  head_hash: string
  checked_at: string
}

/**
 * Razorpay test order & reconciliation status summary.
 */
export interface RazorpayOrderPreview {
  orderId: string | null
  paymentId: string | null
  amountPaise: number | null
  currency: 'INR' | null
  keyId: string | null
  verificationStatus: 'not_connected' | 'pending' | 'verified' | 'failed'
  reconciliationStatus: 'unavailable' | 'created' | 'paid' | 'captured' | 'refunded' | 'failed'
}

/** Response from GET /api/v2/sandbox/razorpay/config (Admin-only, public Test key only). */
export interface RazorpayConfigResult {
  enabled: boolean
  mode: 'test'
  key_id: string
}

/** Stored payment entry returned inside GET /api/v2/sandbox/razorpay/orders/{order_id}. */
export interface RazorpayOrderHistoryPayment {
  id: string
  status: string
  amount_paise: number
  method?: string | null
  verified_at?: string | null
  created_at?: string | null
}

/** Response from GET /api/v2/sandbox/razorpay/orders/{order_id}. */
export interface RazorpayOrderStatusResult {
  id: string
  razorpay_order_id: string
  admin_id?: string
  amount_paise: number
  currency: string
  status: string
  receipt?: string | null
  key_id?: string | null
  created_at?: string
  payments: RazorpayOrderHistoryPayment[]
}

/** Razorpay integration status as known by the frontend. */
export type RazorpayBackendStatus = 'unavailable' | 'pending' | 'available'

/**
 * Canonical FastAPI endpoints for Razorpay Test Mode merchant sandbox.
 */
export const razorpayRequiredEndpoints = [
  { method: 'GET',  path: '/api/v2/sandbox/razorpay/config',            note: 'Return validated Test Mode key_id (rzp_test_* only)' },
  { method: 'POST', path: '/api/v2/sandbox/razorpay/orders',            note: 'Create an isolated Razorpay Test Mode order (idempotent)' },
  { method: 'POST', path: '/api/v2/sandbox/razorpay/verify',            note: 'Verify HMAC payment signature & reconcile with provider' },
  { method: 'GET',  path: '/api/v2/sandbox/razorpay/orders/{order_id}', note: 'Inspect stored merchant order and payment history' },
] as const
