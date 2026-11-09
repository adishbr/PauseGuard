import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { test } from 'node:test'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PAUSEGUARD_TEST_ORIGIN || 'http://localhost:5173'

async function setup(t, options) {
  const browser = await chromium.launch({
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
  })
  t.after(() => browser.close())
  const context = await browser.newContext(options)
  const payer = await context.newPage()
  await payer.goto(origin)
  return { browser, payer }
}

async function openReview(payer) {
  const [guardian] = await Promise.all([
    payer.waitForEvent('popup'),
    payer.getByRole('link', { name: 'Open guardian window' }).click(),
  ])
  await guardian.getByText('Waiting for a review request').waitFor()
  await payer.getByRole('button', { name: 'Check payment', exact: true }).click()
  await payer.getByRole('heading', { name: 'Waiting for your guardian' }).waitFor()
  await guardian.getByRole('button', { name: 'Open review' }).click()
  await guardian.getByRole('heading', { name: 'Review requested' }).waitFor()
  return guardian
}

const completion = (page) => page.getByRole('heading', { name: 'Simulated payment completed' })

test('same-browser windows approve a redacted review, reconnect, then confirm once', { timeout: 25_000 }, async (t) => {
  const { payer } = await setup(t)
  const guardian = await openReview(payer)
  const content = await guardian.locator('main').innerText()
  assert.doesNotMatch(content, /55,000|Willow Supplies|KYC or verification request/)
  assert.equal(await completion(payer).count(), 0)

  const readPattern = '**/api/v2/payments/pg_*'
  const failRead = (route) => route.abort()
  await payer.route(readPattern, failRead)
  await payer.getByRole('button', { name: 'Retry connection' }).waitFor()
  assert.equal(await payer.getByRole('button', { name: 'Stop this payment' }).isEnabled(), false)
  await guardian.getByRole('button', { name: 'Approve review' }).click()
  await guardian.getByRole('heading', { name: 'Review approved' }).waitFor()
  await payer.unroute(readPattern, failRead)
  await payer.getByRole('heading', { name: 'Ready for your confirmation' }).waitFor()
  assert.equal(await completion(payer).count(), 0)

  let confirmRequests = 0
  payer.on('request', (request) => {
    if (request.url().endsWith('/confirm')) confirmRequests += 1
  })
  await payer.getByRole('button', { name: 'Confirm simulated payment' }).dblclick()
  await completion(payer).waitFor()
  await payer.reload()
  await completion(payer).waitFor()
  assert.equal(await completion(payer).count(), 1)
  assert.equal(confirmRequests, 1)
})

test('separate browser profiles can find a request by reference and reject it', { timeout: 20_000 }, async (t) => {
  const { browser, payer } = await setup(t)
  const guardian = await (await browser.newContext()).newPage()
  await guardian.goto(`${origin}/guardian`)
  await payer.getByRole('button', { name: 'Check payment', exact: true }).click()
  await payer.getByRole('heading', { name: 'Waiting for your guardian' }).waitFor()
  const reference = await payer.locator('.reference code').innerText()
  await guardian.getByLabel('Request reference').fill(reference)
  await guardian.getByRole('button', { name: 'Find request' }).click()
  await guardian.getByRole('button', { name: 'Reject payment' }).click()
  await payer.getByRole('heading', { name: 'Payment rejected' }).waitFor()
  await guardian.getByRole('heading', { name: 'Payment rejected' }).waitFor()
  assert.equal(await completion(payer).count(), 0)
})

test('expiry closes both windows and leaves the payer able to stop the payment', { timeout: 45_000 }, async (t) => {
  const { payer } = await setup(t)
  const guardian = await openReview(payer)
  await guardian.getByRole('heading', { name: 'Review window closed' }).waitFor({ timeout: 35_000 })
  await payer.getByRole('heading', { name: 'Review window closed' }).waitFor()
  assert.equal(await guardian.getByRole('button', { name: 'Approve review' }).count(), 0)
  assert.equal(await payer.getByRole('button', { name: 'Confirm simulated payment' }).count(), 0)
  await payer.getByRole('button', { name: 'Stop this payment' }).click()
  await payer.getByRole('heading', { name: 'Payment stopped' }).waitFor()
})

test('mobile keyboard entry and retry preserve the original creation key after a lost response', { timeout: 20_000 }, async (t) => {
  const { payer } = await setup(t, { viewport: { width: 360, height: 780 }, isMobile: true, hasTouch: true })
  assert.equal(await payer.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true)
  await payer.getByRole('button', { name: 'Everyday purchase' }).click()
  const amount = payer.getByRole('textbox', { name: 'Amount (INR)' })
  assert.equal(await amount.getAttribute('inputmode'), 'decimal')
  await amount.focus()
  await payer.keyboard.press('ControlOrMeta+a')
  await payer.keyboard.type('100.05')
  await payer.keyboard.press('Tab')
  assert.equal(await payer.evaluate(() => document.activeElement.name), 'beneficiary')

  const attempts = []
  let firstId
  await payer.route('**/api/v2/payments', async (route) => {
    attempts.push(route.request().postDataJSON())
    if (attempts.length === 1) {
      const response = await route.fetch()
      firstId = (await response.json()).id
      await route.abort()
    } else {
      await route.continue()
    }
  })
  await payer.keyboard.press('Tab')
  await payer.keyboard.press('Tab')
  await payer.keyboard.press('Enter')
  await payer.getByRole('alert').filter({ hasText: /demo API is unavailable/ }).waitFor()
  await payer.reload()
  await payer.getByRole('button', { name: 'Retry this request' }).click()
  await payer.getByRole('heading', { name: 'Ready for your confirmation' }).waitFor()
  assert.equal(await payer.locator('.reference code').innerText(), firstId)
  assert.deepEqual(attempts[0], attempts[1])
  assert.equal(attempts[0].amount_paise, 10_005)
  await payer.getByRole('button', { name: 'Stop this payment' }).click()
  await payer.getByRole('heading', { name: 'Payment stopped' }).waitFor()
})

