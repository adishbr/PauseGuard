import { useEffect, useRef, useState } from 'react'
import { beneficiaries, purposes } from '../../mocks/scenarios.ts'
import { usePayment } from '../hooks/usePayment.ts'
import type { MessageKey } from '../locales/en.ts'
import { languages, translator } from '../locales/messages.ts'
import type { Locale, Translate } from '../locales/messages.ts'
import { formatRupees } from '../services/demoSession.ts'
import { isRealBackendMode } from '../services/backendMode.ts'
import {
  activateBackupGuardian,
  activateFallback,
  createPaymentAppeal,
  guardianDecision,
  listPaymentAppeals,
  payerAction,
  paymentError,
  retryPayment,
  verifyStepUp,
} from '../services/paymentApi.ts'
import type { V5PaymentAppeal } from '../services/paymentApi.ts'
import { terminalStatuses } from '../types/payment.ts'
import type { Role, Status } from '../types/payment.ts'
import { Icon } from './Icon.tsx'
import { PaymentSteps } from './PaymentSteps.tsx'

type Copy = readonly [MessageKey, MessageKey]
const labels: Record<Status, Copy> = {
  CREATED: ['createdTitle', 'createdDetail'],
  AWAITING_WARNING: ['warningTitle', 'warningDetail'],
  AWAITING_STEP_UP: ['stepUpTitle', 'stepUpDetail'],
  AWAITING_GUARDIAN: ['waitingTitle', 'waitingDetail'],
  AWAITING_FALLBACK_REVIEW: ['fallbackTitle', 'fallbackDetail'],
  READY_TO_EXECUTE: ['readyTitle', 'readyDetail'],
  EXECUTED: ['executedTitle', 'executedDetail'],
  REJECTED: ['rejectedTitle', 'rejectedDetail'],
  CANCELLED: ['cancelledTitle', 'cancelledDetail'],
  EXPIRED: ['expiredTitle', 'expiredDetail'],
  FAILED: ['failedTitle', 'failedDetail'],
}

const guardianLabels: Partial<Record<Status, Copy>> = {
  AWAITING_GUARDIAN: ['guardianPendingTitle', 'guardianPendingDetail'],
  AWAITING_FALLBACK_REVIEW: ['fallbackTitle', 'guardianFallbackDetail'],
  READY_TO_EXECUTE: ['guardianReadyTitle', 'guardianReadyDetail'],
  CANCELLED: ['cancelledTitle', 'guardianCancelledDetail'],
}

const reasons = new Map<string, MessageKey>([
  ['RC_NEW_BENEFICIARY', 'newRecipient'],
  ['RC_LARGE_DEVIATION', 'largeDeviation'],
  ['RC_COERCION_PURPOSE', 'coercion'],
  ['RC_CUSTOMER_ALERT_PREFERENCE', 'alertPreference'],
])
const tiers = ['routineTier', 'warningTier', 'stepUpTier', 'restrictionTier'] as const
type Action = 'confirm' | 'cancel' | 'warning/acknowledge' | 'approve' | 'reject'

function useRemaining(deadline: string | null, offset: number) {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    if (!deadline) return
    const interval = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(interval)
  }, [deadline])
  return deadline ? Math.max(0, Math.ceil((Date.parse(deadline) - now - offset) / 1_000)) : null
}

function Reference({ id, t }: { id: string; t: Translate }) {
  const [feedback, setFeedback] = useState<'copied' | 'copyFallback'>()

  async function copy() {
    try {
      await navigator.clipboard.writeText(id)
      setFeedback('copied')
    } catch {
      setFeedback('copyFallback')
    }
  }

  return (
    <div className="reference">
      <div className="reference-row">
        <div>
          <span className="reference-label">{t('reference')}</span>
          <code>{id}</code>
        </div>
        <button className="text-button copy-ref-btn" type="button" onClick={() => void copy()}>
          <Icon name="copy" size={14} />
          <span>{t('copy')}</span>
        </button>
      </div>
      <div role="status" className="copy-feedback-msg">{feedback ? t(feedback) : ''}</div>
    </div>
  )
}

