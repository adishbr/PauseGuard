import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { beneficiaries, purposes, scenarios } from '../../mocks/scenarios.ts'
import { Icon } from '../components/Icon.tsx'
import { PaymentStatus } from '../components/PaymentStatus.tsx'
import { ApiError, createPayment } from '../services/paymentApi.ts'
import { decimalRupees, isReference, payerKey, reviewKey, saveDraft, savedDraft, storageRead, storageWrite, toPaise } from '../services/demoSession.ts'
import type { CreatePayment } from '../types/payment.ts'

const defaultScenario = scenarios[2]

function restoredDraft(): CreatePayment | undefined {
  const draft = savedDraft()
  if (!draft) return undefined
  try {
    const parsed = JSON.parse(draft) as CreatePayment
    if (parsed && typeof parsed.idempotency_key === 'string' && Number.isSafeInteger(parsed.amount_paise) &&
      Object.hasOwn(beneficiaries, parsed.beneficiary_id) && Object.hasOwn(purposes, parsed.purpose)) return parsed
  } catch {
    // Invalid local demo drafts can be ignored.
  }
}

function PaymentForm({ onCreated }: { onCreated: (id: string) => void }) {
  const [pending, setPending] = useState(restoredDraft)
  const [beneficiary, setBeneficiary] = useState<string>(pending?.beneficiary_id ?? defaultScenario.beneficiary)
  const [amount, setAmount] = useState(pending ? decimalRupees(pending.amount_paise) : defaultScenario.amount)
  const [purpose, setPurpose] = useState<string>(pending?.purpose ?? defaultScenario.purpose)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const sending = useRef(false)
  const amountInput = useRef<HTMLInputElement>(null)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (sending.current) return
    const paise = toPaise(amount)
    if (paise === null) {
      setError('Enter a positive rupee amount with up to two decimal places.')
      amountInput.current?.focus()
      return
    }

    const input = pending ?? {
      amount_paise: paise,
      beneficiary_id: beneficiary,
      purpose,
      idempotency_key: crypto.randomUUID(),
    }
    sending.current = true
    setBusy(true)
    setError('')
    setPending(input)
    saveDraft(JSON.stringify(input))
    try {
      const { payment } = await createPayment(input)
      if (payment.guardian_deadline && payment.status === 'AWAITING_GUARDIAN') {
        storageWrite('localStorage', reviewKey, payment.id)
      }
      onCreated(payment.id)
      saveDraft('')
    } catch (failure) {
      if (failure instanceof ApiError && [400, 422].includes(failure.status)) {
        setPending(undefined)
        saveDraft('')
      }
      setError(failure instanceof Error ? failure.message : 'Unable to start this demo payment.')
    } finally {
      sending.current = false
      setBusy(false)
    }
  }

  return (
    <>
      <section className="card" aria-labelledby="payment-heading">
        <div className="card-header">
          <div className="symbol mint"><Icon name="activity" /></div>
          <div>
            <p className="eyebrow">Payer workspace</p>
            <h2 id="payment-heading">Prepare a payment</h2>
          </div>
        </div>
        <form onSubmit={(event) => void submit(event)}>
          <fieldset disabled={Boolean(pending)} className="form-fields">
            <label className="full">Amount (INR)
              <span className="amount-field"><span aria-hidden="true">₹</span>
                <input ref={amountInput} name="amount" inputMode="decimal" value={amount}
                  onChange={(event) => setAmount(event.target.value)} required />
              </span>
            </label>
            <label>Demo recipient
              <select name="beneficiary" value={beneficiary} onChange={(event) => setBeneficiary(event.target.value)}>
                {Object.entries(beneficiaries).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label>Payment purpose
              <select name="purpose" value={purpose} onChange={(event) => setPurpose(event.target.value)}>
                {Object.entries(purposes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
          </fieldset>
          {error && <p className="notice" role="alert">{error}</p>}
          {pending && !busy && <p className="form-note">Retry to check the original request. The demo will reuse its payment reference.</p>}
          <div className="actions">
            <button type="submit" className="primary" disabled={busy}>
              {busy ? 'Checking payment…' : pending ? 'Retry this request' : 'Check payment'}
              <Icon name="arrow" size={18} />
            </button>
          </div>
        </form>
      </section>

      <section className="scenarios" aria-labelledby="scenarios-heading">
        <h2 id="scenarios-heading">Try a demo scenario</h2>
        <div className="scenario-list">
          {scenarios.map((scenario) => {
            const selected = beneficiary === scenario.beneficiary && amount === scenario.amount && purpose === scenario.purpose
            return (
              <button className="scenario" type="button" key={scenario.title} aria-pressed={selected}
                disabled={Boolean(pending)} onClick={() => {
                  setBeneficiary(scenario.beneficiary)
                  setAmount(scenario.amount)
                  setPurpose(scenario.purpose)
                  setError('')
                }}>
                <span>{scenario.tag}</span><strong>{scenario.title}</strong>
              </button>
            )
          })}
        </div>
      </section>
    </>
  )
}

export function Payer() {
  const [id, setId] = useState(() => {
    const previous = storageRead('sessionStorage', payerKey)
    return isReference(previous) ? previous : ''
  })

  function selectPayment(next: string) {
    storageWrite('sessionStorage', payerKey, next)
    setId(next)
  }

  return id ? <PaymentStatus key={id} role="payer" id={id} onClose={() => selectPayment('')} /> :
    <PaymentForm onCreated={selectPayment} />
}
