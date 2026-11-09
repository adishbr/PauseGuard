import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Icon } from '../components/Icon.tsx'
import { PaymentStatus } from '../components/PaymentStatus.tsx'
import { translator } from '../locales/messages.ts'
import type { Locale } from '../locales/messages.ts'
import { isReference, reviewKey, storageRead, storageWrite } from '../services/demoSession.ts'

const guardianKey = 'pauseguard:demo:guardian-payment'

export function Guardian({ locale }: { locale: Locale }) {
  const t = translator(locale)
  const [latest, setLatest] = useState(() => storageRead('localStorage', reviewKey))
  const [id, setId] = useState(() => {
    const previous = storageRead('sessionStorage', guardianKey)
    return isReference(previous) ? previous : ''
  })
  const [reference, setReference] = useState('')
  const [invalidReference, setInvalidReference] = useState(false)
  const [returning, setReturning] = useState(false)
  const referenceInput = useRef<HTMLInputElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    function readLatest() {
      setLatest(storageRead('localStorage', reviewKey))
    }
    function onStorage(event: StorageEvent) {
      if (event.key === reviewKey || event.key === null) readLatest()
    }
    window.addEventListener('storage', onStorage)
    window.addEventListener('focus', readLatest)
    return () => {
      window.removeEventListener('storage', onStorage)
      window.removeEventListener('focus', readLatest)
    }
  }, [])

  useEffect(() => {
    if (returning && !id) heading.current?.focus()
  }, [id, returning])

  function openRequest(next: string) {
    storageWrite('sessionStorage', guardianKey, next)
    setReturning(!next)
    setId(next)
    setInvalidReference(false)
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isReference(reference.trim())) {
      openRequest(reference.trim())
    } else {
      setInvalidReference(true)
      referenceInput.current?.focus()
    }
  }

  if (id) {
    return <PaymentStatus key={id} id={id} role="guardian" locale={locale} onClose={() => openRequest('')} />
  }

  const hasReview = isReference(latest)
  return (
    <section className="card workspace-card" aria-labelledby="guardian-heading">
      <div className="card-header">
        <div className="symbol mint"><Icon name="users" /></div>
        <div>
          <p className="eyebrow">{t('guardianInbox')}</p>
          <h2 id="guardian-heading" ref={heading} tabIndex={-1}>{t('safetyReviews')}</h2>
        </div>
      </div>
      <div className={hasReview ? 'inbox inbox-active' : 'inbox'}>
        <Icon name={hasReview ? 'activity' : 'shield'} />
        <div role="status">
          <strong>{t(hasReview ? 'reviewReceived' : 'waitingRequest')}</strong>
          <p>{t(hasReview ? 'latestRequest' : 'sameBrowser')}</p>
        </div>
        {hasReview && <button type="button" className="primary" onClick={() => openRequest(latest)}>{t('openReview')} <Icon name="arrow" size={18} /></button>}
      </div>
      <form className="reference-form" noValidate onSubmit={submit}>
        <label>{t('reference')}
          <input ref={referenceInput} placeholder="pg_…" value={reference}
            onChange={(event) => {
              setReference(event.target.value)
              setInvalidReference(false)
            }}
            aria-invalid={invalidReference || undefined} aria-describedby="reference-help"
            required autoComplete="off" autoCapitalize="none" spellCheck={false} maxLength={83} />
        </label>
        <button type="submit" className="secondary">{t('findRequest')}</button>
      </form>
      <p id="reference-help" className={invalidReference ? 'field-error' : 'form-note'} role={invalidReference ? 'alert' : undefined}>
        {t(invalidReference ? 'invalidReference' : 'separateProfile')}
      </p>
    </section>
  )
}
