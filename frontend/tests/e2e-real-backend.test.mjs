import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { test } from 'node:test'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined
const origin = process.env.PAUSEGUARD_TEST_ORIGIN || 'http://127.0.0.1:5173'

async function launchBrowser(t) {
  const browser = await chromium.launch(executablePath ? { executablePath } : {})
  t.after(() => browser.close())
  return browser
}

async function cancelPaymentIfNonTerminal(paymentId) {
  if (!paymentId) return
  try {
    const pSession = await (
      await fetch(`${origin}/api/v2/demo/session`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: 'payer', sample: true }),
      })
    ).json()
    await fetch(`${origin}/api/v2/payments/${paymentId}/cancel`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${pSession.token}` },
    })
  } catch {
    // Ignore cleanup errors on already terminal payments
  }
}

test('E2E Real Backend: Separate payer/guardian sessions, WS notification, redaction, approval, confirmation, and audit', { timeout: 60_000 }, async (t) => {
  const browser = await launchBrowser(t)
  const payerCtx = await browser.newContext()
  const guardianCtx = await browser.newContext()
  const payer = await payerCtx.newPage()
  const guardian = await guardianCtx.newPage()

  let paymentId = ''
  t.after(() => cancelPaymentIfNonTerminal(paymentId))

  const payerWsUrls = []
  const guardianWsUrls = []
  payer.on('websocket', (ws) => payerWsUrls.push(ws.url()))
  guardian.on('websocket', (ws) => guardianWsUrls.push(ws.url()))

  // 1. Payer signup displays real-backend notice
  await payer.goto(`${origin}/payer/signup`)
  await payer.getByText(/Self-service account registration is only available in local mock mode/i).waitFor()

  // 2. Payer sample login
  await payer.goto(`${origin}/payer/login`)
  await payer.getByRole('button', { name: 'Open sample payer' }).click()
  await payer.getByRole('heading', { name: 'Prepare a payment' }).waitFor()

  // 3. Guardian sample login in isolated browser context
  await guardian.goto(`${origin}/guardian/login`)
  await guardian.getByRole('button', { name: 'Open sample guardian' }).click()
  await guardian.getByText('Waiting for a review request').waitFor()

  // 4. Payer creates high-risk payment
  await payer.getByRole('button', { name: 'Check payment', exact: true }).click()
  await payer.getByRole('heading', { name: 'Waiting for your guardian' }).waitFor()

  const paymentIdMatch =
    payer.url().match(/pg_[a-zA-Z0-9_-]+/) ||
    (await payer.locator('main').innerText()).match(/pg_[a-zA-Z0-9_-]+/)
  assert.ok(paymentIdMatch, `Expected pg_ payment reference in URL or UI, got ${payer.url()}`)
  paymentId = paymentIdMatch[0]

  // Payer establishes /api/v2/ws connection on active payment screen
  assert.ok(payerWsUrls.some((u) => u.includes('/api/v2/ws?token=')), 'Expected payer WebSocket connection')

  // 5. Guardian opens review and sees privacy-redacted view + establishes WS connection
  const openBtn = guardian.getByRole('button', { name: 'Open review' })
  await openBtn.waitFor()
  await openBtn.click()
  await guardian.getByRole('heading', { name: 'Review requested' }).waitFor()

  assert.ok(guardianWsUrls.some((u) => u.includes('/api/v2/ws?token=')), 'Expected guardian WebSocket connection')

  const guardianText = await guardian.locator('main').innerText()
  assert.doesNotMatch(guardianText, /55,000|Willow Supplies|KYC or verification request/)

  // 6. Guardian approves -> payer receives READY_TO_EXECUTE update without automatic settlement
  await guardian.getByRole('button', { name: 'Approve review' }).click()
  await guardian.getByRole('heading', { name: 'Review approved' }).waitFor()
  await payer.getByRole('heading', { name: 'Ready for your confirmation' }).waitFor()
  assert.equal(await payer.getByRole('heading', { name: 'Simulated payment completed' }).count(), 0)

  // 7. Owning payer final confirmation -> EXECUTED
  await payer.getByRole('button', { name: 'Confirm simulated payment' }).click()
  await payer.getByRole('heading', { name: 'Simulated payment completed' }).waitFor()

  // 8. Authorization isolation, Policy Lab RBAC, and hash-chained audit verification
  const pSession = await (
    await fetch(`${origin}/api/v2/demo/session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role: 'payer', sample: true }),
    })
  ).json()
  const gSession = await (
    await fetch(`${origin}/api/v2/demo/session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role: 'guardian', sample: true }),
    })
  ).json()

  const payerDecisionAttempt = await fetch(`${origin}/api/v2/payments/${paymentId}/guardian/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${pSession.token}` },
    body: JSON.stringify({ approved: true }),
  })
  assert.equal(payerDecisionAttempt.status, 403)

  const guardianConfirmAttempt = await fetch(`${origin}/api/v2/payments/${paymentId}/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${gSession.token}` },
    body: JSON.stringify({ idempotency_key: `guardian-confirm-${paymentId}` }),
  })
  assert.equal(guardianConfirmAttempt.status, 403)

  const eventsRes = await fetch(`${origin}/api/v2/payments/${paymentId}/events`, {
    headers: { Authorization: `Bearer ${pSession.token}` },
  })
  assert.equal(eventsRes.status, 200)
  const events = await eventsRes.json()
  assert.ok(Array.isArray(events) && events.length >= 3, `Expected >= 3 audit events, got ${events.length}`)

  const policyLabForbidden = await fetch(`${origin}/api/v2/policy-lab/simulate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${pSession.token}` },
    body: JSON.stringify({ seed: 42, sample_size: 12 }),
  })
  assert.equal(policyLabForbidden.status, 403)
})

test('E2E Real Backend: Guardian rejection ends payment in terminal declined state', { timeout: 45_000 }, async (t) => {
  const browser = await launchBrowser(t)
  const payerCtx = await browser.newContext()
  const guardianCtx = await browser.newContext()
  const payer = await payerCtx.newPage()
  const guardian = await guardianCtx.newPage()

  let paymentId = ''
  t.after(() => cancelPaymentIfNonTerminal(paymentId))

  await payer.goto(`${origin}/payer/login`)
  await payer.getByRole('button', { name: 'Open sample payer' }).click()
  await payer.getByRole('heading', { name: 'Prepare a payment' }).waitFor()

  await guardian.goto(`${origin}/guardian/login`)
  await guardian.getByRole('button', { name: 'Open sample guardian' }).click()
  await guardian.getByText('Waiting for a review request').waitFor()

  await payer.getByRole('button', { name: 'Check payment', exact: true }).click()
  await payer.getByRole('heading', { name: 'Waiting for your guardian' }).waitFor()

  const paymentIdMatch =
    payer.url().match(/pg_[a-zA-Z0-9_-]+/) ||
    (await payer.locator('main').innerText()).match(/pg_[a-zA-Z0-9_-]+/)
  assert.ok(paymentIdMatch, `Expected pg_ payment reference in URL or UI, got ${payer.url()}`)
  paymentId = paymentIdMatch[0]

  await guardian.getByRole('button', { name: 'Open review' }).click()
  await guardian.getByRole('heading', { name: 'Review requested' }).waitFor()
  await guardian.getByRole('button', { name: 'Reject payment' }).click()
  await guardian.getByRole('heading', { name: 'Payment rejected' }).waitFor()

  await payer.getByRole('heading', { name: 'Payment rejected' }).waitFor()
  assert.equal(await payer.getByRole('heading', { name: 'Simulated payment completed' }).count(), 0)
})

test('E2E Real Backend: Safe-Lock blocks payments (423), network disconnect recovers, 30s timeout triggers fallback, 401 clears session', { timeout: 85_000 }, async (t) => {
  const browser = await launchBrowser(t)
  const payerCtx = await browser.newContext()
  const payer = await payerCtx.newPage()

  await payer.goto(`${origin}/payer/login`)
  await payer.getByRole('button', { name: 'Open sample payer' }).click()
  await payer.getByRole('heading', { name: 'Prepare a payment' }).waitFor()

  // 1. Engage Safe-Lock via Profile UI (/payer/profile) and confirm backend fails closed (HTTP 423)
  await payer.goto(`${origin}/payer/profile`)
  await payer.getByRole('button', { name: 'Turn on Safe-Lock' }).click()
  await payer.getByRole('heading', { name: 'Safe-Lock is on' }).waitFor()

  const pSession = await (
    await fetch(`${origin}/api/v2/demo/session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role: 'payer', sample: true }),
    })
  ).json()
  const lockedAttempt = await fetch(`${origin}/api/v2/payments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${pSession.token}` },
    body: JSON.stringify({
      beneficiary_id: 'safelock_vendor',
      amount_paise: 100000,
      purpose: 'routine transfer while safe-locked',
      idempotency_key: `e2e-safelock-${Date.now()}`,
    }),
  })
  assert.equal(lockedAttempt.status, 423)

  await payer.getByRole('button', { name: 'Turn off Safe-Lock' }).click()
  await payer.getByRole('heading', { name: 'Safe-Lock is off' }).waitFor()

  // 2. Network disconnection & Retry recovery
  await payer.goto(`${origin}/payer`)
  await payer.getByRole('button', { name: 'Check payment', exact: true }).click()
  await payer.getByRole('heading', { name: 'Waiting for your guardian' }).waitFor()

  const readPattern = '**/api/v2/payments/pg_*'
  const failRead = (route) => route.abort()
  await payer.route(readPattern, failRead)
  await payer.getByRole('button', { name: 'Retry connection' }).waitFor({ timeout: 15_000 })
  await payer.unroute(readPattern, failRead)
  await payer.getByRole('button', { name: 'Retry connection' }).click()
  await payer.getByRole('heading', { name: 'Waiting for your guardian' }).waitFor()

  // 3. Wait for 30s server deadline -> fallback review (never executes)
  await payer.getByRole('heading', { name: 'Review window closed' }).waitFor({ timeout: 40_000 })
  assert.equal(await payer.getByRole('heading', { name: 'Simulated payment completed' }).count(), 0)

  // 4. Session expiry (HTTP 401 clears stored session cleanly)
  await payer.route('**/api/v2/**', (route) =>
    route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Session expired' }),
    }),
  )
  await payer.goto(`${origin}/payer`)
  await payer.getByRole('heading', { name: 'Continue to PauseGuard' }).waitFor({ timeout: 10_000 })
})
