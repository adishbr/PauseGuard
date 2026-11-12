import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Icon } from '../components/Icon.tsx'
import { languages } from '../locales/messages.ts'
import type { Locale } from '../locales/messages.ts'
import { reviewDurations } from '../../mocks/reviewPreference.ts'
import type { ReviewDuration } from '../../mocks/reviewPreference.ts'
import { accountApi } from '../services/accountApi.ts'
import { storageWrite, toPaise } from '../services/demoSession.ts'
import { accountCategories, demoContact, demoName, isEmailContact, isMobileContact } from '../types/account.ts'
import type { AccountCategory, DemoSession } from '../types/account.ts'
import type { Role } from '../types/payment.ts'

export function Auth({ path, role, locale, onSession, expired }: {
  path: string; role: Role; locale: Locale; onSession: (session: DemoSession) => void; expired: boolean
}) {
  const guardian = role === 'guardian'
  const base = guardian ? '/guardian' : ''
  const signup = path.endsWith('/signup')
  const form = signup || path.endsWith('/login')
  const enrollmentReturn = guardian && (path === '/guardian/enrollment' ||
    new URLSearchParams(window.location.search).get('next') === '/guardian/enrollment')
  const authLink = (mode: 'signup' | 'login') => `${base}/${mode}${enrollmentReturn ? '?next=/guardian/enrollment' : ''}`

  const [stage, setStage] = useState(1)
  const [name, setName] = useState('')
  const [contact, setContact] = useState('')
  const [language, setLanguage] = useState(locale)
  const [category, setCategory] = useState<AccountCategory>('personal')
  const [organization, setOrganization] = useState('')
  const [largeText, setLargeText] = useState(false)
  const [thresholdInput, setThresholdInput] = useState('')
  const [chosenDuration, setChosenDuration] = useState<ReviewDuration>(30)
  const [consentAcknowledged, setConsentAcknowledged] = useState(true)
  const [visible, setVisible] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [invalid, setInvalid] = useState<'name' | 'contact'>()
  const sending = useRef(false)
  const nameInput = useRef<HTMLInputElement>(null)
  const contactInput = useRef<HTMLInputElement>(null)
  const stepHeading = useRef<HTMLHeadingElement>(null)

  const isEmail = isEmailContact(contact)
  const isMobile = isMobileContact(contact)

  async function submit(event?: FormEvent, sample = false) {
    event?.preventDefault()
    if (sending.current) return
    setError('')
    setInvalid(undefined)
    if (!sample) {
      if (signup && !demoName(name)) {
        setInvalid('name')
        setError('Enter a fictional full name with at least two letters.')
        nameInput.current?.focus()
        return
      }
      if (!demoContact(contact)) {
        setInvalid('contact')
        setError('Enter a valid email address (e.g. name@gmail.com) or 10-digit Indian mobile number.')
        contactInput.current?.focus()
        return
      }
      if (signup && stage === 1) {
        setStage(2)
        requestAnimationFrame(() => stepHeading.current?.focus())
        return
      }
    }
    sending.current = true
    setBusy(true)
    try {
      let session: DemoSession
      if (signup && !sample) {
        const thresholdPaise = thresholdInput.trim() ? toPaise(thresholdInput) : null
        session = await accountApi.register(role, {
          name, contact, language, category, organization,
          largeText, thresholdPaise: thresholdPaise ?? undefined,
        })
        if (!guardian && session.profile.id) {
          storageWrite('localStorage', `pauseguard:demo:review-seconds:${session.profile.id}`, String(chosenDuration))
        }
      } else {
        session = await accountApi.login(role, contact, sample)
      }
      onSession(session)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The demo could not sign you in.')
    } finally {
      sending.current = false
      setBusy(false)
    }
  }

  return (
    <div className="account-layout">
      {/* Left Column: Premium FinTech Security Showcase */}
      <section className="account-intro security-showcase">
        <div className="showcase-badge">
          <span className="symbol mint"><Icon name="shield" size={26} /></span>
          <span className="showcase-kicker">PauseGuard V2 · Fraud Defense Architecture</span>
        </div>
        <p className="eyebrow">{guardian ? 'Independent Guardian Network' : 'Deterministic APP Fraud Interventions'}</p>
        <h1>{guardian ? 'Trusted Guardian Circuit Breaker.' : 'Pause before you pay.'}</h1>
        <p className="showcase-lead">
          {guardian
            ? 'Act as a secure, independent circuit breaker. Review flagged transactions within authoritative time windows with zero access to sensitive financial histories.'
            : 'Next-generation payment safety for UPI. Real-time behavioral friction, coercion detection, and privacy-preserving guardian intervention before money transfers.'}
        </p>

        <div className="security-pillars">
          <div className="pillar-item">
            <div className="pillar-icon"><Icon name="lock" size={18} /></div>
            <div>
              <strong>Advisory Risk Engine</strong>
              <p>Flags high-pressure police impersonation, KYC extortion and rapid velocity smurfing.</p>
            </div>
          </div>
          <div className="pillar-item">
            <div className="pillar-icon"><Icon name="users" size={18} /></div>
            <div>
              <strong>Time-Bound Guardian Ring</strong>
              <p>Deterministic 30s/45s/60s countdowns. Timed-out reviews fail closed, never auto-approving.</p>
            </div>
          </div>
          <div className="pillar-item">
            <div className="pillar-icon"><Icon name="shield" size={18} /></div>
            <div>
              <strong>Zero-Knowledge Privacy</strong>
              <p>Guardians review safety tags only. Payer balances, recipient details and notes remain private.</p>
            </div>
          </div>
        </div>

        <div className="showcase-sandbox-card">
          <div className="sandbox-header">
            <span className="pulse-dot" />
            <span>Interactive Security Sandbox Active</span>
          </div>
          <div className="sandbox-metrics">
            <div>
              <span className="metric-label">Rail Mode</span>
              <span className="metric-val">Mock UPI (v2)</span>
            </div>
            <div>
              <span className="metric-label">Funds Status</span>
              <span className="metric-val text-mint">100% Synthetic</span>
            </div>
            <div>
              <span className="metric-label">Fail-Safe</span>
              <span className="metric-val">Fail Closed</span>
            </div>
          </div>
        </div>

        <div className="role-switch-container">
          <span className="field-help">Need to test the opposite perspective?</span>
          <a className="text-button role-switch-link" href={guardian ? '/' : '/guardian'}>
            {guardian ? 'Switch to payer workspace' : 'Switch to guardian review'} <Icon name="arrow" size={17} />
          </a>
        </div>
      </section>

      {/* Right Column: Premium Auth & Onboarding Card */}
      <section className="card account-card auth-card" aria-labelledby="auth-heading">
        <div className="auth-role-tabs" role="tablist" aria-label="Select demo workspace role">
          <a
            href="/"
            className={`role-tab ${!guardian ? 'active' : ''}`}
            role="tab"
            aria-selected={!guardian}
          >
            <Icon name="shield" size={16} />
            <span>Payer</span>
          </a>
          <a
            href="/guardian"
            className={`role-tab ${guardian ? 'active' : ''}`}
            role="tab"
            aria-selected={guardian}
          >
            <Icon name="users" size={16} />
            <span>Guardian</span>
          </a>
        </div>

        <div className="card-header-block">
          <p className="eyebrow">{guardian ? 'Guardian Workspace' : 'Payer Workspace'} · Demo Identity</p>
          <h2 id="auth-heading">{signup ? 'Create a demo account' : form ? 'Sign in' : 'Welcome to PauseGuard'}</h2>
          <p className="form-note">
            Use realistic or fictional details in this sandbox. Sign-in uses a demo identity without requiring real OTPs or passwords.
          </p>
        </div>

        {expired && <p role="alert" className="notice">Your demo session expired. Sign in again to continue.</p>}
        {error && <p id="auth-error" role="alert" className="notice">{error}</p>}

        {/* Quick Demo Access Bar */}
        <div className="sample-access quick-demo-box">
          <div className="quick-demo-copy">
            <strong>One-Click Demo Access</strong>
            <p className="field-help">Use pre-paired synthetic identities to test the full payer &amp; guardian intervention immediately.</p>
          </div>
          <button className="secondary quick-demo-btn" type="button" disabled={busy} onClick={() => void submit(undefined, true)}>
            <Icon name={guardian ? 'users' : 'shield'} size={18} />
            {guardian ? 'Open sample guardian' : 'Open sample payer'}
          </button>
        </div>

        {form ? (
          <form className="account-form" noValidate onSubmit={(event) => void submit(event)}>
            {signup && (
              <div className="onboarding-stepper">
                <div className="stepper-bar">
                  <div className="stepper-progress" style={{ width: stage === 1 ? '50%' : '100%' }} />
                </div>
                <p className="account-step">
                  Step {stage} of 2 · {stage === 1 ? 'Demo identity' : 'Preferences & Protection'}
                </p>
              </div>
            )}

            {/* STAGE 1: DEMO IDENTITY */}
            <fieldset hidden={signup && stage === 2} disabled={busy}>
              {signup && (
                <label>
                  Full name
                  <input
                    ref={nameInput}
                    value={name}
                    maxLength={64}
                    required
                    autoComplete="off"
                    aria-invalid={invalid === 'name' || undefined}
                    aria-describedby={invalid === 'name' ? 'auth-error' : undefined}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="e.g. Asha Sharma"
                  />
                </label>
              )}

              <label>
                Email or mobile
                <input
                  ref={contactInput}
                  value={contact}
                  maxLength={90}
                  required
                  autoComplete="off"
                  spellCheck={false}
                  aria-invalid={invalid === 'contact' || undefined}
                  aria-describedby={invalid === 'contact' ? 'contact-help auth-error' : 'contact-help'}
                  onChange={(event) => setContact(event.target.value)}
                  placeholder="name@gmail.com or 9876543210"
                />
              </label>

              <div className="contact-status-bar">
                <span className="pill neutral unverified-tag">
                  <Icon name="lock" size={13} /> Unverified demo identity
                </span>
                {contact && (isEmail || isMobile) && (
                  <span className="pill mint format-tag">
                    {isEmail ? 'Valid email format' : 'Valid mobile format'}
                  </span>
                )}
              </div>
              <p className="field-help" id="contact-help">
                Accepts standard email addresses (@gmail.com, @outlook.com, etc.) or 10-digit Indian mobile numbers. Real emails or SMS OTPs will not be sent.
              </p>
            </fieldset>

            {/* STAGE 2: ONBOARDING PREFERENCES & PROTECTION */}
            {signup && stage === 2 && (
              <fieldset disabled={busy}>
                <h3 tabIndex={-1} ref={stepHeading}>Set your preferences</h3>

                {!guardian && (
                  <label>
                    Account type
                    <select
                      value={category}
                      onChange={(event) => setCategory(event.target.value as AccountCategory)}
                    >
                      {Object.entries(accountCategories).map(([key, value]) => (
                        <option key={key} value={key}>{value}</option>
                      ))}
                    </select>
                  </label>
                )}

                {!guardian && category !== 'personal' && (
                  <label>
                    Organization (optional)
                    <input
                      value={organization}
                      onChange={(event) => setOrganization(event.target.value)}
                      maxLength={80}
                      autoComplete="off"
                      placeholder="e.g. Acme Innovations Studio"
                    />
                  </label>
                )}

                <div className="account-fields">
                  <label>
                    Preferred language
                    <select value={language} onChange={(event) => setLanguage(event.target.value as Locale)}>
                      {Object.entries(languages).map(([code, value]) => (
                        <option key={code} value={code} lang={code}>{value.label}</option>
                      ))}
                    </select>
                  </label>

                  {!guardian && (
                    <label>
                      Review duration
                      <select
                        value={chosenDuration}
                        onChange={(event) => setChosenDuration(Number(event.target.value) as ReviewDuration)}
                      >
                        {reviewDurations.map((seconds) => (
                          <option key={seconds} value={seconds}>{seconds} seconds</option>
                        ))}
                      </select>
                    </label>
                  )}
                </div>

                {!guardian && (
                  <label>
                    Payment alert threshold (INR, optional)
                    <input
                      inputMode="decimal"
                      value={thresholdInput}
                      onChange={(event) => setThresholdInput(event.target.value)}
                      placeholder="e.g. 50000"
                    />
                  </label>
                )}

                <div className="onboarding-checkboxes">
                  <label className="check-row">
                    <input
                      type="checkbox"
                      checked={largeText}
                      onChange={(event) => setLargeText(event.target.checked)}
                    />
                    Use larger text for enhanced accessibility
                  </label>

                  <label className="check-row">
                    <input
                      type="checkbox"
                      checked={consentAcknowledged}
                      onChange={(event) => setConsentAcknowledged(event.target.checked)}
                    />
                    I understand PauseGuard interventions are advisory and require explicit guardian consent.
                  </label>
                </div>
              </fieldset>
            )}

            <div className="actions">
              {signup && stage === 2 && (
                <button className="secondary" type="button" disabled={busy} onClick={() => setStage(1)}>
                  Back
                </button>
              )}
              <button className="primary" type="submit" disabled={busy}>
                {busy ? 'Please wait…' : signup ? stage === 1 ? 'Continue' : 'Create account' : 'Sign in to demo'}
              </button>
            </div>
          </form>
        ) : (
          <div className="actions auth-landing-actions">
            <a className="primary" href={authLink('signup')}>Sign up</a>
            <a className="secondary" href={authLink('login')}>Sign in</a>
          </div>
        )}

        {form && (
          <div className="auth-mode-switch">
            <a className="text-button" href={authLink(signup ? 'login' : 'signup')}>
              {signup ? 'Already registered? Sign in' : 'Create a demo account'}
            </a>
          </div>
        )}

        {/* Password & Production IAM Preview (shows how future IAM integrates) */}
        {form && (
          <details className="verify-note iam-preview-note">
            <summary>Password interface preview</summary>
            <div className="iam-preview-content">
              <p className="field-help">
                Future production deployment connects to team IAM. A fixed password preview confirms input accessibility and control styling.
              </p>
              <label>
                Example password
                <input
                  readOnly
                  type={visible ? 'text' : 'password'}
                  value="PauseGuard-Demo!24"
                  autoComplete="off"
                  aria-describedby="password-preview-hint"
                />
              </label>
              <p id="password-preview-hint" className="field-help">
                Preview policy requires a minimum of 12 mixed-case alphanumeric characters.
              </p>
              <button
                className="secondary"
                type="button"
                aria-pressed={visible}
                onClick={() => setVisible(!visible)}
              >
                {visible ? 'Hide example password' : 'Show example password'}
              </button>
            </div>
          </details>
        )}
      </section>
    </div>
  )
}