export function PaymentStatus({ role, token, id, locale, onClose, onSelectPayment }: {
  role: Role; token: string; id: string; locale: Locale; onClose: () => void; onSelectPayment?: (nextId: string) => void
}) {
  const t = translator(locale)
  const { snapshot, error, checking, accept, refresh } = usePayment(role, token, id)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<{ status: Status; key: MessageKey }>()
  const [appeals, setAppeals] = useState<V5PaymentAppeal[]>([])
  const [appealReason, setAppealReason] = useState('')
  const [v5StatusNote, setV5StatusNote] = useState('')
  const [v5ErrorNote, setV5ErrorNote] = useState('')
  const inFlight = useRef(false)
  const heading = useRef<HTMLHeadingElement>(null)
  const checkedDeadline = useRef<string | null>(null)
  const payment = snapshot?.payment
  const status = payment?.status
  const deadline = payment?.status === 'AWAITING_GUARDIAN' ? payment.guardian_deadline : null
  const remaining = useRemaining(deadline, snapshot?.serverOffset ?? 0)
  const terminal = status && terminalStatuses.has(status)
  const disconnected = !terminal && Boolean(error)
  const pendingCheck = !terminal && checking

  useEffect(() => {
    if (document.activeElement === document.body) heading.current?.focus()
  }, [status])

  useEffect(() => {
    if (remaining === 0 && deadline && !checking && !error && !busy && checkedDeadline.current !== deadline) {
      checkedDeadline.current = deadline
      if (role === 'payer' && isRealBackendMode()) {
        void activateFallback(token, id).then(accept).catch(() => refresh())
      } else {
        refresh()
      }
    }
  }, [remaining, deadline, checking, error, busy, role, token, id, accept, refresh])

  const appealEligible =
    isRealBackendMode() &&
    role === 'payer' &&
    (status === 'REJECTED' || status === 'EXPIRED' || status === 'FAILED' || status === 'AWAITING_FALLBACK_REVIEW')

  useEffect(() => {
    if (!appealEligible) return
    let active = true
    void listPaymentAppeals(token, id)
      .then((rows) => { if (active) setAppeals(rows) })
      .catch(() => {})
    return () => { active = false }
  }, [appealEligible, id, token])

  async function runStepUp() {
    if (inFlight.current || busy) return
    inFlight.current = true
    setBusy(true)
    setV5ErrorNote('')
    setV5StatusNote('')
    try {
      const updated = await verifyStepUp(token, id)
      accept(updated)
      setV5StatusNote('Step-up challenge verified.')
    } catch {
      setV5ErrorNote('Step-up verification failed or expired.')
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  async function runBackupFailover() {
    if (inFlight.current || busy) return
    inFlight.current = true
    setBusy(true)
    setV5ErrorNote('')
    setV5StatusNote('')
    try {
      const updated = await activateBackupGuardian(token, id)
      accept(updated)
      setV5StatusNote('Routed payment review to your enrolled backup guardian.')
    } catch {
      setV5ErrorNote('No active backup guardian enrolled for failover.')
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  async function submitAppeal() {
    if (inFlight.current || busy || appealReason.trim().length < 5) {
      setV5ErrorNote('Enter an explanation (at least 5 characters) before submitting an appeal.')
      return
    }
    inFlight.current = true
    setBusy(true)
    setV5ErrorNote('')
    setV5StatusNote('')
    try {
      const created = await createPaymentAppeal(token, id, { reason: appealReason })
      setAppeals((prev) => [created, ...prev])
      setAppealReason('')
      setV5StatusNote('Appeal submitted for independent analyst review.')
    } catch {
      setV5ErrorNote('Could not submit appeal for this transaction.')
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  async function runSafeRetry() {
    if (inFlight.current || busy) return
    inFlight.current = true
    setBusy(true)
    setV5ErrorNote('')
    setV5StatusNote('')
    try {
      const child = await retryPayment(token, id)
      if (onSelectPayment) {
        onSelectPayment(child.payment.id)
      } else {
        accept(child)
      }
    } catch {
      setV5ErrorNote('Safe retry unavailable until an analyst approves the appeal (if rejected) or policy permits.')
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  async function act(action: Action) {
    if (inFlight.current || checking || error || !status) return
    const guardianAction = action === 'approve' || action === 'reject'
    if (guardianAction && (remaining === null || remaining === 0)) return

    inFlight.current = true
    setBusy(true)
    setActionError(undefined)
    try {
      accept(guardianAction ? await guardianDecision(token, id, action) : await payerAction(token, id, action))
    } catch (failure) {
      setActionError({ status, key: paymentError(failure).key })
      refresh()
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  const disabled = pendingCheck || disconnected || busy
  const showActions = status && status !== 'CREATED' && !terminal
  const tone = disconnected || pendingCheck ? 'neutral' :
    status === 'REJECTED' || status === 'FAILED' ? 'danger' :
    status === 'CANCELLED' || status === 'EXPIRED' ? 'neutral' :
    status?.startsWith('AWAITING_') ? 'caution' : 'mint'
  const noGuardian = status === 'AWAITING_FALLBACK_REVIEW' && payment?.guardian_deadline === null
  const [title, description] = noGuardian ? ['noGuardianTitle', 'noGuardianDetail'] as const : status ?
    (role === 'guardian' ? guardianLabels[status] ?? labels[status] : labels[status]) :
    ['checkingStatus', 'connecting'] as const
  const statusDetail = role === 'payer' && payment?.status === 'REJECTED' && !payment.guardian_deadline ?
    'blockedDetail' : description
  const visibleTitle = disconnected ? 'unavailable' : pendingCheck ? 'checkingStatus' : title
  const paymentDetails = role === 'payer' && payment && 'amount_paise' in payment ? payment : undefined
  const help = status?.startsWith('AWAITING_') || status === 'REJECTED'
  const purpose = paymentDetails?.purpose ?? ''

  // Radial progress calculations
  const totalDuration = snapshot?.reviewDuration ?? 30
  const progressRatio = remaining !== null ? Math.max(0, Math.min(1, remaining / totalDuration)) : 0
  const circleCircumference = 2 * Math.PI * 22 // radius = 22, circumference ≈ 138.2
  const strokeOffset = circleCircumference * (1 - progressRatio)

  return (
    <>
      {role === 'payer' && <PaymentSteps current={terminal ? 2 : 1} t={t} />}
      <section className={`card workspace-card status-card tone-${tone}`} aria-labelledby="status-heading">
        <div className="card-header">
          <div className={`symbol ${tone}`}>
            <Icon name={status === 'EXECUTED' ? 'check' : status === 'AWAITING_GUARDIAN' ? 'clock' : status === 'REJECTED' ? 'shieldAlert' : 'shield'} />
          </div>
          <div className="grow">
            <p className="eyebrow">{t(role === 'guardian' ? 'guardianInbox' : 'status')}</p>
            <h2 id="status-heading" tabIndex={-1} ref={heading}>{t(visibleTitle)}</h2>
          </div>
          {payment && !disconnected && !pendingCheck && (
            <span className={`pill ${tone} tier-indicator`}>
              <span className="dot" />
              {t(tiers[payment.tier])}
            </span>
          )}
        </div>

        <div role="status" className="status-copy">
          {pendingCheck && <p className="inline-progress"><span className="spinner" aria-hidden="true" />{t(payment ? 'checkingStatus' : 'connecting')}</p>}
          {!pendingCheck && !disconnected && <p><span className="sr-only">{t(title)}. </span>{t(statusDetail)}</p>}
          {(pendingCheck || disconnected) && payment && <p>{t('lastKnown')}</p>}
          {busy && <p className="inline-progress"><span className="spinner" aria-hidden="true" /> {t('sending')}</p>}
        </div>

        {error && (
          <div className="notice">
            <p role="alert">{t(error.key)}</p>
            <button className="secondary" type="button" disabled={checking || busy} onClick={refresh}>{t('retryConnection')}</button>
          </div>
        )}
        {actionError && !checking && !error && status === actionError.status && (
          <p className="notice" role="alert">{t(actionError.key)} {t('actionUnconfirmed')}</p>
        )}

        {/* Real-time Timer with Animated Radial SVG Ring and tabular digits */}
        {remaining !== null && !disconnected && (
          <div className="timer radial-timer-container">
            <div className="radial-timer-visual" aria-hidden="true">
              <svg width="56" height="56" viewBox="0 0 56 56">
                <circle className="ring-track" cx="28" cy="28" r="22" />
                <circle
                  className={`ring-fill ${remaining <= 10 ? 'ring-critical' : ''}`}
                  cx="28"
                  cy="28"
                  r="22"
                  strokeDasharray={circleCircumference}
                  strokeDashoffset={strokeOffset}
                />
              </svg>
              <div className="timer-icon-center">
                <Icon name="clock" size={18} />
              </div>
            </div>
            <div className="timer-info-block">
              <strong>{t(remaining === 0 ? 'deadlineChecking' : 'timeLeft')}</strong>
              <p>{t('deadlineSource')}</p>
            </div>
            <time className="timer-value" dateTime={deadline ?? undefined} aria-hidden="true">
              {Math.floor(remaining / 60)}:{String(remaining % 60).padStart(2, '0')}
            </time>
            <span className="sr-only">{t('secondsRemaining')} {remaining}</span>
            {snapshot?.reviewDuration && (
              <progress aria-hidden="true" max={snapshot.reviewDuration} value={remaining} />
            )}
          </div>
        )}

        {/* Transaction Ready Checklist for Final Payer Confirmation */}
        {status === 'READY_TO_EXECUTE' && role === 'payer' && (
          <div className="ready-checklist-box">
            <div className="checklist-header">
              <Icon name="shieldCheck" size={18} />
              <strong>Execution Pre-Check Complete</strong>
            </div>
            <ul className="checklist-items">
              <li><Icon name="check" size={14} /> Independent Guardian Approved &amp; Logged</li>
              <li><Icon name="check" size={14} /> Adversarial Coercion Filters Cleared</li>
              <li><Icon name="check" size={14} /> Safe-Lock Verification Passed</li>
            </ul>
            <p className="checklist-note">Payer confirmation is required to commit simulated funds to the mock ledger.</p>
          </div>
        )}

        {paymentDetails && (
          <dl className="payment-details">
            <div><dt>{t('amount')}</dt><dd>{formatRupees(paymentDetails.amount_paise, languages[locale].region)}</dd></div>
            <div><dt>{t('recipient')}</dt><dd>{Object.hasOwn(beneficiaries, paymentDetails.beneficiary_id) ?
              beneficiaries[paymentDetails.beneficiary_id as keyof typeof beneficiaries] : paymentDetails.beneficiary_id}</dd></div>
            <div><dt>{t('purpose')}</dt><dd>{Object.hasOwn(purposes, purpose) ? t(purpose as keyof typeof purposes) : purpose}</dd></div>
          </dl>
        )}

        {paymentDetails && paymentDetails.reason_codes.length > 0 && (
          <div className="risk-context">
            <h3>{t('why')}</h3>
            <ul className="reasons">
              {paymentDetails.reason_codes.map((code) => <li key={code}>{t(reasons.get(code) ?? 'genericReason')}</li>)}
            </ul>
          </div>
        )}

        {help && !disconnected && (
          <details className="verify-note">
            <summary>{t('verify')}</summary>
            <p>{t(role === 'guardian' ? 'guardianVerify' : 'payerVerify')}</p>
          </details>
        )}

        <div className="actions">
          {showActions && role === 'payer' && (
            <>
              {status === 'READY_TO_EXECUTE' && (
                <button type="button" className="primary execute-confirm-btn" disabled={disabled} onClick={() => void act('confirm')}>
                  {t('confirm')} <Icon name="arrow" size={18} />
                </button>
              )}
              {status === 'AWAITING_STEP_UP' && isRealBackendMode() && (
                <button type="button" className="primary" disabled={disabled} onClick={() => void runStepUp()}>
                  Complete step-up verification <Icon name="arrow" size={18} />
                </button>
              )}
              {status === 'AWAITING_WARNING' && (
                <button type="button" className="primary" disabled={disabled} onClick={() => void act('warning/acknowledge')}>
                  {t('acknowledge')} <Icon name="arrow" size={18} />
                </button>
              )}
              {(status === 'AWAITING_GUARDIAN' || status === 'AWAITING_FALLBACK_REVIEW') && isRealBackendMode() && (
                <button type="button" className="secondary" disabled={busy} onClick={() => void runBackupFailover()}>
                  Route to Backup Guardian
                </button>
              )}
              <button type="button" className="secondary" disabled={disabled} onClick={() => void act('cancel')}>
                {t('stop')}
              </button>
            </>
          )}
          {status === 'AWAITING_GUARDIAN' && role === 'guardian' && (
            <>
              <button
                type="button"
                className="reject"
                disabled={disabled || remaining === null || remaining === 0}
                onClick={() => void act('reject')}
              >
                {t('reject')}
              </button>
              <button
                type="button"
                className="secondary approve-btn"
                disabled={disabled || remaining === null || remaining === 0}
                onClick={() => void act('approve')}
              >
                {t('approve')}
              </button>
            </>
          )}
          {role === 'guardian' && (
            <button type="button" className="text-button" disabled={busy} onClick={onClose}>
              {t('back')}
            </button>
          )}
          {role === 'payer' && error?.status === 404 && (
            <button type="button" className="secondary" disabled={checking} onClick={onClose}>
              {t('clearRequest')}
            </button>
          )}
          {role === 'payer' && terminal && (
            <button type="button" className="primary" onClick={onClose}>
              {t('startAnother')} <Icon name="arrow" size={18} />
            </button>
          )}
        </div>

        {v5StatusNote && <p role="status" className="notice" style={{ marginTop: '0.75rem' }}>{v5StatusNote}</p>}
        {v5ErrorNote && <p role="alert" className="notice" style={{ marginTop: '0.75rem' }}>{v5ErrorNote}</p>}

        {appealEligible && (
          <div className="enrollment-item" style={{ marginTop: '1rem' }}>
            <h3>False-Alert Appeal &amp; Safe Retry</h3>
            <p className="field-help">
              If this block or timeout happened on a verified legitimate payment, submit an appeal for analyst review or trigger a policy-checked retry.
            </p>
            <label style={{ marginTop: '0.5rem' }}>
              Appeal explanation
              <input
                value={appealReason}
                onChange={(e) => setAppealReason(e.target.value)}
                placeholder="e.g. Verified invoice with supplier offline"
              />
            </label>
            <div className="actions" style={{ marginTop: '0.6rem' }}>
              <button type="button" className="secondary" disabled={busy} onClick={() => void submitAppeal()}>
                Submit false-alert appeal
              </button>
              <button
                type="button"
                className="primary"
                disabled={busy || (status === 'REJECTED' && !appeals.some((a) => a.status === 'APPROVED_RETRY_ELIGIBLE'))}
                onClick={() => void runSafeRetry()}
              >
                Safe retry payment
              </button>
            </div>
            {appeals.length > 0 && (
              <ul className="reasons" style={{ marginTop: '0.65rem' }}>
                {appeals.map((a) => (
                  <li key={a.appeal_id}>
                    <strong>{a.status}</strong>: {a.reason}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {payment && role === 'guardian' && (
          <div className="guardian-privacy-shield-banner">
            <Icon name="lock" size={16} />
            <span>{t('guardianPrivacy')}</span>
          </div>
        )}

        {payment && <Reference id={payment.id} t={t} />}
      </section>
    </>
  )
}
