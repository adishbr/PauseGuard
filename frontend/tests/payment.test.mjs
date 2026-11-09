import assert from 'node:assert/strict'
import { once } from 'node:events'
import { createServer, request } from 'node:http'
import { test } from 'node:test'
import { createMockApi } from '../mocks/payment-api.ts'
import { demoReviewDurationHeader, reviewDurations } from '../mocks/reviewPreference.ts'
import { demoAccountPath } from '../src/types/account.ts'
import { formatRupees, toPaise } from '../src/services/demoSession.ts'
import { isLocale, translator } from '../src/locales/messages.ts'
import { parsePayment } from '../src/services/paymentResponse.ts'

const demoTokens = { payer: 'payer', guardian: 'guardian' }
const coerced = { beneficiary_id: 'supplier_new', amount_paise: 5_500_000, purpose: 'kyc_verification', idempotency_key: 'attempt-1' }
const routine = { beneficiary_id: 'merchant_familiar', amount_paise: 10_000, purpose: 'purchase', idempotency_key: 'attempt-2' }

async function fixture(t) {
  let now = Date.parse('2026-11-09T10:00:00Z')
  const handler = createMockApi(() => now)
  const server = createServer((request, response) => handler(request, response, () => response.writeHead(404).end()))
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  t.after(() => new Promise((resolve) => server.close(resolve)))

  const origin = `http://127.0.0.1:${server.address().port}`
  async function account(path, body, token, method) {
    const response = await fetch(origin + demoAccountPath + path, {
      method: method ?? (body ? 'POST' : 'GET'),
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    })
    return { code: response.status, body: await response.json() }
  }
  const tokens = new Map()
  for (const role of ['payer', 'guardian']) {
    tokens.set(role, (await account('/session', { role, sample: true })).body.token)
  }
  tokens.set('pauseguard-demo-unassigned-guardian', (await account('/register', {
    role: 'guardian', name: 'Other Demo', contact: 'other@fixture.test',
  })).body.token)
  async function call(path, token, body, headers = {}) {
    const response = await fetch(`http://127.0.0.1:${server.address().port}/api/v2${path}`, {
      method: body ? 'POST' : 'GET',
      headers: { Authorization: `Bearer ${tokens.get(token) ?? token}`, 'Content-Type': 'application/json', ...headers },
      body: body ? JSON.stringify(body) : undefined,
    })
    return { code: response.status, body: await response.json(), duration: response.headers.get(demoReviewDurationHeader) }
  }

  return {
    call, account,
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

for (const seconds of reviewDurations) {
  test(`the ${seconds}-second fixture deadline survives retries and expires without executing`, async (t) => {
    const { call, advance } = await fixture(t)
    const headers = { [demoReviewDurationHeader]: String(seconds) }
    const created = await call('/payments', demoTokens.payer, coerced, headers)
    assert.equal(created.code, 200)
    assert.equal(created.duration, String(seconds))
    const payment = created.body
    const deadline = new Date(Date.parse('2026-11-09T10:00:00Z') + seconds * 1_000).toISOString()
    assert.equal(payment.guardian_deadline, deadline)
    const route = `/payments/${payment.id}`
    const guardian = await call(route, demoTokens.guardian)
    assert.equal(guardian.body.guardian_deadline, deadline)
    assert.equal(guardian.duration, String(seconds))
    assert.equal((await call(route, 'pauseguard-demo-unassigned-guardian')).duration, null)

    advance(seconds * 1_000 - 1)
    const duplicate = await call('/payments', demoTokens.payer, coerced, {
      [demoReviewDurationHeader]: String(seconds === 30 ? 60 : 30),
    })
    assert.deepEqual(duplicate, created)
    assert.equal((await call(`${route}/fallback/activate`, demoTokens.payer, {})).code, 409)
    advance(1)
    assert.equal((await call(`${route}/guardian/decision`, demoTokens.guardian, { decision: 'approve' })).code, 409)
    const fallback = await call(route, demoTokens.payer)
    assert.equal(fallback.body.status, 'AWAITING_FALLBACK_REVIEW')
    assert.equal(fallback.body.version, payment.version + 1)
    assert.equal(fallback.duration, null)
    assert.equal((await call(`${route}/confirm`, demoTokens.payer, { idempotency_key: 'late' })).code, 409)
    assert.equal((await call(`${route}/cancel`, demoTokens.payer, {})).body.status, 'CANCELLED')
  })
}

test('the fixture validates duration hints and skips review for routine payments', async (t) => {
  const { call } = await fixture(t)
  const headers = (value) => ({ [demoReviewDurationHeader]: value })
  assert.equal((await call('/payments', demoTokens.payer, coerced, headers('90'))).code, 422)
  assert.equal((await call('/payments', demoTokens.payer, coerced, headers('30, 60'))).code, 422)
  const result = await call('/payments', demoTokens.payer, routine, headers('60'))
  assert.equal(result.body.status, 'READY_TO_EXECUTE')
  assert.equal(result.body.guardian_deadline, null)
  assert.equal(result.duration, null)
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

test('demo onboarding isolates roles, validates fictional details and expires sessions', async (t) => {
  const { account, call, advance } = await fixture(t)
  const payer = { role: 'payer', name: 'New Demo', contact: 'new@fixture.test', category: 'enterprise', language: 'kn' }
  assert.equal((await account('/register', { ...payer, contact: 'new@gmail.com' })).code, 422)
  assert.equal((await account('/register', { ...payer, role: 'admin' })).code, 422)
  const registered = await account('/register', payer)
  assert.equal(registered.code, 200)
  assert.equal(registered.body.profile.category, 'enterprise')
  assert.equal(registered.body.profile.language, 'kn')
  const token = registered.body.token
  assert.equal((await account('/register', payer)).code, 409)
  assert.equal((await account('/session', { contact: payer.contact, role: 'guardian' })).code, 404)
  assert.equal((await account('/profile', { quietStart: '22:00' }, token)).code, 422)
  const updated = await account('/profile', { largeText: true, quietStart: '22:00', quietEnd: '06:00',
    callConsent: true, thresholdPaise: 100, role: 'guardian', sample: true }, token)
  assert.equal(updated.body.role, 'payer')
  assert.equal(updated.body.sample, false)
  assert.equal(updated.body.callConsent, true)
  assert.equal((await account('/session', undefined, token)).body.profile.largeText, true)
  const ready = (await call('/payments', token, routine)).body
  assert.equal(ready.status, 'READY_TO_EXECUTE')
  assert.ok(ready.reason_codes.includes('RC_CUSTOMER_ALERT_PREFERENCE'))
  assert.equal((await call('/payments', token, { ...routine, idempotency_key: 'flagged', beneficiary_id: 'recipient_flagged' })).body.status, 'REJECTED')
  assert.equal((await account('/profile', { safeLock: true }, token)).body.safeLock, true)
  assert.equal((await call(`/payments/${ready.id}/confirm`, token, { idempotency_key: 'lock' })).body.status, 'REJECTED')
  assert.equal((await call('/payments', token, { ...routine, idempotency_key: 'new-locked' })).body.status, 'REJECTED')
  assert.equal((await account('/session', undefined, token, 'DELETE')).code, 200)
  assert.equal((await call('/payments', token, routine)).code, 401)
  const next = await account('/session', { role: 'payer', contact: payer.contact })
  assert.equal(next.code, 200)
  advance(30 * 60_000)
  assert.equal((await account('/session', undefined, next.body.token)).code, 401)
  assert.equal((await call('/payments', 'pauseguard-demo-payer', routine)).code, 401)
})

test('enrollment consent gates reviews and revocation invalidates a previously approved payment', async (t) => {
  const { account, call } = await fixture(t)
  const payer = (await account('/register', { role: 'payer', name: 'Invite Demo', contact: 'payer@enrollment.test' })).body.token
  const guardian = (await account('/register', { role: 'guardian', name: 'Review Demo', contact: '0000012345' })).body.token
  const unrelated = (await account('/register', { role: 'guardian', name: 'Other Guardian', contact: 'other@enrollment.test' })).body.token
  const request = { action: 'invite', name: 'Review Demo', contact: '0000012345', relationship: 'Family' }
  assert.equal((await account('/enrollment', request, payer)).code, 422)
  assert.equal((await account('/enrollment', { ...request, contact: 'ravi@pauseguard.test', consent: true }, payer)).code, 422)
  assert.equal((await account('/enrollment', { ...request, consent: true }, guardian)).code, 403)
  const pending = (await account('/enrollment', { ...request, consent: true }, payer)).body[0]
  assert.equal(pending.status, 'Pending')
  assert.deepEqual((await account('/enrollment', undefined, unrelated)).body, [])
  assert.equal((await account('/enrollment', { action: 'accept', id: pending.id, consent: true }, unrelated)).code, 404)
  assert.equal((await account('/enrollment', { action: 'accept', id: pending.id }, guardian)).code, 422)
  assert.equal((await call('/payments', payer, { ...coerced, idempotency_key: 'pending' })).body.status, 'AWAITING_FALLBACK_REVIEW')
  assert.equal((await account('/enrollment', { action: 'decline', id: pending.id }, guardian)).body[0].status, 'Declined')
  const next = (await account('/enrollment', { ...request, consent: true }, payer)).body[0]
  assert.equal((await account('/enrollment', { action: 'accept', id: next.id, consent: true }, guardian)).body[0].status, 'Accepted')
  const payment = (await call('/payments', payer, coerced, { [demoReviewDurationHeader]: '60' })).body
  assert.equal(payment.status, 'AWAITING_GUARDIAN')
  assert.equal((await account('/reviews', undefined, guardian)).body.id, payment.id)
  const route = `/payments/${payment.id}`
  assert.equal((await call(route, unrelated)).code, 404)
  assert.deepEqual(Object.keys((await call(route, guardian)).body).sort(), ['guardian_deadline', 'id', 'message', 'status', 'tier'])
  assert.equal((await call(route + '/guardian/decision', guardian, { decision: 'approve' })).body.status, 'READY_TO_EXECUTE')
  assert.equal((await account('/enrollment', { action: 'withdraw', id: next.id }, guardian)).body[0].status, 'Revoked')
  assert.equal((await call(route, guardian)).code, 404)
  assert.equal((await call(route + '/confirm', payer, { idempotency_key: 'after-revoke' })).body.status, 'REJECTED')
})


test('demo enrollment and registration decode Unicode names split across chunks', async (t) => {
  const server = createServer(createMockApi())
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  t.after(() => new Promise((resolve) => server.close(resolve)))
  const name = 'ಆಶಾ ಡೆಮೊ'
  const payload = Buffer.from(JSON.stringify({ role: 'payer', name, contact: 'unicode@fixture.test' }))
  const cut = payload.indexOf(Buffer.from(name)) + 1
  const result = await new Promise((resolve, reject) => {
    const connection = request({
      host: '127.0.0.1', port: server.address().port, path: demoAccountPath + '/register',
      method: 'POST', headers: { 'Content-Type': 'application/json' },
    }, (response) => {
      let body = ''
      response.setEncoding('utf8')
      response.on('data', (chunk) => { body += chunk })
      response.on('end', () => resolve({ code: response.statusCode, body: JSON.parse(body) }))
      response.on('error', reject)
    })
    connection.on('error', reject)
    connection.write(payload.subarray(0, cut))
    setTimeout(() => connection.end(payload.subarray(cut)), 20)
  })
  assert.equal(result.code, 200)
  assert.equal(result.body.profile.name, name)
})
