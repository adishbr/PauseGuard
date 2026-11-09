import { useState } from 'react'
import { isReference, payerKey, storageRead } from '../services/demoSession.ts'

export function Help({ payerId }: { payerId?: string }) {
  const reference = payerId ? storageRead('sessionStorage', `${payerKey}:${payerId}`) : ''
  const [copied, setCopied] = useState('')
  return (
    <section className="card account-card">
      <p className="eyebrow">PauseGuard help</p>
      <h2>Help and fraud reporting</h2>
      <p>For a suspicious request, stop the payment and verify independently through a trusted contact method. For an actual transfer, contact your bank through its official channel.</p>
      <div className="actions">
        <a className="secondary" href="tel:1930">Call cybercrime helpline 1930</a>
        <a className="secondary" href="https://cybercrime.gov.in/" target="_blank" rel="noreferrer">Open the National Cybercrime Reporting Portal</a>
      </div>
      {payerId && <section id="recovery-assist" className="safety-setting">
        <h3>Recovery Assist</h3>
        <p className="field-help">Use your simulated request reference when discussing the demo. Keep actual account information in official channels. Reports are submitted directly through the official portal.</p>
        {isReference(reference) ? <>
          <p className="reference"><code>{reference}</code></p>
          <button className="secondary" type="button" onClick={() => {
            void (async () => {
              try { await navigator.clipboard.writeText(reference); setCopied('Reference copied.') }
              catch { setCopied('Select and copy the displayed reference.') }
            })()
          }}>Copy demo reference</button>
          <p role="status">{copied}</p>
        </> : <p className="field-help">Open a simulated payment in this tab to make its reference available here.</p>}
      </section>}
    </section>
  )
}
