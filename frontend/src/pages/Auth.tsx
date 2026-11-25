import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { Icon } from "../components/Icon.tsx";
import { languages } from "../locales/messages.ts";
import type { Locale } from "../locales/messages.ts";
import { reviewDurations } from "../../mocks/reviewPreference.ts";
import type { ReviewDuration } from "../../mocks/reviewPreference.ts";
import { accountApi } from "../services/accountApi.ts";
import { isLoopbackHost, isRealBackendMode } from "../services/backendMode.ts";
import { storageWrite, toPaise } from "../services/demoSession.ts";
import {
  accountCategories,
  demoContact,
  demoName,
  isEmailContact,
  isMobileContact,
} from "../types/account.ts";
import type { AccountCategory, DemoSession } from "../types/account.ts";
import type { Role } from "../types/payment.ts";

export function Auth({
  path,
  role,
  locale,
  onSession,
  expired,
}: {
  path: string;
  role: Role;
  locale: Locale;
  onSession: (session: DemoSession) => void;
  expired: boolean;
}) {
  const guardian = role === "guardian";
  const base = guardian ? "/guardian" : "/payer";
  const signup = path.endsWith("/signup");
  const form = signup || path.endsWith("/login");
  const enrollmentReturn =
    guardian &&
    (path === "/guardian/enrollment" ||
      new URLSearchParams(window.location.search).get("next") === "/guardian/enrollment");
  const authLink = (mode: "signup" | "login") =>
    `${base}/${mode}${enrollmentReturn ? "?next=/guardian/enrollment" : ""}`;

  const realBackend = isRealBackendMode();
  const [stage, setStage] = useState(1);
  const [name, setName] = useState("");
  const [contact, setContact] = useState("");
  const [password, setPassword] = useState("");
  const [loginMethod, setLoginMethod] = useState<"password" | "demo">("password");
  const [otpChallengeId, setOtpChallengeId] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [otpPreview, setOtpPreview] = useState<string | null>(null);
  const [language, setLanguage] = useState(locale);
  const [category, setCategory] = useState<AccountCategory>("personal");
  const [organization, setOrganization] = useState("");
  const [largeText, setLargeText] = useState(false);
  const [thresholdInput, setThresholdInput] = useState("");
  const [chosenDuration, setChosenDuration] = useState<ReviewDuration>(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [statusMessage, setStatusMessage] = useState("");
  const [invalid, setInvalid] = useState<"name" | "contact" | "password" | "otp">();
  const sending = useRef(false);
  const nameInput = useRef<HTMLInputElement>(null);
  const contactInput = useRef<HTMLInputElement>(null);
  const passwordInput = useRef<HTMLInputElement>(null);
  const stepHeading = useRef<HTMLHeadingElement>(null);

  const isEmail = isEmailContact(contact);
  const isMobile = isMobileContact(contact);

  // Keep sample access immediately reachable on payer sign-up & sign-in, and on guardian sign-in
  const showSampleAccess =
    !enrollmentReturn && (!realBackend || isLoopbackHost()) && (!guardian || !signup);
  const provisionedContact = guardian ? "ravi@pauseguard.test" : "asha@pauseguard.test";

  async function resendSignupOtp() {
    if (sending.current || !contact.trim()) return;
    sending.current = true;
    setBusy(true);
    setError("");
    setStatusMessage("");
    try {
      const challenge = await accountApi.v5RequestOtp({
        contact: contact.trim(),
        purpose: "signup_email",
        channel: "email",
      });
      setOtpChallengeId(challenge.challenge_id);
      setOtpPreview(challenge.dev_otp_preview ?? null);
      setStatusMessage("Fresh verification OTP issued.");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not resend verification OTP.");
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }

  async function submit(event?: FormEvent, sample = false) {
    event?.preventDefault();
    if (sending.current) return;
    setError("");
    setStatusMessage("");
    setInvalid(undefined);

    if (realBackend && !sample) {
      if (signup) {
        if (stage === 1) {
          if (!demoName(name)) {
            setInvalid("name");
            setError("Enter your full name (at least 2 letters).");
            nameInput.current?.focus();
            return;
          }
          if (!isEmail) {
            setInvalid("contact");
            setError("Enter a valid email address for account verification.");
            contactInput.current?.focus();
            return;
          }
          if (password.length < 8) {
            setInvalid("password");
            setError("Password must be at least 8 characters long.");
            passwordInput.current?.focus();
            return;
          }
          sending.current = true;
          setBusy(true);
          try {
            const res = await accountApi.v5Signup({
              email: contact,
              password,
              fullName: name,
              role: guardian ? "guardian" : "payer",
            });
            setOtpChallengeId(res.challenge_id);
            setOtpPreview(res.dev_otp_preview ?? null);
            setStage(2);
            setStatusMessage(
              "Account registered. Enter the verification OTP below to activate your account.",
            );
            requestAnimationFrame(() => stepHeading.current?.focus());
          } catch (failure) {
            setError(failure instanceof Error ? failure.message : "Could not create account.");
          } finally {
            sending.current = false;
            setBusy(false);
          }
          return;
        }

        if (!otpCode.trim()) {
          setInvalid("otp");
          setError("Enter the 6-digit verification OTP.");
          return;
        }
        sending.current = true;
        setBusy(true);
        try {
          await accountApi.v5VerifyOtp({ challengeId: otpChallengeId, otpCode });
          const session = await accountApi.v5Login(role, contact, password);
          onSession(session);
        } catch (failure) {
          setError(failure instanceof Error ? failure.message : "OTP verification failed.");
        } finally {
          sending.current = false;
          setBusy(false);
        }
        return;
      }

      const trimmedContact = contact.trim();
      if (loginMethod === "password") {
        if (!isEmail) {
          setInvalid("contact");
          setError("Enter the registered email address.");
          contactInput.current?.focus();
          return;
        }
        if (!password) {
          setInvalid("password");
          setError("Enter your account password.");
          passwordInput.current?.focus();
          return;
        }
        sending.current = true;
        setBusy(true);
        try {
          const session = await accountApi.v5Login(role, trimmedContact, password);
          onSession(session);
        } catch (failure) {
          setError(failure instanceof Error ? failure.message : "Invalid email or password.");
        } finally {
          sending.current = false;
          setBusy(false);
        }
        return;
      }
      if (!trimmedContact) {
        setInvalid("contact");
        setError("Enter a synthetic demo contact or backend-issued bearer token.");
        contactInput.current?.focus();
        return;
      }
    } else if (!sample) {
      if (signup && !demoName(name)) {
        setInvalid("name");
        setError("Enter a fictional full name with at least two letters.");
        nameInput.current?.focus();
        return;
      }
      if (!demoContact(contact)) {
        setInvalid("contact");
        setError("Enter a valid email address or 10-digit Indian mobile number.");
        contactInput.current?.focus();
        return;
      }
      if (signup && stage === 1) {
        setStage(2);
        requestAnimationFrame(() => stepHeading.current?.focus());
        return;
      }
    }

    sending.current = true;
    setBusy(true);
    try {
      let session: DemoSession;
      if (!realBackend && signup && !sample) {
        const thresholdPaise = thresholdInput.trim() ? toPaise(thresholdInput) : null;
        session = await accountApi.register(role, {
          name,
          contact,
          language,
          category,
          organization,
          largeText,
          thresholdPaise: thresholdPaise ?? undefined,
        });
        if (!guardian && session.profile.id) {
          storageWrite(
            "localStorage",
            `pauseguard:demo:review-seconds:${session.profile.id}`,
            String(chosenDuration),
          );
        }
      } else {
        session = await accountApi.login(role, contact, sample);
      }
      onSession(session);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The service could not sign you in.");
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }

  const headingText = signup
    ? "Create your preview account"
    : form
      ? "Sign in"
      : "Continue to PauseGuard";

  return (
    <div className="auth-stage">
      {/* Ambient sculpted pause bars + ribbon thread continuing the homepage visual language */}
      <div className="auth-ambient" aria-hidden="true">
        <span className="auth-sculpt-bar auth-sculpt-left" />
        <span className="auth-sculpt-bar auth-sculpt-right" />
        <svg className="auth-ribbon-svg" viewBox="0 0 1200 320" preserveAspectRatio="none">
          <defs>
            <linearGradient id="pg-auth-ribbon" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor="var(--brand-accent)" stopOpacity="0" />
              <stop offset="0.22" stopColor="var(--brand-accent)" stopOpacity="0.65" />
              <stop offset="0.52" stopColor="#ffffff" stopOpacity="0.85" />
              <stop offset="0.82" stopColor="#a855f7" stopOpacity="0.65" />
              <stop offset="1" stopColor="#a855f7" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path
            d="M 0 210 C 260 110, 440 260, 620 155 S 960 70, 1200 140"
            fill="none"
            stroke="url(#pg-auth-ribbon)"
            strokeWidth="1.6"
          />
          <path
            d="M 0 226 C 270 128, 450 274, 630 168 S 970 86, 1200 156"
            fill="none"
            stroke="url(#pg-auth-ribbon)"
            strokeWidth="0.9"
            strokeOpacity="0.55"
          />
        </svg>
      </div>

      <section className="card account-card auth-card" aria-labelledby="auth-heading">
        <div className="auth-top-meta">
          <span className="eyebrow">{guardian ? "Guardian portal" : "Payer workspace"}</span>
          <a className="auth-role-switch" href={guardian ? "/payer/login" : "/guardian/login"}>
            {guardian ? "Switch to payer" : "Guardian portal"} <Icon name="arrow" size={13} />
          </a>
        </div>

        <div className="card-header-block">
          <h1 id="auth-heading">{headingText}</h1>
          <p className="form-note">
            {realBackend
              ? "Local sandbox mode: Email + password + local mock OTP verification. No real funds or live bank KYC."
              : "Use fictional details in this preview. No verification messages are sent and no funds move."}
          </p>
        </div>

        {form && (
          <div className="auth-mode-tabs" aria-label="Account access mode">
            <a
              href={authLink("signup")}
              className={`auth-mode-tab${signup ? " is-active" : ""}`}
              aria-current={signup ? "page" : undefined}
            >
              Create account
            </a>
            <a
              href={authLink("login")}
              className={`auth-mode-tab${!signup ? " is-active" : ""}`}
              aria-current={!signup ? "page" : undefined}
            >
              Sign in
            </a>
          </div>
        )}

        {expired && (
          <p role="alert" className="notice">
            Your demo session expired. Sign in again to continue.
          </p>
        )}
        {error && (
          <p id="auth-error" role="alert" className="notice">
            {error}
          </p>
        )}
        {statusMessage && (
          <p role="status" className="form-note status-banner">
            {statusMessage}
          </p>
        )}

        {form ? (
          <form className="account-form" noValidate onSubmit={(event) => void submit(event)}>
            {realBackend && !signup && (
              <div className="segmented-tabs" role="tablist" aria-label="Sign in method">
                <button
                  type="button"
                  role="tab"
                  aria-selected={loginMethod === "password"}
                  className={loginMethod === "password" ? "seg-tab is-active" : "seg-tab"}
                  onClick={() => {
                    setLoginMethod("password");
                    setError("");
                  }}
                >
                  Email &amp; Password
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={loginMethod === "demo"}
                  className={loginMethod === "demo" ? "seg-tab is-active" : "seg-tab"}
                  onClick={() => {
                    setLoginMethod("demo");
                    setError("");
                  }}
                >
                  Demo / Token
                </button>
              </div>
            )}

            {signup && (
              <div className="onboarding-stepper">
                <div className="stepper-row">
                  <span className="account-step">
                    Step {stage} of 2 ·{" "}
                    {stage === 1
                      ? realBackend
                        ? "Account credentials"
                        : "Account details"
                      : realBackend
                        ? "Email OTP verification"
                        : "Protection preferences"}
                  </span>
                  <span className="stepper-fraction">{stage}/2</span>
                </div>
                <div className="stepper-bar">
                  <div
                    className="stepper-progress"
                    style={{ width: stage === 1 ? "50%" : "100%" }}
                  />
                </div>
              </div>
            )}

            {/* STAGE 1 */}
            <fieldset hidden={signup && stage === 2} disabled={busy}>
              {signup && (
                <label>
                  Full name
                  <input
                    ref={nameInput}
                    value={name}
                    maxLength={120}
                    required
                    autoComplete="name"
                    aria-invalid={invalid === "name" || undefined}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="e.g. Asha Nair"
                  />
                </label>
              )}

              <label>
                {realBackend && !signup && loginMethod === "demo"
                  ? "Synthetic contact or bearer token"
                  : realBackend
                    ? "Email address"
                    : "Email or mobile"}
                <input
                  ref={contactInput}
                  value={contact}
                  maxLength={512}
                  required
                  autoComplete={realBackend && loginMethod === "password" ? "email" : "off"}
                  spellCheck={false}
                  aria-invalid={invalid === "contact" || undefined}
                  aria-describedby="contact-help"
                  onChange={(event) => setContact(event.target.value)}
                  placeholder={
                    realBackend && !signup && loginMethod === "demo"
                      ? `${provisionedContact} or bearer token`
                      : realBackend
                        ? "you@example.com"
                        : "asha@example.test"
                  }
                />
              </label>

              {realBackend && (signup || loginMethod === "password") && (
                <label>
                  Password
                  <input
                    ref={passwordInput}
                    type="password"
                    value={password}
                    maxLength={128}
                    required
                    autoComplete={signup ? "new-password" : "current-password"}
                    aria-invalid={invalid === "password" || undefined}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder={signup ? "At least 8 characters" : "Enter your password"}
                  />
                </label>
              )}

              <p className="field-help" id="contact-help">
                {realBackend && !signup && loginMethod === "demo"
                  ? `FastAPI demo session (/api/v2/demo/session). Provisioned identity: ${provisionedContact}`
                  : realBackend
                    ? "Authenticated against FastAPI (/api/v2/auth/*)."
                    : contact && (isEmail || isMobile)
                      ? "Format looks right. Contact details are not verified in this preview."
                      : "Use a fictional email such as asha@example.test or a 10-digit mobile number."}
              </p>
            </fieldset>

            {/* STAGE 2 (REAL BACKEND): EMAIL OTP */}
            {realBackend && signup && stage === 2 && (
              <fieldset disabled={busy}>
                <h3 tabIndex={-1} ref={stepHeading}>
                  Verify your email via OTP
                </h3>
                {otpPreview && (
                  <div className="otp-preview-box" role="status">
                    <strong>Local Mock OTP Preview:</strong> <code>{otpPreview}</code>
                    <span className="field-help">
                      Displayed strictly because local mock OTP delivery is active (never shown in
                      production).
                    </span>
                  </div>
                )}
                <label>
                  Verification OTP code
                  <input
                    value={otpCode}
                    maxLength={12}
                    required
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    aria-invalid={invalid === "otp" || undefined}
                    onChange={(event) => setOtpCode(event.target.value)}
                    placeholder="Enter 6-digit OTP"
                  />
                </label>
                <div>
                  <button
                    className="text-button"
                    type="button"
                    disabled={busy}
                    onClick={() => void resendSignupOtp()}
                  >
                    Resend verification OTP
                  </button>
                </div>
              </fieldset>
            )}

            {/* STAGE 2 (STANDALONE DEMO): PREFERENCES */}
            {!realBackend && signup && stage === 2 && (
              <fieldset disabled={busy}>
                <h3 tabIndex={-1} ref={stepHeading}>
                  Set your preferences
                </h3>

                {!guardian && (
                  <label>
                    Account type
                    <select
                      value={category}
                      onChange={(event) => setCategory(event.target.value as AccountCategory)}
                    >
                      {Object.entries(accountCategories).map(([key, value]) => (
                        <option key={key} value={key}>
                          {value}
                        </option>
                      ))}
                    </select>
                  </label>
                )}

                {!guardian && category !== "personal" && (
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
                    <select
                      value={language}
                      onChange={(event) => setLanguage(event.target.value as Locale)}
                    >
                      {Object.entries(languages).map(([code, value]) => (
                        <option key={code} value={code} lang={code}>
                          {value.label}
                        </option>
                      ))}
                    </select>
                  </label>

                  {!guardian && (
                    <label>
                      Review duration
                      <select
                        value={chosenDuration}
                        onChange={(event) =>
                          setChosenDuration(Number(event.target.value) as ReviewDuration)
                        }
                      >
                        {reviewDurations.map((seconds) => (
                          <option key={seconds} value={seconds}>
                            {seconds} seconds
                          </option>
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
                </div>
              </fieldset>
            )}

            <div className="actions auth-submit-row">
              {!realBackend && signup && stage === 2 && (
                <button
                  className="secondary"
                  type="button"
                  disabled={busy}
                  onClick={() => setStage(1)}
                >
                  Back
                </button>
              )}
              <button className="primary" type="submit" disabled={busy}>
                {busy
                  ? "Please wait…"
                  : signup
                    ? stage === 1
                      ? realBackend
                        ? "Create account & send OTP"
                        : "Continue"
                      : realBackend
                        ? "Verify OTP & Sign in"
                        : "Create account"
                    : realBackend && loginMethod === "password"
                      ? "Sign in"
                      : "Sign in to preview"}
                {!busy && <Icon name="arrow" size={16} />}
              </button>
            </div>
          </form>
        ) : (
          <div className="actions auth-landing-actions">
            <a className="primary" href={authLink("signup")}>
              Sign up
            </a>
            <a className="secondary" href={authLink("login")}>
              Sign in
            </a>
          </div>
        )}

        {showSampleAccess && (
          <div className="sample-access-dock">
            <div className="sample-dock-copy">
              <span className="sample-dock-eyebrow">Quick walkthrough</span>
              <p>
                {guardian
                  ? "Enter with the pre-enrolled guardian account to review paused requests."
                  : "Skip setup and try a live payment check with a pre-enrolled sample account."}
              </p>
            </div>
            <button
              className="secondary sample-entry-btn"
              type="button"
              disabled={busy}
              onClick={() => void submit(undefined, true)}
            >
              <span>{guardian ? "Open sample guardian" : "Open sample payer"}</span>
              <Icon name="arrow" size={15} />
            </button>
          </div>
        )}

        {form && (
          <div className="auth-mode-switch">
            <a className="text-button" href={authLink(signup ? "login" : "signup")}>
              {signup ? "Already registered? Sign in" : "Create an account"}
            </a>
          </div>
        )}

        {realBackend && form && loginMethod === "demo" && !signup && (
          <div className="admin-login-meta">
            <span className="pill neutral">
              <Icon name="lock" size={13} /> Provisioned identity: <code>{provisionedContact}</code>
            </span>
            <span className="pill neutral">Server-enforced role boundary</span>
          </div>
        )}
      </section>
    </div>
  );
}
