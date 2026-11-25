import { useEffect, useState } from "react";
import { useLocation, useRouter } from "@tanstack/react-router";
import { BrandMark } from "../components/pauseguard/brand-mark.tsx";
import { defaultReviewDuration, parseReviewDuration } from "../../mocks/reviewPreference.ts";
import type { ReviewDuration } from "../../mocks/reviewPreference.ts";
import { ProtectionSettings } from "../components/ProtectionSettings.tsx";
import { Icon } from "../components/Icon.tsx";
import { ThemeToggle } from "../components/ThemeToggle.tsx";
import { isLocale, languages, translator } from "../locales/messages.ts";
import type { Locale } from "../locales/messages.ts";
import { Account } from "./Account.tsx";
import { Admin, AdminLogin } from "./Admin.tsx";
import { Auth } from "./Auth.tsx";
import { Enrollment } from "./Enrollment.tsx";
import { Help } from "./Help.tsx";
import {
  accountApi,
  AccountError,
  savedSession,
  saveSession,
  sessionExpired,
} from "../services/accountApi.ts";
import { isRealBackendMode } from "../services/backendMode.ts";
import type { DemoProfile, DemoSession } from "../types/account.ts";
import { Guardian } from "./Guardian.tsx";
import { Payer } from "./Payer.tsx";
import { storageRead, storageWrite } from "../services/demoSession.ts";
import "../styles/pauseguard/base.css";
import "../styles/pauseguard/app.css";

const languageKey = "pauseguard:demo:language";
const protectionKey = "pauseguard:demo:review-seconds";

function dashboardDestination(dashboard: string) {
  return dashboard === "/guardian" &&
    new URLSearchParams(window.location.search).get("next") === "/guardian/enrollment"
    ? "/guardian/enrollment"
    : dashboard;
}

function normalize(pathname: string) {
  return pathname.replace(/\/$/, "") || "/";
}

