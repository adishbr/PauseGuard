import type { IncomingMessage, ServerResponse } from 'node:http'
import { randomUUID } from 'node:crypto'
import { demoTokens, beneficiaries, purposes } from './scenarios.ts'
import { defaultReviewDuration, demoReviewDurationHeader, parseReviewDuration } from './reviewPreference.ts'
import type { ReviewDuration } from './reviewPreference.ts'
import { terminalStatuses } from '../src/types/payment.ts'
import type { CreatePayment, GuardianPayment, PayerPayment, Status } from '../src/types/payment.ts'

const API = '/api/v2'
const PAYER = 'demo-payer'
const ASSIGNED_GUARDIAN = 'demo-guardian'
const actors = new Map([
  [`Bearer ${demoTokens.payer}`, { id: PAYER, role: 'payer' }],
  [`Bearer ${demoTokens.guardian}`, { id: ASSIGNED_GUARDIAN, role: 'guardian' }],
  ['Bearer pauseguard-demo-unassigned-guardian', { id: 'demo-other', role: 'guardian' }],
])

interface PaymentRecord {
  payment: PayerPayment
  input: CreatePayment
  payer: string
  guardian: string | null
  reviewDuration?: ReviewDuration
  confirmationKey?: string
}

class MockError extends Error {
  constructor(readonlyStatus: number, message: string) {
    super(message)
    this.status = readonlyStatus
  }

  readonly status: number
}

async function readBody(request: IncomingMessage): Promise<Record<string, unknown>> {
  let text = ''
  for await (const chunk of request) {
    text += chunk
    if (text.length > 4096) throw new MockError(413, 'The demo request is too large.')
  }
  try {
    const body = JSON.parse(text)
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw new Error()
    return body
  } catch {
    throw new MockError(400, 'The demo request needs a JSON object.')
  }
}

function respond(response: ServerResponse, now: number, status: number, body: unknown) {
  response.writeHead(status, {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-store',
    Date: new Date(now).toUTCString(),
  })
  response.end(JSON.stringify(body))
}

function transition(record: PaymentRecord, status: Status) {
  record.payment.status = status
  record.payment.version += 1
}

function guardianView(payment: PayerPayment): GuardianPayment {
  return {
    id: payment.id,
    status: payment.status,
    tier: payment.tier,
    guardian_deadline: payment.guardian_deadline,
    message: 'PauseGuard requested an independent safety review.',
  }
}

function classify(input: CreatePayment): Pick<PayerPayment, 'status' | 'tier' | 'risk_score' | 'reason_codes'> {
  if (input.beneficiary_id === 'recipient_flagged') {
    return { status: 'REJECTED', tier: 3, risk_score: 100, reason_codes: [] }
  }
  if (input.purpose === 'kyc_verification') {
    const reasons = ['RC_COERCION_PURPOSE']
    if (input.beneficiary_id === 'supplier_new') reasons.unshift('RC_NEW_BENEFICIARY')
    if (input.amount_paise >= 5_500_000) reasons.push('RC_LARGE_DEVIATION', 'RC_CUSTOMER_ALERT_PREFERENCE')
    return { status: 'AWAITING_GUARDIAN', tier: 3, risk_score: 100, reason_codes: reasons }
  }
  if (input.beneficiary_id === 'supplier_new') {
    return { status: 'AWAITING_WARNING', tier: 1, risk_score: 30, reason_codes: ['RC_NEW_BENEFICIARY'] }
  }
  return { status: 'READY_TO_EXECUTE', tier: 0, risk_score: 5, reason_codes: [] }
}

function validKey(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= 128
}

