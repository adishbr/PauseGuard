import { useEffect, useRef, useState } from 'react'
import { beneficiaries, purposes } from '../../mocks/scenarios.ts'
import { usePayment } from '../hooks/usePayment.ts'
import { formatRupees } from '../services/demoSession.ts'
import { guardianDecision, payerAction } from '../services/paymentApi.ts'
import { terminalStatuses } from '../types/payment.ts'
import type { Role, Status } from '../types/payment.ts'
import { Icon } from './Icon.tsx'

const labels: Record<Status, [string, string]> = {
  CREATED: ['Checking payment', 'PauseGuard is evaluating the request.'],
  AWAITING_WARNING: ['Review this payment', 'Verify the recipient using a contact method you already trust before continuing.'],
  AWAITING_STEP_UP: ['Independent verification required', 'Stop and verify the request through a trusted channel. This demo cannot complete independent verification.'],
  AWAITING_GUARDIAN: ['Waiting for your guardian', 'Your guardian can review this request before you decide whether to continue.'],
  AWAITING_FALLBACK_REVIEW: ['Review window closed', 'The payment is still on hold. Verify the request independently or stop this payment.'],
  READY_TO_EXECUTE: ['Ready for your confirmation', 'Check the details below. The simulated payment only completes after you confirm.'],
  EXECUTED: ['Simulated payment completed', 'The demo API confirmed the transfer.'],
  REJECTED: ['Payment rejected', 'The request was stopped before any simulated transfer.'],
  CANCELLED: ['Payment stopped', 'You cancelled the request before any simulated transfer.'],
  EXPIRED: ['Payment expired', 'The request closed before any simulated transfer.'],
  FAILED: ['Payment failed', 'Start a new request after checking the details.'],
}

const guardianLabels: Partial<Record<Status, [string, string]>> = {
  AWAITING_GUARDIAN: ['Review requested', 'If you can independently verify that the request is legitimate, you can let the payer continue. If you are unsure, stop the payment.'],
  AWAITING_FALLBACK_REVIEW: ['Review window closed', 'The payment remains on hold and your decision is no longer accepted.'],
  READY_TO_EXECUTE: ['Review approved', 'The payer still needs to confirm their simulated payment.'],
  REJECTED: ['Payment rejected', 'The payment was stopped before any simulated transfer.'],
  CANCELLED: ['Payment stopped', 'The payer cancelled the request.'],
}

const reasons: Record<string, string> = {
  RC_NEW_BENEFICIARY: 'This recipient is unfamiliar for this demo account.',
  RC_LARGE_DEVIATION: 'This amount is higher than the demo account’s usual payments.',
  RC_COERCION_PURPOSE: 'Payment requests framed as KYC or verification can be a scam.',
  RC_CUSTOMER_ALERT_PREFERENCE: 'This request meets the demo account’s alert preference.',
}

const tiers = ['Routine check', 'Safety warning', 'Extra verification', 'Safety restriction']

function useRemaining(deadline: string | null, offset: number) {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    if (!deadline) return
    const interval = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(interval)
  }, [deadline])
  return deadline ? Math.max(0, Math.ceil((Date.parse(deadline) - now - offset) / 1_000)) : null
}

