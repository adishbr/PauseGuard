import assert from 'node:assert/strict'
import { once } from 'node:events'
import { createServer } from 'node:http'
import { test } from 'node:test'
import { createMockApi } from '../mocks/payment-api.ts'
import { demoTokens } from '../mocks/scenarios.ts'
import { formatRupees, toPaise } from '../src/services/demoSession.ts'
import { isLocale, translator } from '../src/locales/messages.ts'
import { parsePayment } from '../src/services/paymentResponse.ts'

const coerced = { beneficiary_id: 'supplier_new', amount_paise: 5_500_000, purpose: 'kyc_verification', idempotency_key: 'attempt-1' }
const routine = { beneficiary_id: 'merchant_familiar', amount_paise: 10_000, purpose: 'purchase', idempotency_key: 'attempt-2' }

async function fixture(t) {
  let now = Date.parse('2026-11-09T10:00:00Z')
  const handler = createMockApi(() => now)
  const server = createServer((request, response) => handler(request, response, () => response.writeHead(404).end()))
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  t.after(() => new Promise((resolve) => server.close(resolve)))

  async function call(path, token, body) {
    const response = await fetch(`http://127.0.0.1:${server.address().port}/api/v2${path}`, {
      method: body ? 'POST' : 'GET',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    })
    return { code: response.status, body: await response.json() }
  }

  return {
    call,
    create: async (input) => (await call('/payments', demoTokens.payer, input)).body,
    advance: (ms) => { now += ms },
  }
}

test('amounts convert to integer paise without accepting invalid or unsafe inputs', () => {
  assert.equal(toPaise('100.01'), 10_001)
  assert.equal(toPaise(' 1.2 '), 120)
  assert.equal(toPaise('90071992547409.91'), Number.MAX_SAFE_INTEGER)
  assert.equal(formatRupees(5_500_005), '₹55,000.05')
  assert.equal(formatRupees(Number.MAX_SAFE_INTEGER), '₹9,00,71,99,25,47,409.91')
  for (const value of ['', '0', '-1', '1e3', '1.005', '1,000', '90071992547409.92']) {
    assert.equal(toPaise(value), null)
  }
})

test('guardian reads and decisions expose only the V2 redacted fields', async (t) => {
  const { call, create } = await fixture(t)
  const payment = await create({ ...coerced, role: 'guardian', guardian_id: 'demo-other' })
  assert.equal(payment.status, 'AWAITING_GUARDIAN')
  assert.equal(payment.amount_paise, 5_500_000)
  assert.equal(payment.guardian_deadline, '2026-11-09T10:00:30.000Z')
  const route = `/payments/${payment.id}`
  const fields = ['guardian_deadline', 'id', 'message', 'status', 'tier']
  const view = await call(route, demoTokens.guardian)
  assert.equal(view.code, 200)
  assert.deepEqual(Object.keys(view.body).sort(), fields)
  const unassigned = await call(route, 'pauseguard-demo-unassigned-guardian')
  assert.equal(unassigned.code, 404)
  assert.deepEqual(Object.keys(unassigned.body), ['detail'])
  assert.equal((await call(route, 'invalid')).code, 401)
  assert.equal((await call('/payments', demoTokens.guardian, coerced)).code, 403)
  assert.equal((await call(`${route}/guardian/decision`, demoTokens.payer, { decision: 'approve' })).code, 403)
  assert.equal((await call(`${route}/confirm`, demoTokens.guardian, { idempotency_key: 'fake' })).code, 403)
  const rejection = await call(`${route}/guardian/decision`, demoTokens.guardian, { decision: 'reject' })
  assert.equal(rejection.code, 200)
  assert.deepEqual(Object.keys(rejection.body).sort(), fields)
  assert.equal(rejection.body.status, 'REJECTED')
  assert.equal((await call(`${route}/guardian/decision`, demoTokens.guardian, { decision: 'approve' })).code, 409)
  assert.equal((await call(`${route}/confirm`, demoTokens.payer, { idempotency_key: 'fake' })).code, 409)
})

test('guardian approval requires separate payer confirmation and duplicate retries execute once', async (t) => {
  const { call, create } = await fixture(t)
  const [payment, duplicate] = await Promise.all([create(coerced), create(coerced)])
  assert.equal(duplicate.id, payment.id)
  assert.equal((await call('/payments', demoTokens.payer, { ...coerced, amount_paise: 123 })).code, 409)
  const route = `/payments/${payment.id}`
  const approval = await call(`${route}/guardian/decision`, demoTokens.guardian, { decision: 'approve' })
  assert.equal(approval.body.status, 'READY_TO_EXECUTE')
  const key = { idempotency_key: 'same-confirmation' }
  const results = await Promise.all([
    call(`${route}/confirm`, demoTokens.payer, key),
    call(`${route}/confirm`, demoTokens.payer, key),
  ])
  assert.equal(results[0].code, 200)
  assert.equal(results[0].body.status, 'EXECUTED')
  assert.equal(results[0].body.version, 3)
  assert.deepEqual(results[0], results[1])
  assert.equal((await call(`${route}/confirm`, demoTokens.payer, { idempotency_key: 'different' })).code, 409)
  assert.equal((await call(`${route}/cancel`, demoTokens.payer, {})).code, 409)
})

