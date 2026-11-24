import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Icon } from "../components/Icon.tsx";
import { accountApi } from "../services/accountApi.ts";
import type {
  V5GuardianInvitation,
  V5GuardianInvitationList,
  V5IdentityAssurance,
} from "../services/accountApi.ts";
import { isRealBackendMode } from "../services/backendMode.ts";
import { demoContact, demoName, relationships } from "../types/account.ts";
import type { DemoProfile, EnrollmentView, Relationship } from "../types/account.ts";

export function Enrollment({ profile, token }: { profile: DemoProfile; token: string }) {
  const payer = profile.role === "payer";
  const realV5 = isRealBackendMode() && !profile.sample;

  const [items, setItems] = useState<EnrollmentView[]>();
  const [enabled, setEnabled] = useState(false);
  const [name, setName] = useState("");
  const [contact, setContact] = useState("");
  const [relationship, setRelationship] = useState<Relationship | "">("");
  const [consent, setConsent] = useState(false);
  const [acceptance, setAcceptance] = useState<string[]>([]);

  const [assurance, setAssurance] = useState<V5IdentityAssurance>();
  const [kycName, setKycName] = useState(profile.name || "");
  const [kycDocRef, setKycDocRef] = useState("");
  const [kycConsent, setKycConsent] = useState(false);

  const [invitations, setInvitations] = useState<V5GuardianInvitationList>();
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRel, setInviteRel] = useState<Relationship>("Family");
  const [inviteSlot, setInviteSlot] = useState<"primary" | "backup">("primary");
  const [inviteChannel, setInviteChannel] = useState<"in_app" | "email" | "push" | "sms">("in_app");
  const [latestCreatedInvite, setLatestCreatedInvite] = useState<V5GuardianInvitation>();

  const [acceptToken, setAcceptToken] = useState<Record<string, string>>({});
  const [acceptChallengeId, setAcceptChallengeId] = useState<Record<string, string>>({});
  const [acceptOtpPreview, setAcceptOtpPreview] = useState<Record<string, string>>({});
  const [acceptOtpCode, setAcceptOtpCode] = useState<Record<string, string>>({});
  const [acceptConsent, setAcceptConsent] = useState<Record<string, boolean>>({});

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [copiedLink, setCopiedLink] = useState(false);
  const acting = useRef(false);

  const loadV5State = useCallback(async () => {
    const [idStatus, invList] = await Promise.all([
      accountApi.identityStatus(token),
      accountApi.v5Invitations(token),
    ]);
    setAssurance(idStatus);
    setInvitations(invList);
  }, [token]);

  useEffect(() => {
    let active = true;
    if (realV5) {
      void Promise.all([accountApi.identityStatus(token), accountApi.v5Invitations(token)]).then(
        ([idStatus, invList]) => {
          if (!active) return;
          setAssurance(idStatus);
          setInvitations(invList);
        },
        (failure) => {
          if (active)
            setError(
              failure instanceof Error ? failure.message : "Failed to load enrollment state.",
            );
        },
      );
    } else {
      void accountApi.enrollments(token).then(
        (data) => {
          if (active) setItems(data);
        },
        (failure) => {
          if (active) setError(failure.message);
        },
      );
    }
    return () => {
      active = false;
    };
  }, [realV5, token]);

  async function verifyIdentity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (acting.current) return;
    setError("");
    setMessage("");
    if (!kycName.trim() || kycDocRef.trim().length < 4 || !kycConsent) {
      setError(
        "Enter your full legal name, synthetic document reference (4+ chars), and confirm consent.",
      );
      return;
    }
    acting.current = true;
    setBusy(true);
    try {
      const next = await accountApi.identityVerify(token, {
        fullName: kycName,
        syntheticDocumentRef: kycDocRef,
        consentConfirmed: kycConsent,
      });
      setAssurance(next);
      setKycDocRef("");
      setMessage(
        "Synthetic identity assurance recorded cleanly. Raw document reference discarded.",
      );
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Identity verification failed.");
    } finally {
      acting.current = false;
      setBusy(false);
    }
  }

  async function sendV5Invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (acting.current) return;
    setError("");
    setMessage("");
    if (!inviteEmail.trim() || !consent) {
      setError("Enter the guardian email and confirm limited notification consent.");
      return;
    }
    acting.current = true;
    setBusy(true);
    try {
      const created = await accountApi.createV5Invitation(token, {
        guardianEmail: inviteEmail,
        relationship: inviteRel,
        roleSlot: inviteSlot,
        notificationChannel: inviteChannel,
      });
      setLatestCreatedInvite(created);
      setInviteEmail("");
      await loadV5State();
      setMessage("Durable guardian invitation created.");
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "Could not create guardian invitation.",
      );
    } finally {
      acting.current = false;
      setBusy(false);
    }
  }

  async function requestInviteOtp(invitationId: string, guardianEmail: string) {
    if (acting.current) return;
    acting.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const challenge = await accountApi.v5RequestOtp({
        contact: guardianEmail,
        purpose: "guardian_invite",
        channel: "email",
      });
      setAcceptChallengeId((prev) => ({ ...prev, [invitationId]: challenge.challenge_id }));
      if (challenge.dev_otp_preview) {
        setAcceptOtpPreview((prev) => ({ ...prev, [invitationId]: challenge.dev_otp_preview! }));
      }
      setMessage("Guardian invitation verification OTP issued.");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Failed to request invite OTP.");
    } finally {
      acting.current = false;
      setBusy(false);
    }
  }

  async function acceptInvite(invitationId: string) {
    if (acting.current) return;
    setError("");
    setMessage("");
    const inviteToken = acceptToken[invitationId]?.trim() || "";
    const challengeId = acceptChallengeId[invitationId]?.trim() || "";
    const otp = acceptOtpCode[invitationId]?.trim() || "";
    const consented = Boolean(acceptConsent[invitationId]);
    if (!inviteToken || !challengeId || !otp || !consented) {
      setError(
        "Provide invite token, request & enter the OTP code, and confirm explicit guardian consent.",
      );
      return;
    }
    acting.current = true;
    setBusy(true);
    try {
      await accountApi.acceptV5Invitation(token, invitationId, {
        inviteToken,
        otpChallengeId: challengeId,
        otpCode: otp,
        explicitConsent: consented,
      });
      await loadV5State();
      setMessage("Guardian invitation verified and activated cleanly.");
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "Could not accept guardian invitation.",
      );
    } finally {
      acting.current = false;
      setBusy(false);
    }
  }

  async function handleInvitationStatusAction(
    invitationId: string,
    action: "decline" | "revoke" | "suspend",
  ) {
    if (acting.current) return;
    acting.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      if (action === "decline") {
        await accountApi.declineV5Invitation(token, invitationId);
        setMessage("Invitation declined.");
      } else if (action === "suspend") {
        await accountApi.suspendV5Invitation(token, invitationId, "suspected_compromise");
        setMessage("Guardian suspended immediately for security review.");
      } else {
        await accountApi.revokeV5Invitation(token, invitationId);
        setMessage("Guardian link revoked immediately.");
      }
      await loadV5State();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not update invitation.");
    } finally {
      acting.current = false;
      setBusy(false);
    }
  }

  async function change(body?: object, success?: string) {
    if (acting.current) return;
    acting.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      setItems(
        body ? await accountApi.enrollmentAction(token, body) : await accountApi.enrollments(token),
      );
      if (success) setMessage(success);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Enrollment could not be updated.");
    } finally {
      acting.current = false;
      setBusy(false);
    }
  }

  function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!demoName(name) || !demoContact(contact) || !relationship || !consent) {
      setError(
        "Enter a fictional name, demo contact and relationship, then confirm sharing consent.",
      );
      return;
    }
    void change(
      { action: "invite", name, contact, relationship, consent },
      "Simulated invitation created.",
    );
  }

  const privacyContractCard = (
    <aside className="enrollment-contract-rail">
      <div className="card contract-promise-card">
        <p className="eyebrow">Privacy contract</p>
        <h3>
          Independent review, <em className="text-accent-italic">not account access.</em>
        </h3>
        <div className="contract-columns">
          <div className="contract-box">
            <span className="contract-label">Guardian sees</span>
            <ul>
              <li>Assigned request reference</li>
              <li>Risk classification tier</li>
              <li>Review deadline &amp; status</li>
            </ul>
          </div>
          <div className="contract-box is-private">
            <span className="contract-label">Stays private with payer</span>
            <ul>
              <li>Recipient name &amp; VPA</li>
              <li>Payment rupee amount</li>
              <li>Purpose &amp; past transfers</li>
            </ul>
          </div>
        </div>
        <div className="contract-hold-note">
          <Icon name="clock" size={16} />
          <span>If a guardian does not respond in time, the payment stays on hold.</span>
        </div>
      </div>
    </aside>
  );

  if (realV5) {
    const visibleInvites = payer ? (invitations?.sent ?? []) : (invitations?.received ?? []);
    const hasActiveGuardian = visibleInvites.some((i) => i.status === "ACTIVE");

    return (
      <div className="enrollment-split-layout">
        <section className="card account-card enrollment-card">
          <div className="composer-top">
            <div>
              <p className="eyebrow">
                {payer ? "Identity & Trusted Guardians" : "Identity & Guardian Consent"}
              </p>
              <h2>{payer ? "KYC & Guardian Enrollment" : "KYC & Guardian Invitations"}</h2>
              <p className="card-lead">
                Independent contact OTP and synthetic identity assurance ensure a payer and guardian
                are distinct verified individuals before activation.
              </p>
            </div>
          </div>

          <article className="enrollment-item">
            <div className="enrollment-title">
              <h3>1. Identity Assurance (Synthetic Local IDP)</h3>
              <span className={`pill ${assurance?.verified ? "mint" : "caution"}`}>
                {assurance?.verified ? "Verified" : "Unverified"}
              </span>
            </div>
            {assurance?.verified ? (
              <div>
                <p className="field-help">
                  Provider: <code>{assurance.provider}</code> · Level:{" "}
                  <code>{assurance.assurance_level}</code>
                </p>
                <p className="field-help">
                  Opaque Person Ref: <code>{assurance.trusted_person_ref}</code> (Mock assurance:{" "}
                  {String(assurance.is_mock_assurance)})
                </p>
              </div>
            ) : (
              <form className="account-form" onSubmit={(e) => void verifyIdentity(e)} noValidate>
                <fieldset disabled={busy}>
                  <label>
                    Full legal name
                    <input
                      required
                      value={kycName}
                      onChange={(e) => setKycName(e.target.value)}
                      placeholder="e.g. Asha Nair"
                    />
                  </label>
                  <label>
                    Synthetic document reference (mock e-KYC — never real Aadhaar/PAN)
                    <input
                      required
                      value={kycDocRef}
                      onChange={(e) => setKycDocRef(e.target.value)}
                      placeholder="e.g. SYNTH-ASHA-001"
                    />
                  </label>
                  <p className="field-help">
                    Normalized in-memory via HMAC-SHA256 into an opaque person reference and
                    discarded immediately. Accounts sharing a reference cannot guard each other.
                  </p>
                  <label className="check-row toggle-tile">
                    <input
                      type="checkbox"
                      checked={kycConsent}
                      onChange={(e) => setKycConsent(e.target.checked)}
                    />
                    <span>
                      I consent to synthetic identity verification under PauseGuard V5 sandbox
                      terms.
                    </span>
                  </label>
                </fieldset>
                <button className="primary" type="submit" disabled={busy}>
                  Verify identity
                </button>
              </form>
            )}
          </article>

          <article className="enrollment-item">
            <div className="enrollment-title">
              <h3>2. {payer ? "Trusted Guardian Invitations" : "Received Guardian Invitations"}</h3>
              <span className={`pill ${hasActiveGuardian ? "mint" : "neutral"}`}>
                {hasActiveGuardian ? "Active Link" : "Pending"}
              </span>
            </div>

            {latestCreatedInvite?.dev_invite_token_preview && payer && (
              <div className="otp-preview-box" role="status">
                <strong>Local Mock Invite Token Preview (for guardian acceptance):</strong>{" "}
                <code>{latestCreatedInvite.dev_invite_token_preview}</code>
              </div>
            )}

            {invitations === undefined && !error && <p role="status">Loading invitations…</p>}
            {invitations && visibleInvites.length === 0 && (
              <p className="field-help">
                {payer
                  ? "No guardian invitations sent yet."
                  : "No guardian invitations received for your account email yet."}
              </p>
            )}

            <div className="enrollment-list">
              {visibleInvites.map((inv) => (
                <div key={inv.invitation_id} className="enrollment-item nested-invite-card">
                  <div className="enrollment-title">
                    <h4>
                      {payer ? inv.guardian_email : `Payer ${inv.payer_id.slice(0, 8)}…`} (
                      {inv.role_slot})
                    </h4>
                    <span
                      className={`pill ${
                        inv.status === "ACTIVE"
                          ? "mint"
                          : inv.status === "DECLINED" || inv.status === "REVOKED"
                            ? "danger"
                            : "caution"
                      }`}
                    >
                      {inv.status}
                    </span>
                  </div>
                  <p className="field-help">
                    Relationship: {inv.relationship} · Channel: {inv.notification_channel}
                  </p>

                  {!payer && inv.status === "PENDING" && (
                    <div className="invite-accept-stack">
                      {!assurance?.verified && (
                        <p className="notice" role="status">
                          Complete Step 1 (Identity Assurance) above before accepting.
                        </p>
                      )}
                      <label>
                        Invite Token
                        <input
                          value={acceptToken[inv.invitation_id] ?? ""}
                          onChange={(e) =>
                            setAcceptToken((p) => ({ ...p, [inv.invitation_id]: e.target.value }))
                          }
                          placeholder="Paste pg_inv_... token"
                        />
                      </label>
                      <div className="actions">
                        <button
                          type="button"
                          className="secondary"
                          disabled={busy}
                          onClick={() =>
                            void requestInviteOtp(inv.invitation_id, inv.guardian_email)
                          }
                        >
                          Request Invite OTP
                        </button>
                      </div>
                      {acceptOtpPreview[inv.invitation_id] && (
                        <p className="otp-preview-box" role="status">
                          <strong>Local Mock Invite OTP Preview:</strong>{" "}
                          <code>{acceptOtpPreview[inv.invitation_id]}</code>
                        </p>
                      )}
                      <label>
                        Invite OTP Code
                        <input
                          value={acceptOtpCode[inv.invitation_id] ?? ""}
                          onChange={(e) =>
                            setAcceptOtpCode((p) => ({ ...p, [inv.invitation_id]: e.target.value }))
                          }
                          placeholder="Enter 6-digit OTP"
                        />
                      </label>
                      <label className="check-row toggle-tile">
                        <input
                          type="checkbox"
                          checked={Boolean(acceptConsent[inv.invitation_id])}
                          onChange={(e) =>
                            setAcceptConsent((p) => ({
                              ...p,
                              [inv.invitation_id]: e.target.checked,
                            }))
                          }
                        />
                        <span>
                          I explicitly consent to serve as an independent guardian for
                          privacy-redacted approvals.
                        </span>
                      </label>
                      <div className="actions">
                        <button
                          type="button"
                          className="primary"
                          disabled={busy || !assurance?.verified}
                          onClick={() => void acceptInvite(inv.invitation_id)}
                        >
                          Verify &amp; Accept Invitation
                        </button>
                        <button
                          type="button"
                          className="secondary"
                          disabled={busy}
                          onClick={() =>
                            void handleInvitationStatusAction(inv.invitation_id, "decline")
                          }
                        >
                          Decline
                        </button>
                      </div>
                    </div>
                  )}

                  {(inv.status === "PENDING" || inv.status === "ACTIVE") &&
                    (payer || inv.status === "ACTIVE") && (
                      <div className="actions">
                        {payer && inv.status === "ACTIVE" && (
                          <button
                            type="button"
                            className="secondary"
                            disabled={busy}
                            onClick={() =>
                              void handleInvitationStatusAction(inv.invitation_id, "suspend")
                            }
                          >
                            Suspend (Suspected Compromise)
                          </button>
                        )}
                        <button
                          type="button"
                          className="secondary"
                          disabled={busy}
                          onClick={() =>
                            void handleInvitationStatusAction(inv.invitation_id, "revoke")
                          }
                        >
                          {inv.status === "ACTIVE" ? "Revoke Guardian Access" : "Cancel Invitation"}
                        </button>
                      </div>
                    )}
                </div>
              ))}
            </div>

            {payer && (
              <form className="account-form" onSubmit={(e) => void sendV5Invite(e)} noValidate>
                <fieldset disabled={busy}>
                  <legend>Invite Primary or Backup Guardian</legend>
                  <label>
                    Guardian account email
                    <input
                      required
                      type="email"
                      value={inviteEmail}
                      onChange={(e) => setInviteEmail(e.target.value)}
                      placeholder="guardian@example.com"
                    />
                  </label>
                  <div className="account-fields">
                    <label>
                      Relationship
                      <select
                        value={inviteRel}
                        onChange={(e) => setInviteRel(e.target.value as Relationship)}
                      >
                        {relationships.map((value) => (
                          <option key={value} value={value}>
                            {value}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Guardian slot
                      <select
                        value={inviteSlot}
                        onChange={(e) => setInviteSlot(e.target.value as "primary" | "backup")}
                      >
                        <option value="primary">Primary guardian</option>
                        <option value="backup">Backup guardian</option>
                      </select>
                    </label>
                    <label>
                      Alert channel
                      <select
                        value={inviteChannel}
                        onChange={(e) =>
                          setInviteChannel(e.target.value as "in_app" | "email" | "push" | "sms")
                        }
                      >
                        <option value="in_app">In-app</option>
                        <option value="email">Email</option>
                        <option value="push">Push (stub)</option>
                        <option value="sms">SMS (stub)</option>
                      </select>
                    </label>
                  </div>
                  <label className="check-row toggle-tile">
                    <input
                      type="checkbox"
                      checked={consent}
                      onChange={(e) => setConsent(e.target.checked)}
                    />
                    <span>
                      I consent to sending redacted review requests (no amounts/recipients) after
                      guardian acceptance.
                    </span>
                  </label>
                </fieldset>
                <button className="primary" type="submit" disabled={busy}>
                  Send durable invitation
                </button>
              </form>
            )}
          </article>

          {error && (
            <p role="alert" className="notice">
              {error}
            </p>
          )}
          {message && (
            <p role="status" className="form-note status-banner">
              {message}
            </p>
          )}
          <div className="actions">
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => void loadV5State()}
            >
              {busy ? "Refreshing…" : "Refresh status"}
            </button>
          </div>
        </section>

        {privacyContractCard}
      </div>
    );
  }

  const current = items?.[0];
  const occupied = current?.status === "Pending" || current?.status === "Accepted";

  return (
    <div className="enrollment-split-layout">
      <section className="card account-card enrollment-card">
        <div className="composer-top">
          <div>
            <p className="eyebrow">{payer ? "Payment protection" : "Guardian consent"}</p>
            <h2>{payer ? "Guardian enrollment" : "Guardian invitations"}</h2>
            <p className="card-lead">
              Connect someone you trust for an optional second look on high-risk transfers.
            </p>
          </div>
        </div>

        <div className="enrollment-stepper-visual" aria-hidden="true">
          <div className="enrollment-step active">
            <span className="step-circle">
              <Icon name="shieldCheck" size={14} />
            </span>
            <span>1. Invite Guardian</span>
          </div>
          <div className="step-connector" />
          <div className={`enrollment-step ${occupied ? "active" : ""}`}>
            <span className="step-circle">
              <Icon name="clock" size={14} />
            </span>
            <span>2. Explicit Consent</span>
          </div>
          <div className="step-connector" />
          <div className={`enrollment-step ${current?.status === "Accepted" ? "active" : ""}`}>
            <span className="step-circle">
              <Icon name="check" size={14} />
            </span>
            <span>3. Active Protection</span>
          </div>
        </div>

        {items === undefined && !error && <p role="status">Loading enrollment…</p>}
        {items?.length === 0 && (
          <div className="empty-enrollment-state">
            <Icon name="users" size={22} />
            <p>{payer ? "No guardian enrolled." : "No invitations for this demo identity."}</p>
          </div>
        )}

        <div className="enrollment-list">
          {items?.map((item) => (
            <article key={item.id} className="enrollment-item">
              <div className="enrollment-title">
                <div className="guardian-person-head">
                  <span className="persona-avatar">{item.name.charAt(0).toUpperCase()}</span>
                  <div>
                    <h3>{item.name}</h3>
                    <p className="field-help">{item.relationship}</p>
                  </div>
                </div>
                <span
                  className={`pill ${
                    item.status === "Accepted"
                      ? "mint"
                      : item.status === "Declined" || item.status === "Revoked"
                        ? "danger"
                        : "caution"
                  }`}
                >
                  {item.status}
                </span>
              </div>

              {payer && item.status === "Pending" && (
                <div className="invite-link">
                  <p>
                    Share this demo link with your trusted contact. They should sign in or register
                    using the fictional contact you entered.
                  </p>
                  <div className="invite-link-row">
                    <label>
                      Guardian invitation link
                      <input
                        readOnly
                        value={new URL("/guardian/enrollment", window.location.origin).href}
                        onFocus={(event) => event.target.select()}
                      />
                    </label>
                    <button
                      className="secondary copy-link-btn"
                      type="button"
                      onClick={() => {
                        void navigator.clipboard.writeText(
                          new URL("/guardian/enrollment", window.location.origin).href,
                        );
                        setCopiedLink(true);
                        setTimeout(() => setCopiedLink(false), 2000);
                      }}
                    >
                      <Icon name="copy" size={14} />
                      <span>{copiedLink ? "Copied" : "Copy"}</span>
                    </button>
                  </div>
                </div>
              )}

              {payer &&
                !profile.sample &&
                (item.status === "Pending" || item.status === "Accepted") && (
                  <button
                    className="secondary"
                    disabled={busy}
                    type="button"
                    onClick={() =>
                      void change({ action: "revoke", id: item.id }, "Guardian access revoked.")
                    }
                  >
                    {item.status === "Pending" ? "Cancel invitation" : "Revoke guardian access"}
                  </button>
                )}

              {!payer && !profile.sample && item.status === "Accepted" && (
                <button
                  className="secondary"
                  disabled={busy}
                  type="button"
                  onClick={() =>
                    void change({ action: "withdraw", id: item.id }, "Guardian consent withdrawn.")
                  }
                >
                  Withdraw guardian consent
                </button>
              )}

              {!payer && item.status === "Pending" && (
                <>
                  <label className="check-row toggle-tile">
                    <input
                      type="checkbox"
                      checked={acceptance.includes(item.id)}
                      onChange={(event) => {
                        const checked = event.target.checked;
                        setAcceptance((before) =>
                          checked ? [...before, item.id] : before.filter((id) => id !== item.id),
                        );
                      }}
                    />
                    <span>I agree to receive privacy-limited review requests from this payer.</span>
                  </label>
                  <div className="actions">
                    <button
                      className="primary"
                      type="button"
                      disabled={busy || !acceptance.includes(item.id)}
                      onClick={() =>
                        void change(
                          { action: "accept", id: item.id, consent: true },
                          "Invitation accepted.",
                        )
                      }
                    >
                      Accept invitation
                    </button>
                    <button
                      className="secondary"
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        void change({ action: "decline", id: item.id }, "Invitation declined.")
                      }
                    >
                      Decline invitation
                    </button>
                  </div>
                </>
              )}
            </article>
          ))}
        </div>

        {payer && profile.sample && (
          <p className="form-note">
            The walkthrough uses a pre-enrolled sample pair. Create your own payer account to test
            custom invitations and revocation.
          </p>
        )}

        {payer && !profile.sample && items && !occupied && (
          <div className="invite-composer-wrap">
            <label className="check-row toggle-tile">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => {
                  setEnabled(event.target.checked);
                  if (!event.target.checked) setConsent(false);
                }}
              />
              <span>I want to invite a trusted guardian</span>
            </label>
            {enabled && (
              <form className="account-form" noValidate onSubmit={invite}>
                <fieldset disabled={busy}>
                  <legend>Trusted guardian details</legend>
                  <div className="account-fields">
                    <label>
                      Guardian name
                      <input
                        required
                        maxLength={64}
                        value={name}
                        onChange={(event) => setName(event.target.value)}
                      />
                    </label>
                    <label>
                      Relationship
                      <select
                        required
                        value={relationship}
                        onChange={(event) => setRelationship(event.target.value as Relationship)}
                      >
                        <option value="">Choose a relationship</option>
                        {relationships.map((value) => (
                          <option key={value}>{value}</option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <label>
                    Guardian demo email or mobile
                    <input
                      required
                      maxLength={90}
                      value={contact}
                      autoComplete="off"
                      placeholder="name@gmail.com or 9876543210"
                      onChange={(event) => setContact(event.target.value)}
                    />
                  </label>
                  <p className="field-help">
                    Standard email or 10-digit Indian mobile. Ownership is unverified in demo.
                  </p>
                  <label className="check-row toggle-tile">
                    <input
                      type="checkbox"
                      checked={consent}
                      onChange={(event) => setConsent(event.target.checked)}
                    />
                    <span>
                      I consent to sharing the limited review details after this guardian accepts.
                    </span>
                  </label>
                </fieldset>
                <button className="primary" type="submit" disabled={busy}>
                  Send demo invitation
                </button>
              </form>
            )}
          </div>
        )}

        {error && (
          <p role="alert" className="notice">
            {error}
          </p>
        )}
        {message && (
          <p role="status" className="form-note status-banner">
            {message}
          </p>
        )}
        <div className="actions">
          <button
            type="button"
            className="secondary"
            disabled={busy || (!items && !error)}
            onClick={() => void change()}
          >
            {busy ? "Updating…" : "Refresh invitation status"}
          </button>
        </div>
      </section>

      {privacyContractCard}
    </div>
  );
}