test('mobile localization preserves the draft and presents validation, focus and reduced motion', { timeout: 20_000 }, async (t) => {
  const { payer } = await setup(t, { viewport: { width: 360, height: 780 }, reducedMotion: 'reduce' })
  const language = payer.locator('.locale-control select')
  const amount = payer.locator('#amount')
  const warning = payer.getByRole('alert')
  await amount.fill('0')
  await payer.getByRole('button', { name: 'Check payment', exact: true }).click()
  await warning.filter({ hasText: 'Enter a positive rupee amount' }).waitFor()
  assert.equal(await amount.getAttribute('aria-invalid'), 'true')
  assert.equal(await amount.evaluate((element) => element === document.activeElement), true)
  assert.equal(await payer.locator('.amount-field').evaluate((el) => getComputedStyle(el).outlineStyle), 'solid')
  assert.equal(await payer.locator('.workspace-card').evaluate((el) => getComputedStyle(el).animationName), 'none')
  await amount.fill('100.05')
  for (const [locale, family, sample] of [
    ['kn', 'Noto Sans Kannada Variable', 'ಕನ್ನಡ'],
    ['hi', 'Noto Sans Devanagari Variable', 'हिन्दी'],
    ['te', 'Noto Sans Telugu Variable', 'తెలుగు'],
  ]) {
    await language.selectOption(locale)
    await payer.waitForFunction((lang) => document.documentElement.lang === lang, locale)
    const loaded = await payer.evaluate(async ([font, text]) => {
      const faces = await document.fonts.load(`600 20px "${font}"`, text)
      return faces.some((face) => face.status === 'loaded')
    }, [family, sample])
    assert.equal(loaded, true)
    assert.equal(await amount.inputValue(), '100.05')
    assert.equal(await payer.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true)
  }
  await payer.reload()
  await payer.waitForFunction(() => document.documentElement.lang === 'te')
  await language.selectOption('en')
  await payer.getByRole('heading', { name: 'Prepare a payment' }).waitFor()
})

test('warning guidance and a lost confirmation response resolve to the authoritative outcome', { timeout: 20_000 }, async (t) => {
  const { payer } = await setup(t)
  await payer.getByRole('button', { name: 'Unfamiliar supplier' }).click()
  await payer.getByRole('button', { name: 'Check payment', exact: true }).click()
  await payer.getByRole('heading', { name: 'Review this payment' }).waitFor()
  assert.equal(await payer.locator('[aria-current="step"]').innerText(), '02\nReview')
  await payer.getByText('How to verify the request', { exact: true }).click()
  await payer.getByText(/Contact the recipient using a saved number/).waitFor()
  await payer.getByRole('button', { name: 'I verified the recipient' }).click()
  await payer.getByRole('heading', { name: 'Ready for your confirmation' }).waitFor()
  assert.equal(await completion(payer).count(), 0)

  let confirmationPosts = 0
  await payer.route('**/confirm', async (route) => {
    confirmationPosts += 1
    await route.fetch()
    await route.abort()
  })
  await payer.getByRole('button', { name: 'Confirm simulated payment' }).click()
  await completion(payer).waitFor()
  assert.equal(confirmationPosts, 1)
  assert.equal(await payer.locator('[aria-current="step"]').innerText(), '03\nOutcome')
  assert.equal(await payer.getByRole('alert').count(), 0)
  await payer.getByRole('button', { name: 'Start another payment' }).click()
  assert.equal(await payer.getByRole('heading', { name: 'Prepare a payment' }).evaluate((el) => el === document.activeElement), true)
})

test('guardian rejects an unexpected private response and recovers on a clean status check', { timeout: 20_000 }, async (t) => {
  const { payer } = await setup(t)
  const guardian = await openReview(payer)
  const readPattern = '**/api/v2/payments/pg_*'
  const leakedRead = async (route) => {
    const response = await route.fetch()
    const payment = await response.json()
    await route.fulfill({ response, json: { ...payment, amount_paise: 5_500_000, beneficiary_id: 'Willow Supplies' } })
  }
  await guardian.route(readPattern, leakedRead)
  await guardian.getByRole('heading', { name: 'Payment status unavailable' }).waitFor()
  assert.doesNotMatch(await guardian.locator('main').innerText(), /55,000|Willow Supplies/)
  assert.equal(await guardian.getByRole('button', { name: 'Approve review' }).isEnabled(), false)
  await guardian.unroute(readPattern, leakedRead)
  await guardian.getByRole('button', { name: 'Retry connection' }).click()
  await guardian.getByRole('heading', { name: 'Review requested' }).waitFor()
  assert.equal(await guardian.getByRole('button', { name: 'Approve review' }).isEnabled(), true)
})

test('flagged demo recipient is rejected without opening a guardian request', { timeout: 20_000 }, async (t) => {
  const { payer } = await setup(t)
  await payer.getByRole('button', { name: 'Flagged recipient' }).click()
  await payer.getByRole('button', { name: 'Check payment', exact: true }).click()
  await payer.getByRole('heading', { name: 'Payment rejected' }).waitFor()
  await payer.getByText(/A safety rule stopped this request/).waitFor()
  assert.equal(await payer.getByRole('button', { name: 'Confirm simulated payment' }).count(), 0)
  assert.equal(await payer.evaluate(() => localStorage.getItem('pauseguard:demo:guardian-request')), null)
})
