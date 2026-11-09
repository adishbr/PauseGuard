import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Icon } from '../components/Icon.tsx'
import { PaymentStatus } from '../components/PaymentStatus.tsx'
import { isReference, reviewKey, storageRead, storageWrite } from '../services/demoSession.ts'

const guardianKey = 'pauseguard:demo:guardian-payment'

export function Guardian() {
  const [latest, setLatest] = useState(() => storageRead('localStorage', reviewKey))
  const [id, setId] = useState(() => {
    const previous = storageRead('sessionStorage', guardianKey)
    return isReference(previous) ? previous : ''
  })
  const [reference, setReference] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    function onStorage(event: StorageEvent) {
      if (event.key === reviewKey) setLatest(event.newValue ?? '')
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  function openRequest(next: string) {
    storageWrite('sessionStorage', guardianKey, next)
    setId(next)
    setError('')
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isReference(reference.trim())) openRequest(reference.trim())
    else setError('Enter the request reference starting with pg_.')
  }

  if (id) return <PaymentStatus key={id} id={id} role="guardian" onClose={() => openRequest('')} />

  return (
    <section className="card" aria-labelledby="guardian-heading">
      <div className="card-header">
        <div className="symbol mint"><Icon name="users" /></div>
        <div>
          <p className="eyebrow">Guardian inbox</p>
          <h2 id="guardian-heading">Safety reviews</h2>
        </div>
      </div>
      <div className="inbox" role="status">
        <Icon name={isReference(latest) ? 'activity' : 'shield'} />
        <div>
          <strong>{isReference(latest) ? 'Review received' : 'Waiting for a review request'}</strong>
          <p>{isReference(latest) ? 'Open the latest request to check its current status.' :
            'Requests from the payer window in this browser appear here.'}</p>
        </div>
        {isReference(latest) && <button type="button" className="primary" onClick={() => openRequest(latest)}>Open review <Icon name="arrow" size={18} /></button>}
      </div>
      <form className="reference-form" onSubmit={submit}>
        <label>Request reference
          <input placeholder="pg_…" value={reference} onChange={(event) => setReference(event.target.value)}
            required autoComplete="off" autoCapitalize="none" spellCheck={false} maxLength={83} />
        </label>
        <button type="submit" className="secondary">Find request</button>
      </form>
      {error && <p className="notice" role="alert">{error}</p>}
      <p className="form-note">Paste a reference from the payer window if you are using a separate browser profile.</p>
    </section>
  )
}