export function Workspace() {
  const router = useRouter();
  const path = normalize(useLocation({ select: (location) => location.pathname }));
  const setPath = (target: string) => router.history.replace(target);
  const guardian = path === "/guardian" || path.startsWith("/guardian/");
  const adminPath = path === "/admin" || path.startsWith("/admin/");
  const role = guardian ? "guardian" : adminPath ? "admin" : "payer";
  const base = guardian ? "/guardian" : adminPath ? "/admin" : "/payer";
  const dashboard = base;
  const shell = path === "/analyst";
  const [token, setToken] = useState(() => (shell ? "" : savedSession(role)));
  const [session, setSession] = useState<DemoSession>();
  const [expired, setExpired] = useState(false);
  const [sessionError, setSessionError] = useState("");
  const [retry, setRetry] = useState(0);
  const [signingOut, setSigningOut] = useState(false);
  const [locale, setLocale] = useState<Locale>(() => {
    const saved = storageRead("localStorage", languageKey);
    return isLocale(saved) ? saved : "en";
  });
  const [savedDuration, setSavedDuration] = useState<{ key: string; value: ReviewDuration }>();
  const t = translator(locale);
  const profile = session?.profile;
  const durationKey = `${protectionKey}:${profile?.id}`;
  const realBackend = isRealBackendMode();
  const reviewDuration = realBackend
    ? defaultReviewDuration
    : savedDuration?.key === durationKey
      ? savedDuration.value
      : (parseReviewDuration(
          storageRead("localStorage", durationKey) ||
            (profile?.sample ? storageRead("localStorage", protectionKey) : ""),
        ) ?? defaultReviewDuration);

  const paymentPage = path === dashboard;
  const isProfilePage = path.endsWith("/profile");
  const isEnrollmentPage = path.endsWith("/enrollment");
  const isHelpPage = path.endsWith("/help");
  const showProtection = !realBackend && !guardian && !adminPath && (paymentPage || isProfilePage);

  function changeLocale(next: Locale) {
    storageWrite("localStorage", languageKey, next);
    setLocale(next);
  }

  function saveReviewDuration(duration: ReviewDuration) {
    if (!storageWrite("localStorage", durationKey, String(duration))) return false;
    setSavedDuration({ key: durationKey, value: duration });
    return true;
  }

  function enter(next: DemoSession) {
    if (next.profile.role !== role) return;
    saveSession(role, next.token);
    setSession(next);
    setToken(next.token);
    setExpired(false);
    setSessionError("");
    if (!next.profile.sample) changeLocale(next.profile.language);
    const target =
      path.endsWith("/login") || path.endsWith("/signup") ? dashboardDestination(dashboard) : path;
    setPath(target);
  }

  function saveProfile(next: DemoProfile) {
    setSession((previous) => previous && { ...previous, profile: next });
    changeLocale(next.language);
  }

  async function logout() {
    if (!token || signingOut) return;
    setSigningOut(true);
    try {
      await accountApi.logout(token);
      saveSession(role, "");
      setToken("");
      setSession(undefined);
      setSessionError("");
      setExpired(false);
      setPath(base + "/login");
    } catch (error) {
      if (!(error instanceof AccountError && error.status === 401)) {
        setSessionError("Sign-out could not reach the demo service. Try again.");
      }
    } finally {
      setSigningOut(false);
    }
  }

  useEffect(() => {
    if (!token) return;
    let active = true;

    function expire() {
      if (!active) return;
      saveSession(role, "");
      setToken("");
      setSession(undefined);
      setExpired(true);
      setSessionError("");
    }

    function onExpiry(event: Event) {
      if ((event as CustomEvent<string>).detail === token) expire();
    }

    let timer: ReturnType<typeof setTimeout>;
    window.addEventListener(sessionExpired, onExpiry);
    void accountApi.session(token).then(
      (next) => {
        if (!active) return;
        if (next.profile.role !== role) {
          expire();
          return;
        }
        setSession(next);
        setSessionError("");
        if (
          window.location.pathname.endsWith("/login") ||
          window.location.pathname.endsWith("/signup")
        ) {
          router.history.replace(dashboardDestination(dashboard));
        }
        timer = setTimeout(expire, Math.max(0, next.expiresAt - Date.now()));
      },
      (error: unknown) => {
        if (!active) return;
        if (error instanceof AccountError && error.status === 401) expire();
        else setSessionError("Could not check your demo session. Retry when connected.");
      },
    );

    return () => {
      active = false;
      clearTimeout(timer);
      window.removeEventListener(sessionExpired, onExpiry);
    };
  }, [token, role, retry, dashboard, router]);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const authRole = guardian ? "guardian" : "payer";
  const isAuth = !shell && !adminPath && !session && !token;
  const layoutKind = isProfilePage
    ? "is-profile"
    : isEnrollmentPage
      ? "is-enrollment"
      : isHelpPage
        ? "is-help"
        : guardian
          ? "is-guardian"
          : "is-payer";

  return (
    <div className={`app${profile?.largeText ? " large-text" : ""}${isAuth ? " auth-page" : ""}`}>
      <a className="skip-link" href="#main">
        {t("skip")}
      </a>

      <header className="site-header">
        <div className="frame topbar">
          <div className="topbar-brand-group">
            <a
              href={profile ? dashboard : "/"}
              className="brand"
              aria-label={
                guardian
                  ? "PauseGuard guardian home"
                  : adminPath
                    ? "PauseGuard admin home"
                    : t("payerHome")
              }
            >
              <BrandMark className="pg-brand-svg" />
              <span className="brand-wordmark">PauseGuard</span>
            </a>

            <span className="workspace-role-pill">
              <span className="pulse-dot" aria-hidden="true" />
              {shell
                ? "Analyst shell"
                : adminPath
                  ? "Merchant sandbox"
                  : guardian
                    ? "Guardian portal"
                    : "Preview"}
            </span>
          </div>

          {profile && (
            <nav className="account-nav account-nav-inline" aria-label="Account navigation">
              <div className="nav-primary-links">
                <a href={dashboard} aria-current={paymentPage ? "page" : undefined}>
                  <Icon
                    name={adminPath ? "shieldAlert" : guardian ? "users" : "activity"}
                    size={15}
                  />
                  <span>{adminPath ? "Testing" : guardian ? "Reviews" : "Dashboard"}</span>
                </a>
                {!adminPath && (
                  <>
                    <a href={`${base}/profile`} aria-current={isProfilePage ? "page" : undefined}>
                      <Icon name="sliders" size={15} />
                      <span>Profile</span>
                    </a>
                    <a
                      href={`${base}/enrollment`}
                      aria-current={isEnrollmentPage ? "page" : undefined}
                    >
                      <Icon name="users" size={15} />
                      <span>{guardian ? "Invitations" : "Guardians"}</span>
                    </a>
                    <a href={`${base}/help`} aria-current={isHelpPage ? "page" : undefined}>
                      <Icon name="fileText" size={15} />
                      <span>Help &amp; recovery</span>
                    </a>
                  </>
                )}
              </div>
              <div className="nav-utility-group">
                <button
                  className="text-button signout-btn"
                  disabled={signingOut}
                  type="button"
                  onClick={() => void logout()}
                >
                  {signingOut ? "Signing out…" : "Sign out"}
                </button>
              </div>
            </nav>
          )}

          <div className="topbar-controls">
            {!guardian && !adminPath && profile?.safeLock && (
              <a
                href="/payer/profile"
                className="safelock-indicator active"
                title="Safe-Lock is Active (Outgoing transfers blocked)"
              >
                <Icon name="lock" size={13} />
                <span>Safe-Lock ON</span>
              </a>
            )}

            <ThemeToggle compact />

            {!adminPath && (
              <label className="locale-control">
                <span className="sr-only">{t("language")}</span>
                <select
                  value={locale}
                  onChange={(event) => {
                    const next = event.target.value;
                    if (!isLocale(next)) return;
                    changeLocale(next);
                  }}
                >
                  {Object.entries(languages).map(([code, language]) => (
                    <option key={code} value={code} lang={code}>
                      {language.label}
                    </option>
                  ))}
                </select>
              </label>
            )}

            {!profile && (
              <a className="topbar-home-link" href="/">
                Home
              </a>
            )}
          </div>
        </div>
      </header>

      <main id="main" className="frame main-stage" tabIndex={-1}>
        {sessionError && (
          <div className="notice session-notice" role="alert">
            <p>{sessionError}</p>
            {!session && (
              <button
                className="secondary"
                type="button"
                onClick={() => {
                  setSessionError("");
                  setRetry((n) => n + 1);
                }}
              >
                Retry session
              </button>
            )}
          </div>
        )}

        {shell ? (
          <section className="analyst-stage">
            <div className="card workspace-card analyst-card">
              <div className="analyst-badge-row">
                <span className="eyebrow">Integration shell</span>
                <span className="pill neutral">Authorized Backend Required</span>
              </div>
              <h1>
                Analyst <em>review console.</em>
              </h1>
              <p className="form-note">
                Access and data will come from the team’s authorized backend. The local demo
                supports payer, guardian, and admin sandbox sessions.
              </p>
              <div className="analyst-capabilities">
                <div>
                  <span className="step-num">01</span>
                  <strong>False-alert appeals</strong>
                  <p>
                    Independent analyst review of appealed rejections before policy-checked retry.
                  </p>
                </div>
                <div>
                  <span className="step-num">02</span>
                  <strong>Redacted audit trail</strong>
                  <p>
                    Cryptographically chained transition history without exposing live bank
                    credentials.
                  </p>
                </div>
              </div>
              <div className="actions">
                <a className="primary" href="/">
                  Return to PauseGuard
                </a>
                <a className="secondary" href="/payer/login">
                  Open payer workspace
                </a>
              </div>
            </div>
          </section>
        ) : adminPath ? (
          !session ? (
            token ? (
              !sessionError && (
                <div className="session-loading-state" role="status">
                  <span className="spinner" aria-hidden="true" />
                  <span>Checking your admin session…</span>
                </div>
              )
            ) : (
              <AdminLogin
                onSession={enter}
                expired={expired}
                registrationBlocked={path === "/admin/signup"}
              />
            )
          ) : (
            <Admin key={session.profile.id} token={token} accountId={session.profile.id} />
          )
        ) : !session ? (
          token ? (
            !sessionError && (
              <div className="session-loading-state" role="status">
                <span className="spinner" aria-hidden="true" />
                <span>Checking your demo session…</span>
              </div>
            )
          ) : (
            <Auth
              key={path}
              path={path}
              role={authRole}
              locale={locale}
              onSession={enter}
              expired={expired}
            />
          )
        ) : (
          <>
            {paymentPage && (
              <div className="workspace-masthead">
                <div className="masthead-copy">
                  <p className="eyebrow">
                    <span className="line" />
                    {t(guardian ? "guardianEyebrow" : "payerEyebrow")}
                  </p>
                  <h1>
                    {t(guardian ? "guardianHero" : "payerHero")}{" "}
                    <em className="text-accent-italic">
                      {t(guardian ? "guardianAccent" : "payerAccent")}
                    </em>
                  </h1>
                  <p className="masthead-lead">{t(guardian ? "guardianIntro" : "payerIntro")}</p>
                </div>
                <div className="masthead-identity">
                  <div className="persona-card">
                    <span className="persona-avatar">
                      {session.profile.name.charAt(0).toUpperCase()}
                    </span>
                    <div className="persona-details">
                      <span className="persona-signed">Signed in as {session.profile.name}</span>
                      <span className="persona-meta">
                        {guardian ? "Trusted Guardian" : session.profile.category.replace("_", " ")}{" "}
                        · {session.profile.sample ? "Sample preview" : "Preview account"}
                      </span>
                    </div>
                  </div>
                  {showProtection && (
                    <a className="mobile-settings-link" href="#payment-protection-settings">
                      {t("protectionSettings")} <Icon name="arrow" size={15} />
                    </a>
                  )}
                </div>
              </div>
            )}

            {!paymentPage && (
              <div className="subpage-context-strip">
                <span className="persona-signed-pill">
                  <span className="persona-dot" aria-hidden="true" />
                  Signed in as {session.profile.name} · {guardian ? "Guardian" : "Payer"}
                </span>
                {showProtection && (
                  <a className="mobile-settings-link" href="#payment-protection-settings">
                    {t("protectionSettings")} <Icon name="arrow" size={15} />
                  </a>
                )}
              </div>
            )}

            <div
              className={`workspace ${layoutKind}${paymentPage ? " is-dashboard" : " account-workspace"}`}
            >
              <div className="main-column">
                {isProfilePage ? (
                  <Account
                    key={session.profile.id}
                    token={token}
                    profile={session.profile}
                    saved={saveProfile}
                  />
                ) : isEnrollmentPage ? (
                  <Enrollment key={session.profile.id} token={token} profile={session.profile} />
                ) : isHelpPage ? (
                  <Help payerId={guardian ? undefined : session.profile.id} />
                ) : guardian ? (
                  <Guardian
                    key={session.profile.id}
                    token={token}
                    accountId={session.profile.id}
                    locale={locale}
                  />
                ) : (
                  <Payer
                    key={session.profile.id}
                    token={token}
                    accountId={session.profile.id}
                    locale={locale}
                    reviewDuration={reviewDuration}
                  />
                )}
              </div>

              {(showProtection || paymentPage) && (
                <aside className="side-column" aria-label={t("about")}>
                  {showProtection && (
                    <ProtectionSettings
                      key={session.profile.id}
                      saved={reviewDuration}
                      save={saveReviewDuration}
                      t={t}
                    />
                  )}

                  {paymentPage && (
                    <section className="card side-card privacy-note-card">
                      <div className="side-card-head">
                        <span className="symbol subtle">
                          <Icon name="lock" size={17} />
                        </span>
                        <h2>{t("privacy")}</h2>
                      </div>
                      <p>
                        {session.profile.sample
                          ? t("privacyNote")
                          : "Guardian enrollment requires explicit acceptance. Payment details stay with the payer."}
                      </p>
                      <div className="privacy-pills" aria-label="Redacted fields">
                        <span>Recipient private</span>
                        <span>Amount private</span>
                        <span>Hold on timeout</span>
                      </div>
                    </section>
                  )}
                </aside>
              )}
            </div>
          </>
        )}
      </main>

      <footer className="frame site-footer">
        <div className="footer-left">
          <BrandMark className="footer-mark" />
          <span>PauseGuard V2</span>
          <span className="footer-divider">·</span>
          <a href="/">Public homepage</a>
          <span className="footer-divider">·</span>
          <a href={guardian ? "/payer/login" : "/guardian/login"}>
            {guardian ? "Payer workspace" : "Guardian portal"}
          </a>
        </div>
        <span className="footer-note">{t("footer")}</span>
      </footer>
    </div>
  );
}
