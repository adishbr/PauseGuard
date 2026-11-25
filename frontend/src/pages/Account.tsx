import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { beneficiaries } from "../../mocks/scenarios.ts";
import { Icon } from "../components/Icon.tsx";
import { languages } from "../locales/messages.ts";
import type { Locale } from "../locales/messages.ts";
import { accountApi } from "../services/accountApi.ts";
import { decimalRupees, toPaise } from "../services/demoSession.ts";
import { accountCategories, demoContact, demoName } from "../types/account.ts";
import type { AccountCategory, DemoProfile, ProfileUpdate } from "../types/account.ts";

export function Account({
  profile,
  token,
  saved,
}: {
  profile: DemoProfile;
  token: string;
  saved: (next: DemoProfile) => void;
}) {
  const [fields, setFields] = useState(profile);
  const [threshold, setThreshold] = useState(
    profile.thresholdPaise === null ? "" : decimalRupees(profile.thresholdPaise),
  );
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ message: string; error?: boolean }>();
  const sending = useRef(false);
  const payer = profile.role === "payer";

  function update<K extends keyof DemoProfile>(key: K, value: DemoProfile[K]) {
    setFields((before) => ({ ...before, [key]: value }));
    setNotice(undefined);
  }

  async function persist(changes: ProfileUpdate) {
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    setNotice(undefined);
    try {
      const next = await accountApi.save(token, changes);
      setFields((previous) =>
        "safeLock" in changes ? { ...previous, safeLock: next.safeLock } : next,
      );
      saved(next);
      setNotice({ message: "Settings saved." });
    } catch (failure) {
      setNotice({
        error: true,
        message: failure instanceof Error ? failure.message : "Settings could not be saved.",
      });
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const thresholdPaise = payer && threshold.trim() ? toPaise(threshold) : null;
    if (
      !demoName(fields.name) ||
      !demoContact(fields.contact) ||
      (payer && threshold.trim() && thresholdPaise === null)
    ) {
      setNotice({
        error: true,
        message: "Check the fictional name, demo contact and payment alert threshold.",
      });
      return;
    }
    const details = {
      name: fields.name,
      contact: fields.contact,
      language: fields.language,
      largeText: fields.largeText,
    };
    void persist(
      payer
        ? {
            ...details,
            category: fields.category,
            organization: fields.organization,
            recurringSupplier: fields.recurringSupplier,
            thresholdPaise,
            notifications: fields.notifications,
            quietStart: fields.quietStart,
            quietEnd: fields.quietEnd,
            callConsent: fields.callConsent,
          }
        : details,
    );
  }

  return (
    <div className="profile-split-layout">
      {/* Left Identity & Section Directory */}
      <aside className="profile-directory-rail">
        <div className="card profile-identity-summary">
          <div className="profile-avatar-large">{fields.name.charAt(0).toUpperCase() || "P"}</div>
          <p className="eyebrow">Account Settings</p>
          <h2>Profile</h2>
          <p className="field-help">
            Use fictional or realistic details. Account categories, suppliers, and threshold
            settings are self-declared.
          </p>
          <div className="profile-Quick-badges">
            <span className="pill neutral">{payer ? "Payer" : "Guardian"}</span>
            <span className="pill neutral">
              {languages[fields.language]?.label ?? fields.language}
            </span>
          </div>
          <nav className="profile-section-links" aria-label="Profile sections">
            {payer && <a href="#safelock-section">Safe-Lock control</a>}
            <a href="#about-you-section">About you</a>
            {payer && fields.category !== "personal" && (
              <a href="#business-section">Business preferences</a>
            )}
            {payer && <a href="#notifications-section">Notifications &amp; consent</a>}
          </nav>
        </div>
      </aside>

      {/* Right Settings Stack */}
      <div className="profile-settings-stack">
        {payer && (
          <section
            id="safelock-section"
            className={`card safety-setting safelock-card ${profile.safeLock ? "safelock-on" : "safelock-off"}`}
          >
            <div className="safelock-header">
              <div className="safelock-icon-symbol">
                <Icon name={profile.safeLock ? "lock" : "unlock"} size={24} />
              </div>
              <div>
                <span className="eyebrow">Immediate Transfer Lock</span>
                <h3>Safe-Lock is {profile.safeLock ? "on" : "off"}</h3>
                <p className="field-help">
                  Safe-Lock blocks simulated outgoing payments, including requests awaiting your
                  final confirmation.
                </p>
              </div>
            </div>
            <button
              className={`secondary safelock-action-btn ${profile.safeLock ? "btn-unlock" : "btn-lock"}`}
              disabled={busy}
              type="button"
              onClick={() => void persist({ safeLock: !profile.safeLock })}
            >
              <Icon name={profile.safeLock ? "unlock" : "lock"} size={15} />
              {profile.safeLock ? "Turn off Safe-Lock" : "Turn on Safe-Lock"}
            </button>
          </section>
        )}

        <section className="card account-card profile-settings-card">
          <form className="account-form profile-structured-form" onSubmit={submit} noValidate>
            <fieldset id="about-you-section" disabled={busy} className="settings-section-block">
              <div className="settings-section-intro">
                <legend>About you</legend>
                <p className="field-help">
                  Display identity, language preference, and text readability.
                </p>
              </div>
              <div className="settings-section-fields">
                <div className="account-fields">
                  <label>
                    Full name
                    <input
                      required
                      maxLength={64}
                      value={fields.name}
                      onChange={(e) => update("name", e.target.value)}
                    />
                  </label>
                  <label>
                    Email or mobile
                    <input
                      required
                      maxLength={90}
                      value={fields.contact}
                      placeholder="name@gmail.com or 9876543210"
                      aria-describedby="contact-verification-status"
                      onChange={(e) => update("contact", e.target.value)}
                    />
                  </label>
                  <label>
                    Preferred language
                    <select
                      value={fields.language}
                      onChange={(e) => update("language", e.target.value as Locale)}
                    >
                      {Object.entries(languages).map(([key, value]) => (
                        <option key={key} value={key} lang={key}>
                          {value.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  {payer && (
                    <label>
                      Account type
                      <select
                        value={fields.category}
                        onChange={(e) => update("category", e.target.value as AccountCategory)}
                      >
                        {Object.entries(accountCategories).map(([key, value]) => (
                          <option key={key} value={key}>
                            {value}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                </div>
                <p id="contact-verification-status" className="field-help sandbox-inline-note">
                  <span className="pill neutral">Demo Sandbox</span> Contact ownership is
                  unverified. Real OTP and email verification connect to production IAM.
                </p>
                <label className="check-row toggle-tile">
                  <input
                    type="checkbox"
                    checked={fields.largeText}
                    onChange={(e) => update("largeText", e.target.checked)}
                  />
                  <span>Use larger text</span>
                </label>
              </div>
            </fieldset>

            {payer && fields.category !== "personal" && (
              <fieldset id="business-section" disabled={busy} className="settings-section-block">
                <div className="settings-section-intro">
                  <legend>Professional and business preferences</legend>
                  <p className="field-help">
                    Payment safety checks still apply to recurring suppliers.
                  </p>
                </div>
                <div className="settings-section-fields">
                  <div className="account-fields">
                    <label>
                      Organization (optional)
                      <input
                        maxLength={80}
                        value={fields.organization}
                        onChange={(e) => update("organization", e.target.value)}
                      />
                    </label>
                    <label>
                      Recurring supplier (optional)
                      <select
                        value={fields.recurringSupplier}
                        onChange={(e) => update("recurringSupplier", e.target.value)}
                      >
                        <option value="">Choose later</option>
                        {Object.entries(beneficiaries)
                          .filter(([key]) => key !== "recipient_flagged")
                          .map(([key, value]) => (
                            <option key={key} value={key}>
                              {value}
                            </option>
                          ))}
                      </select>
                    </label>
                  </div>
                </div>
              </fieldset>
            )}

            {payer && (
              <fieldset
                id="notifications-section"
                disabled={busy}
                className="settings-section-block"
              >
                <div className="settings-section-intro">
                  <legend>Notifications and consent</legend>
                  <p className="field-help">
                    Personal alert preferences never override independent payment safety policy.
                  </p>
                </div>
                <div className="settings-section-fields">
                  <label>
                    Personal payment alert threshold (INR, optional)
                    <input
                      inputMode="decimal"
                      value={threshold}
                      onChange={(e) => setThreshold(e.target.value)}
                    />
                  </label>
                  <p className="field-help">
                    The threshold affects your alert preferences. Payment safety policy is evaluated
                    separately.
                  </p>
                  <label className="check-row toggle-tile">
                    <input
                      type="checkbox"
                      checked={fields.notifications}
                      onChange={(e) => update("notifications", e.target.checked)}
                    />
                    <span>Allow optional notifications</span>
                  </label>
                  <div className="account-fields">
                    <label>
                      Quiet hours start (optional)
                      <input
                        type="time"
                        value={fields.quietStart}
                        onChange={(e) => update("quietStart", e.target.value)}
                      />
                    </label>
                    <label>
                      Quiet hours end (optional)
                      <input
                        type="time"
                        value={fields.quietEnd}
                        onChange={(e) => update("quietEnd", e.target.value)}
                      />
                    </label>
                  </div>
                  <label className="check-row toggle-tile">
                    <input
                      type="checkbox"
                      checked={fields.callConsent}
                      onChange={(e) => update("callConsent", e.target.checked)}
                    />
                    <span>I opt in to simulated guardian call preferences</span>
                  </label>
                  <p className="field-help">
                    Delivery and quiet-hours scheduling are planned provider integrations.
                  </p>
                </div>
              </fieldset>
            )}

            <div className="profile-save-bar">
              <button className="primary" disabled={busy} type="submit">
                {busy ? "Saving…" : "Save profile"}
              </button>
              {notice && (
                <p
                  className={notice.error ? "notice" : "form-note status-banner"}
                  role={notice.error ? "alert" : "status"}
                >
                  {notice.message}
                </p>
              )}
            </div>
          </form>
        </section>
      </div>
    </div>
  );
}