test('server time closes guardian review at the deadline and fallback cannot execute', async (t) => {
  const { call, create, advance } = await fixture(t)
  const payment = await create(coerced)
  const route = `/payments/${payment.id}`
  advance(29_999)
  assert.equal((await call(`${route}/fallback/activate`, demoTokens.payer, {})).code, 409)
  advance(1)
  assert.equal((await call(`${route}/guardian/decision`, demoTokens.guardian, { decision: 'approve' })).code, 409)
  assert.equal((await call(route, demoTokens.payer)).body.status, 'AWAITING_FALLBACK_REVIEW')
  assert.equal((await call(`${route}/confirm`, demoTokens.payer, { idempotency_key: 'late' })).code, 409)
  assert.equal((await call(`${route}/cancel`, demoTokens.payer, {})).body.status, 'CANCELLED')
})

test('routine and warning flows do not alert a guardian, and a flagged fixture is rejected', async (t) => {
  const { call, create } = await fixture(t)
  const normal = await create(routine)
  assert.equal(normal.status, 'READY_TO_EXECUTE')
  assert.equal((await call(`/payments/${normal.id}`, demoTokens.guardian)).code, 404)

  const warning = await create({ ...coerced, purpose: 'supplier_payment' })
  const warningPath = `/payments/${warning.id}`
  assert.equal(warning.status, 'AWAITING_WARNING')
  assert.equal((await call(warningPath, demoTokens.guardian)).code, 404)
  assert.equal((await call(`${warningPath}/confirm`, demoTokens.payer, { idempotency_key: 'early' })).code, 409)
  assert.equal((await call(`${warningPath}/warning/acknowledge`, demoTokens.payer, {})).body.status, 'READY_TO_EXECUTE')
  assert.equal((await call(`${warningPath}/cancel`, demoTokens.payer, {})).body.status, 'CANCELLED')

  const blocked = await create({ ...routine, idempotency_key: 'flagged', beneficiary_id: 'recipient_flagged' })
  assert.equal(blocked.status, 'REJECTED')
  assert.equal((await call(`/payments/${blocked.id}/confirm`, demoTokens.payer, { idempotency_key: 'blocked' })).code, 409)
})

test('payer cancellation racing a guardian rejection keeps the terminal decision', async (t) => {
  const { call, create } = await fixture(t)
  const { id } = await create(coerced)
  const route = `/payments/${id}`
  const results = await Promise.all([
    call(`${route}/cancel`, demoTokens.payer, {}),
    call(`${route}/guardian/decision`, demoTokens.guardian, { decision: 'reject' }),
  ])
  assert.deepEqual(results.map(({ code }) => code).sort(), [200, 409])
  const winner = results.find(({ code }) => code === 200).body.status
  assert.ok(['CANCELLED', 'REJECTED'].includes(winner))
  assert.equal((await call(route, demoTokens.payer)).body.status, winner)
})

test('payment response validation fails closed for wrong references, malformed data and leaked guardian fields', () => {
  const id = 'pg_test'
  const guardian = { id, status: 'AWAITING_GUARDIAN', tier: 3, guardian_deadline: '2026-11-09T10:00:30Z', message: 'Review.' }
  const payer = { ...guardian, amount_paise: 10_005, beneficiary_id: 'merchant_familiar', purpose: 'purchase',
    version: 1, reason_codes: [], risk_score: 5 }

  assert.deepEqual(parsePayment(guardian, 'guardian', id), guardian)
  assert.equal(parsePayment(payer, 'payer', id).amount_paise, 10_005)
  assert.equal(parsePayment({ ...guardian, amount_paise: 10_005 }, 'guardian', id), undefined)
  assert.equal(parsePayment({ ...guardian, guardian_deadline: null }, 'guardian', id), undefined)
  assert.equal(parsePayment({ ...guardian, guardian_deadline: 'invalid' }, 'guardian', id), undefined)
  assert.equal(parsePayment({ ...guardian, status: 'PENDING_REVIEW' }, 'guardian', id), undefined)
  assert.equal(parsePayment({ ...guardian, tier: 4 }, 'guardian', id), undefined)
  assert.equal(parsePayment({ ...payer, amount_paise: '10005' }, 'payer', id), undefined)
  assert.equal(parsePayment({ ...payer, status: 'EXECUTED', version: '1' }, 'payer', id), undefined)
  assert.equal(parsePayment(guardian, 'guardian', 'pg_other'), undefined)
})

test('local-language input keeps exact paise and locale switches keep canonical payment keys', () => {
  for (const input of ['१००.०५', '౧౦౦.౦౫', '೧೦೦.೦೫']) assert.equal(toPaise(input), 10_005)
  assert.equal(toPaise('೧೦೦.೦೫೫'), null)
  for (const locale of ['kn', 'hi', 'te']) {
    assert.equal(isLocale(locale), true)
    assert.notEqual(translator(locale)('confirm'), translator('en')('confirm'))
    assert.notEqual(translator(locale)('fallbackDetail'), translator('en')('fallbackDetail'))
  }
  assert.equal(isLocale('unknown'), false)
})

test('the fixture rejects whitespace idempotency keys and leaves timeout decisions closed', async (t) => {
  const { call, create, advance } = await fixture(t)
  assert.equal((await call('/payments', demoTokens.payer, { ...coerced, idempotency_key: ' ' })).code, 422)
  const payment = await create(coerced)
  const route = `/payments/${payment.id}`
  advance(30_000)
  const [lateApproval, lateRejection, fallback] = await Promise.all([
    call(`${route}/guardian/decision`, demoTokens.guardian, { decision: 'approve' }),
    call(`${route}/guardian/decision`, demoTokens.guardian, { decision: 'reject' }),
    call(`${route}/fallback/activate`, demoTokens.payer, {}),
  ])
  assert.equal(lateApproval.code, 409)
  assert.equal(lateRejection.code, 409)
  assert.equal(fallback.body.status, 'AWAITING_FALLBACK_REVIEW')
  assert.equal((await call(route, demoTokens.payer)).body.version, payment.version + 1)
})
