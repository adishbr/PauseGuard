import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Icon } from '../components/Icon.tsx'
import { languages } from '../locales/messages.ts'
import type { Locale } from '../locales/messages.ts'
import { accountApi } from '../services/accountApi.ts'
import { accountCategories, demoContact, demoName } from '../types/account.ts'
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
  const [visible, setVisible] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [invalid, setInvalid] = useState<'name' | 'contact'>()
  const sending = useRef(false)
  const nameInput = useRef<HTMLInputElement>(null)
  const contactInput = useRef<HTMLInputElement>(null)
  const stepHeading = useRef<HTMLHeadingElement>(null)

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
        setError('Use a fictional .test email or a 10-digit demo mobile beginning with 00000.')
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
      onSession(signup && !sample ? await accountApi.register(role, { name, contact, language, category, organization }) :
        await accountApi.login(role, contact, sample))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The demo could not sign you in.')
    } finally {
      sending.current = false
      setBusy(false)
    }
  }

  return (
    <div className="account-layout">
      <section className="account-intro">
        <span className="symbol mint"><Icon name="shield" size={24} /></span>
        <p className="eyebrow">PauseGuard demo</p>
        <h1>{guardian ? 'Trusted guardian access' : 'Pause before you pay.'}</h1>
        <p>{guardian ? 'Review only the payment alerts you are assigned. You choose whether to accept each enrollment.' :
          'Set protection preferences, invite a trusted guardian, and try a simulated transfer.'}</p>
        <a className="text-button" href={guardian ? '/' : '/guardian'}>{guardian ? 'Switch to payer' : 'Switch to guardian'} <Icon name="arrow" size={17} /></a>
      </section>
      <section className="card account-card" aria-labelledby="auth-heading">
        <p className="eyebrow">{guardian ? 'Guardian' : 'Payer'} · Demo identity</p>
        <h2 id="auth-heading">{signup ? 'Create a demo account' : form ? 'Sign in' : 'Welcome to PauseGuard'}</h2>
        <p className="form-note">Use fictional details in this simulation. Sign-in uses a demo identity without a password or OTP.</p>
        {expired && <p role="alert" className="notice">Your demo session expired. Sign in again to continue.</p>}
        {error && <p id="auth-error" role="alert" className="notice">{error}</p>}
        {form ? <form className="account-form" noValidate onSubmit={(event) => void submit(event)}>
          {signup && <p className="account-step">Step {stage} of 2 · {stage === 1 ? 'Demo identity' : 'Preferences'}</p>}
          <fieldset hidden={signup && stage === 2} disabled={busy}>
            {signup && <label>Full name<input ref={nameInput} value={name} maxLength={64} required autoComplete="off"
              aria-invalid={invalid === 'name' || undefined} aria-describedby={invalid === 'name' ? 'auth-error' : undefined}
              onChange={(event) => setName(event.target.value)} placeholder="Asha Demo" /></label>}
            <label>Email or mobile<input ref={contactInput} value={contact} maxLength={90} required autoComplete="off" spellCheck={false}
              aria-invalid={invalid === 'contact' || undefined}
              aria-describedby={invalid === 'contact' ? 'contact-help auth-error' : 'contact-help'}
              onChange={(event) => setContact(event.target.value)} placeholder="asha@pauseguard.test" /></label>
            <p className="field-help" id="contact-help">Use a .test email or a demo mobile such as 0000012345.</p>
          </fieldset>
          {signup && stage === 2 && <fieldset disabled={busy}>
            <h3 tabIndex={-1} ref={stepHeading}>Set your preferences</h3>
            {!guardian && <label>Account type
              <select value={category} onChange={(event) => setCategory(event.target.value as AccountCategory)}>
                {Object.entries(accountCategories).map(([key, value]) => <option key={key} value={key}>{value}</option>)}
              </select>
            </label>}
            {!guardian && category !== 'personal' && <label>Organization (optional)
              <input value={organization} onChange={(event) => setOrganization(event.target.value)} maxLength={80} autoComplete="off" />
            </label>}
            <label>Preferred language
              <select value={language} onChange={(event) => setLanguage(event.target.value as Locale)}>
                {Object.entries(languages).map(([code, value]) => <option key={code} value={code} lang={code}>{value.label}</option>)}
              </select>
            </label>
          </fieldset>}
          <div className="actions">
            {signup && stage === 2 && <button className="secondary" type="button" disabled={busy} onClick={() => setStage(1)}>Back</button>}
            <button className="primary" type="submit" disabled={busy}>{busy ? 'Please wait…' : signup ? stage === 1 ? 'Continue' : 'Create account' : 'Sign in to demo'}</button>
          </div>
        </form> : <div className="actions">
          <a className="primary" href={authLink('signup')}>Sign up</a>
          <a className="secondary" href={authLink('login')}>Sign in</a>
        </div>}
        {form && <a className="text-button" href={authLink(signup ? 'login' : 'signup')}>{signup ? 'Already registered? Sign in' : 'Create a demo account'}</a>}
        <div className="sample-access">
          <button className="secondary" type="button" disabled={busy} onClick={() => void submit(undefined, true)}>
            {guardian ? 'Open sample guardian' : 'Open sample payer'}
          </button>
          <p className="field-help">The sample payer and guardian are already paired for the payment walkthrough.</p>
        </div>
        {form && <details className="verify-note">
          <summary>Password interface preview</summary>
          <p className="field-help">A fixed example shows the visibility control and validation copy for future integration.</p>
          <label>Example password<input readOnly type={visible ? 'text' : 'password'} value="PauseGuard-Demo!24"
            autoComplete="off" aria-describedby="password-preview-hint" /></label>
          <p id="password-preview-hint" className="field-help">Example meets the preview minimum of 12 characters.</p>
          <button className="secondary" type="button" aria-pressed={visible} onClick={() => setVisible(!visible)}>
            {visible ? 'Hide example password' : 'Show example password'}
          </button>
        </details>}
      </section>
    </div>
  )
}
