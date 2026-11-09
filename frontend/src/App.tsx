import { Icon } from './components/Icon.tsx'
import { Guardian } from './pages/Guardian.tsx'
import { Payer } from './pages/Payer.tsx'
import './App.css'

function App() {
  const guardian = window.location.pathname.replace(/\/$/, '') === '/guardian'

  return (
    <>
      <a className="skip-link" href="#main">Skip to payment workspace</a>
      <header className="site-header">
        <div className="frame topbar">
          <a href="/" className="brand" aria-label="PauseGuard payer home">
            <span className="brand-mark"><Icon name="shield" /></span>
            <span>Pause<span>Guard</span></span>
          </a>
          <span className="demo-badge"><span /> Simulation mode</span>
        </div>
      </header>

      <main id="main" className="frame" tabIndex={-1}>
        <div className="intro">
          <div className="intro-copy">
            <p className="eyebrow"><span className="line" /> {guardian ? 'Trusted reviewer' : 'Payment safety workspace'}</p>
            <h1>{guardian ? <>Guardian <em>review.</em></> : <>Pause before <em>you pay.</em></>}</h1>
            <p>{guardian ?
              'Help a trusted payer make an informed decision while their payment is on hold.' :
              'Check a payment for warning signs before you decide whether to send it.'}</p>
          </div>
        </div>

        <div className="workspace">
          <div className="main-column">{guardian ? <Guardian /> : <Payer />}</div>
          <aside className="side-column" aria-label="About this simulation">
            <section className="card side-card">
              <div className="symbol mint"><Icon name="users" /></div>
              <h2>Two-window demo</h2>
              <p>{guardian ? 'You’re in the guardian workspace. Keep it open while you start a review from the payer window.' :
                'Open the guardian workspace alongside this one. Choose Coerced KYC transfer to see an independent review.'}</p>
              <a className="secondary" href={guardian ? '/' : '/guardian'} target="_blank" rel="noopener">
                Open {guardian ? 'payer' : 'guardian'} window <Icon name="external" size={18} />
              </a>
            </section>
            <section className="card side-card privacy-card">
              <div className="symbol"><Icon name="lock" /></div>
              <h2>Private by default</h2>
              <p>The two synthetic accounts are pre-enrolled for this demo. The guardian sees a safety request with a reference and deadline. Payment details stay in the payer workspace.</p>
            </section>
          </aside>
        </div>
      </main>

      <footer className="frame site-footer">
        <span><Icon name="shield" size={16} /> PauseGuard V2</span>
        <span>Local simulation · Synthetic data · No money moves</span>
      </footer>
    </>
  )
}

export default App
