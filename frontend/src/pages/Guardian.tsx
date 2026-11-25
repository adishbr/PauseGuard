import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Icon } from "../components/Icon.tsx";
import { PaymentStatus } from "../components/PaymentStatus.tsx";
import { translator } from "../locales/messages.ts";
import type { Locale } from "../locales/messages.ts";
import { accountApi } from "../services/accountApi.ts";
import { isReference, reviewKey, storageRead, storageWrite } from "../services/demoSession.ts";
import { listNotificationOutbox } from "../services/paymentApi.ts";
import type { NotificationOutboxItem } from "../services/paymentApi.ts";

const guardianKey = "pauseguard:demo:guardian-payment";

export function Guardian({
  locale,
  token,
  accountId,
}: {
  locale: Locale;
  token: string;
  accountId: string;
}) {
  const t = translator(locale);
  const [latest, setLatest] = useState("");
  const [outboxItems, setOutboxItems] = useState<NotificationOutboxItem[]>([]);
  const [inboxError, setInboxError] = useState(false);
  const [id, setId] = useState(() => {
    const previous = storageRead("sessionStorage", `${guardianKey}:${accountId}`);
    return isReference(previous) ? previous : "";
  });
  const [reference, setReference] = useState("");
  const [invalidReference, setInvalidReference] = useState(false);
  const [returning, setReturning] = useState(false);
  const referenceInput = useRef<HTMLInputElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (id) return;
    let active = true;
    let reading = false;
    async function readLatest() {
      if (!active || reading) return;
      reading = true;
      try {
        const [result, outbox] = await Promise.all([
          accountApi.review(token, storageRead("localStorage", reviewKey)),
          listNotificationOutbox(token, 8).catch(() => []),
        ]);
        if (active) {
          setLatest(result.id ?? "");
          setOutboxItems(outbox);
          setInboxError(false);
        }
      } catch {
        if (active) {
          setLatest("");
          setInboxError(true);
        }
      } finally {
        reading = false;
      }
    }
    void readLatest();
    const interval = setInterval(() => void readLatest(), 1_000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [id, token]);

  useEffect(() => {
    if (returning && !id) heading.current?.focus();
  }, [id, returning]);

  function openRequest(next: string) {
    storageWrite("sessionStorage", `${guardianKey}:${accountId}`, next);
    setReturning(!next);
    setId(next);
    setInvalidReference(false);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isReference(reference.trim())) {
      openRequest(reference.trim());
    } else {
      setInvalidReference(true);
      referenceInput.current?.focus();
    }
  }

  if (id) {
    return (
      <PaymentStatus
        key={id}
        id={id}
        role="guardian"
        token={token}
        locale={locale}
        onClose={() => openRequest("")}
      />
    );
  }

  const hasReview = isReference(latest);

  return (
    <div className="guardian-watch-stack">
      <section
        className="card workspace-card guardian-workspace-card"
        aria-labelledby="guardian-heading"
      >
        <div className="composer-top">
          <div>
            <p className="eyebrow">{t("guardianInbox")}</p>
            <h2 id="guardian-heading" ref={heading} tabIndex={-1}>
              {t("safetyReviews")}
            </h2>
          </div>
          <span className={`pill ${hasReview ? "caution" : "neutral"} header-tag`}>
            <Icon name="radar" size={14} /> {hasReview ? "Action Needed" : "Live Review Watch"}
          </span>
        </div>

        {/* Primary Live Review Stage */}
        <div className={hasReview ? "inbox inbox-active" : "inbox"}>
          <div className="inbox-icon-container">
            <Icon name={hasReview ? "shieldAlert" : "radar"} size={24} />
            {!hasReview && <span className="radar-ping" aria-hidden="true" />}
          </div>
          <div role="status" className="inbox-status-copy">
            <strong>
              {inboxError
                ? "Review alerts unavailable. Reconnecting…"
                : t(hasReview ? "reviewReceived" : "waitingRequest")}
            </strong>
            <p>{t(hasReview ? "latestRequest" : "sameBrowser")}</p>
          </div>
          {hasReview && (
            <button
              type="button"
              className="primary open-review-btn"
              onClick={() => openRequest(latest)}
            >
              {t("openReview")} <Icon name="arrow" size={18} />
            </button>
          )}
        </div>

        {/* Split Utility Row: Reference Lookup + Privacy Scope */}
        <div className="guardian-utility-grid">
          <div className="guardian-lookup-panel">
            <h3>Open by request reference</h3>
            <form className="reference-form" noValidate onSubmit={submit}>
              <label>
                {t("reference")}
                <input
                  ref={referenceInput}
                  placeholder="pg_…"
                  value={reference}
                  onChange={(event) => {
                    setReference(event.target.value);
                    setInvalidReference(false);
                  }}
                  aria-invalid={invalidReference || undefined}
                  aria-describedby="reference-help"
                  required
                  autoComplete="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  maxLength={83}
                />
              </label>
              <button type="submit" className="secondary">
                {t("findRequest")}
              </button>
            </form>
            <p
              id="reference-help"
              className={invalidReference ? "field-error" : "form-note"}
              role={invalidReference ? "alert" : undefined}
            >
              {t(invalidReference ? "invalidReference" : "separateProfile")}
            </p>
          </div>

          <div className="guardian-privacy-summary-card">
            <div className="privacy-card-icon">
              <Icon name="lock" size={17} />
            </div>
            <div>
              <strong>Authorized view only</strong>
              <p className="field-help">
                You see the request reference, risk tier, status, and server countdown. Recipient,
                amount, and payment purpose stay private with the payer.
              </p>
              <div className="privacy-pills">
                <span>Recipient hidden</span>
                <span>Amount hidden</span>
                <span>Purpose hidden</span>
              </div>
            </div>
          </div>
        </div>

        {outboxItems.length > 0 && (
          <div className="detail-panel" aria-label="Durable Notification Outbox">
            <div className="outbox-header">
              <strong>Notification Outbox ({outboxItems.length})</strong>
              <span className="pill neutral">Redacted · Cross-Device</span>
            </div>
            <ul className="audit-list">
              {outboxItems.slice(0, 5).map((item) => (
                <li key={item.notification_id} className="audit-item">
                  <span>
                    <code>{item.event_type}</code> · {item.channel} ({item.status})
                  </span>
                  {item.payment_id && (
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => openRequest(item.payment_id ?? "")}
                    >
                      Inspect {item.payment_id}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </div>
  );
}
