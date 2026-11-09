import { useEffect, useState } from 'react'
import { Icon } from './components/Icon.tsx'
import { isLocale, languages, translator } from './locales/messages.ts'
import type { Locale } from './locales/messages.ts'
import { Guardian } from './pages/Guardian.tsx'
import { Payer } from './pages/Payer.tsx'
import { storageRead, storageWrite } from './services/demoSession.ts'
import './App.css'

const languageKey = 'pauseguard:demo:language'

function App() {
  const guardian = window.location.pathname.replace(/\/$/, '') === '/guardian'
  const [locale, setLocale] = useState<Locale>(() => {
    const saved = storageRead('localStorage', languageKey)
    return isLocale(saved) ? saved : 'en'
  })
  const t = translator(locale)

  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  return (
    <>
      <a className="skip-link" href="#main">{t('skip')}</a>
      <header className="site-header">
        <div className="frame topbar">
          <a href="/" className="brand" aria-label={t('payerHome')}>
            <span className="brand-mark"><Icon name="shield" /></span>
            <span>Pause<span>Guard</span></span>
          </a>
          <div className="topbar-controls">
            <span className="demo-badge"><span />{t('simulation')}</span>
            <label className="locale-control">
              <span className="sr-only">{t('language')}</span>
              <select value={locale} onChange={(event) => {
                const next = event.target.value
                if (!isLocale(next)) return
                storageWrite('localStorage', languageKey, next)
                setLocale(next)
              }}>
                {Object.entries(languages).map(([code, language]) => (
                  <option key={code} value={code} lang={code}>{language.label}</option>
                ))}
              </select>
            </label>
          </div>
        </div>
      </header>

      <main id="main" className="frame" tabIndex={-1}>
        <div className="intro">
          <div className="intro-copy">
            <p className="eyebrow"><span className="line" />{t(guardian ? 'guardianEyebrow' : 'payerEyebrow')}</p>
            <h1>{t(guardian ? 'guardianHero' : 'payerHero')} <em>{t(guardian ? 'guardianAccent' : 'payerAccent')}</em></h1>
            <p>{t(guardian ? 'guardianIntro' : 'payerIntro')}</p>
          </div>
          <div className="intro-mark" aria-hidden="true"><Icon name="shield" size={53} /></div>
        </div>

        <div className="workspace">
          <div className="main-column">{guardian ? <Guardian locale={locale} /> : <Payer locale={locale} />}</div>
          <aside className="side-column" aria-label={t('about')}>
            <section className="card side-card">
              <div className="symbol mint"><Icon name="users" /></div>
              <h2>{t('twoWindows')}</h2>
              <p>{t(guardian ? 'guardianGuide' : 'payerGuide')}</p>
              <a className="secondary" href={guardian ? '/' : '/guardian'} target="_blank" rel="noopener">
                {t(guardian ? 'openPayer' : 'openGuardian')} <Icon name="external" size={18} />
              </a>
            </section>
            <section className="card side-card privacy-card">
              <div className="symbol"><Icon name="lock" /></div>
              <h2>{t('privacy')}</h2>
              <p>{t('privacyNote')}</p>
            </section>
          </aside>
        </div>
      </main>

      <footer className="frame site-footer">
        <span><Icon name="shield" size={16} /> PauseGuard V2</span>
        <span>{t('footer')}</span>
      </footer>
    </>
  )
}

export default App