export function PaymentStatus({ role, id, onClose }: { role: Role, id: string, onClose: () => void }) {
  const { snapshot, error, checking, accept, refresh } = usePayment(role, id)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const inFlight = useRef(false)
  const heading = useRef<HTMLHeadingElement>(null)
  const payment = snapshot?.payment
  const remaining = useRemaining(payment?.status === 'AWAITING_GUARDIAN' ? payment.guardian_deadline : null,
    snapshot?.serverOffset ?? 0)

  async function act(action: 'confirm' | 'cancel' | 'warning/acknowledge' | 'approve' | 'reject') {
    if (inFlight.current || checking || error) return
    inFlight.current = true
    setBusy(true)
    setActionError('')
    try {
      accept(action === 'approve' || action === 'reject' ?
        await guardianDecision(id, action) : await payerAction(id, action))
    } catch (failure) {
      setActionError(failure instanceof Error ? failure.message : 'The action could not be confirmed.')
      refresh()
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  const status = payment?.status
  useEffect(() => {
    if (document.activeElement === document.body) heading.current?.focus()
  }, [status])
  const disabled = checking || Boolean(error) || busy
  const terminal = status && terminalStatuses.has(status)
  const showActions = status && !terminal
  const tone = status === 'REJECTED' || status === 'FAILED' ? 'danger' :
    status?.startsWith('AWAITING_') ? 'caution' : 'mint'
  const [title, description] = status ?
    (role === 'guardian' ? guardianLabels[status] ?? labels[status] : labels[status]) :
    ['Checking payment status', 'Connecting to the local demo API.']
  const paymentDetails = role === 'payer' && payment && 'amount_paise' in payment ? payment : undefined

  return (
    <section className="card status-card" aria-labelledby="status-heading">
      <div className="card-header">
        <div className={`symbol ${tone}`}><Icon name={status === 'EXECUTED' ? 'check' : 'shield'} /></div>
        <div className="grow">
          <p className="eyebrow">{role === 'guardian' ? 'Guardian inbox' : 'Payment status'}</p>
          <h2 id="status-heading" tabIndex={-1} ref={heading}>{error && !status ? 'Payment status unavailable' : title}</h2>
        </div>
        {payment && <span className={`pill ${tone}`}>{tiers[payment.tier]}</span>}
      </div>

      <div role="status" className="status-copy">
        {checking && payment ? <p>Checking payment status…</p> : error && !status ? null : <p><span className="sr-only">{title}. </span>{description}</p>}
        {busy && <p>Sending your action…</p>}
      </div>
      {error && (
        <div className="notice">
          <p role="alert">{error.message}</p>
          <button className="secondary" type="button" disabled={checking || busy} onClick={refresh}>Retry connection</button>
        </div>
      )}
      {actionError && <p className="notice" role="alert">{actionError}</p>}

      {status === 'AWAITING_GUARDIAN' && (
        <div className="timer">
          <Icon name="clock" />
          <div>
            <strong>{remaining === 0 ? 'Checking whether the review has closed' : 'Time left to review'}</strong>
            <p>Review time is set by the demo API.</p>
          </div>
          {remaining !== null && <span className="timer-value" aria-label={`${remaining} seconds remaining`}>0:{String(remaining).padStart(2, '0')}</span>}
        </div>
      )}

      {paymentDetails && (
        <dl className="payment-details">
          <div><dt>Amount</dt><dd>{formatRupees(paymentDetails.amount_paise)}</dd></div>
          <div><dt>Recipient</dt><dd>{beneficiaries[paymentDetails.beneficiary_id as keyof typeof beneficiaries] ?? paymentDetails.beneficiary_id}</dd></div>
          <div><dt>Purpose</dt><dd>{purposes[paymentDetails.purpose as keyof typeof purposes] ?? paymentDetails.purpose}</dd></div>
        </dl>
      )}
      {paymentDetails && paymentDetails.reason_codes.length > 0 && (
        <ul className="reasons">
          {paymentDetails.reason_codes.map((code) => <li key={code}>{reasons[code] ?? 'PauseGuard flagged a detail for review.'}</li>)}
        </ul>
      )}
      {payment && <p className="reference">Request reference <code>{payment.id}</code></p>}

      <div className="actions">
        {showActions && role === 'payer' && (
          <>
            {status === 'READY_TO_EXECUTE' && <button type="button" className="primary" disabled={disabled} onClick={() => void act('confirm')}>Confirm simulated payment <Icon name="arrow" size={18} /></button>}
            {status === 'AWAITING_WARNING' && <button type="button" className="primary" disabled={disabled} onClick={() => void act('warning/acknowledge')}>I verified the recipient <Icon name="arrow" size={18} /></button>}
            <button type="button" className="secondary" disabled={disabled} onClick={() => void act('cancel')}>Stop this payment</button>
          </>
        )}
        {status === 'AWAITING_GUARDIAN' && role === 'guardian' && (
          <>
            <button type="button" className="reject" disabled={disabled || remaining === null || remaining === 0} onClick={() => void act('reject')}>Reject payment</button>
            <button type="button" className="secondary" disabled={disabled || remaining === null || remaining === 0} onClick={() => void act('approve')}>Approve review</button>
          </>
        )}
        {role === 'guardian' && <button type="button" className="text-button" disabled={busy} onClick={onClose}>Back to inbox</button>}
        {role === 'payer' && error?.status === 404 && (
          <button type="button" className="secondary" onClick={onClose}>Clear unavailable request</button>
        )}
        {role === 'payer' && terminal && <button type="button" className="primary" onClick={onClose}>Start another payment <Icon name="arrow" size={18} /></button>}
      </div>
    </section>
  )
}