export function createMockApi(clock: () => number = Date.now) {
  const payments = new Map<string, PaymentRecord>()
  const creations = new Map<string, PaymentRecord>()

  function expire(record: PaymentRecord) {
    const { status, guardian_deadline } = record.payment
    if (status === 'AWAITING_GUARDIAN' && guardian_deadline && clock() >= Date.parse(guardian_deadline)) {
      transition(record, 'AWAITING_FALLBACK_REVIEW')
    }
  }

  return (request: IncomingMessage, response: ServerResponse, next: () => void) => {
    const path = new URL(request.url ?? '/', 'http://localhost').pathname
    if (!path.startsWith(`${API}/`)) return next()

    function snapshot(record: PaymentRecord, role: string) {
      if (record.payment.status === 'AWAITING_GUARDIAN' && record.reviewDuration) {
        response.setHeader(demoReviewDurationHeader, record.reviewDuration)
      }
      return role === 'guardian' ? guardianView(record.payment) : record.payment
    }

    async function handle() {
      const route = path.slice(API.length)
      const method = request.method
      if (method === 'GET' && route === '/health') return { status: 'ok', mode: 'mock' }
      const actor = actors.get(request.headers.authorization ?? '')
      if (!actor) throw new MockError(401, 'This demo session is unauthorized.')

      if (method === 'POST' && route === '/payments') {
        if (actor.role !== 'payer') throw new MockError(403, 'This demo role cannot start payments.')
        const body = await readBody(request)
        const { beneficiary_id, purpose, amount_paise, idempotency_key } = body
        if (typeof beneficiary_id !== 'string' || !Object.hasOwn(beneficiaries, beneficiary_id) ||
            typeof purpose !== 'string' || !Object.hasOwn(purposes, purpose) ||
            typeof amount_paise !== 'number' || !Number.isSafeInteger(amount_paise) || amount_paise <= 0 ||
            !validKey(idempotency_key)) {
          throw new MockError(422, 'Enter a positive amount and choose a demo recipient and purpose.')
        }
        const input = { beneficiary_id, purpose, amount_paise, idempotency_key }
        const key = `${actor.id}:${idempotency_key}`
        const existing = creations.get(key)
        if (existing) {
          if (JSON.stringify(existing.input) !== JSON.stringify(input)) {
            throw new MockError(409, 'This payment reference already belongs to another request.')
          }
          expire(existing)
          return snapshot(existing, actor.role)
        }
        // The demo adapter supplies a preference; the fixture owns deadline creation.
        const durationHint = request.headers[demoReviewDurationHeader]
        const requestedDuration = durationHint === undefined ? defaultReviewDuration : parseReviewDuration(durationHint)
        if (!requestedDuration) throw new MockError(422, 'Choose 30, 45, or 60 seconds for guardian review.')
        const outcome = classify(input)
        const reviewDuration = outcome.status === 'AWAITING_GUARDIAN' ? requestedDuration : undefined
        const payment: PayerPayment = {
          id: `pg_${randomUUID()}`, ...outcome, beneficiary_id, amount_paise, purpose, version: 1,
          guardian_deadline: reviewDuration ? new Date(clock() + reviewDuration * 1_000).toISOString() : null,
        }
        // The two synthetic accounts are pre-enrolled for this fixture only.
        const record = {
          payment, input, payer: actor.id, guardian: reviewDuration ? ASSIGNED_GUARDIAN : null, reviewDuration,
        }
        payments.set(payment.id, record)
        creations.set(key, record)
        return snapshot(record, actor.role)
      }

      const [, resource, id, ...segments] = route.split('/')
      const action = segments.join('/')
      if (resource !== 'payments' || !id) throw new MockError(404, 'This route is unavailable in the demo.')
      const record = payments.get(id)
      if (!record || (actor.id !== record.payer && actor.id !== record.guardian)) {
        throw new MockError(404, 'This payment is unavailable for this demo account.')
      }
      const { payment } = record
      if (method === 'GET' && !action) {
        expire(record)
        return snapshot(record, actor.role)
      }
      if (method !== 'POST') throw new MockError(405, 'This method is unavailable for the payment.')
      if (action === 'guardian/decision') {
        if (actor.id !== record.guardian) throw new MockError(403, 'Only the assigned guardian can review.')
        const { decision } = await readBody(request)
        expire(record)
        if (payment.status !== 'AWAITING_GUARDIAN') {
          throw new MockError(409, 'This guardian review has closed. Refresh its status.')
        }
        if (decision !== 'approve' && decision !== 'reject') throw new MockError(422, 'Choose a review decision.')
        transition(record, decision === 'approve' ? 'READY_TO_EXECUTE' : 'REJECTED')
        return guardianView(payment)
      }
      if (actor.id !== record.payer) throw new MockError(403, 'Only the payer can take this action.')
      if (action === 'confirm') {
        const { idempotency_key } = await readBody(request)
        if (!validKey(idempotency_key)) throw new MockError(422, 'A confirmation key is required.')
        if (payment.status === 'EXECUTED' && idempotency_key === record.confirmationKey) return payment
        if (payment.status !== 'READY_TO_EXECUTE') throw new MockError(409, 'This payment is unavailable for confirmation.')
        record.confirmationKey = idempotency_key
        transition(record, 'EXECUTED')
        return payment
      }
      expire(record)
      if (action === 'warning/acknowledge' && payment.status === 'AWAITING_WARNING') {
        transition(record, 'READY_TO_EXECUTE')
        return payment
      }
      if (action === 'fallback/activate' && payment.status === 'AWAITING_FALLBACK_REVIEW') return payment
      if (action === 'cancel' && payment.status !== 'CREATED' && !terminalStatuses.has(payment.status)) {
        transition(record, 'CANCELLED')
        return payment
      }
      throw new MockError(409, 'This action is unavailable for the current payment status.')
    }

    void handle().then(
      (body) => respond(response, clock(), 200, body),
      (error: unknown) => {
        const known = error instanceof MockError
        respond(response, clock(), known ? error.status : 500, {
          detail: known ? error.message : 'The local demo API encountered an error.',
        })
      },
    )
  }
}
