import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { defaultReviewDuration } from "../../mocks/reviewPreference.ts";
import { beneficiaries, purposes, scenarios } from "../../mocks/scenarios.ts";
import { Icon } from "../components/Icon.tsx";
import { PaymentStatus } from "../components/PaymentStatus.tsx";
import { accountApi, AccountError } from "../services/accountApi.ts";
import {
  adminCreatePayment,
  adminMockApi,
  AdminApiError,
  loadRazorpayCheckoutScript,
  paymentError,
  policyLabApi,
  razorpayApi,
  validateRazorpayTestKey,
} from "../services/adminApi.ts";
import type {
  PolicyLabSimulationResult,
  RazorpayOrderResult,
  RazorpayVerifyResult,
} from "../services/adminApi.ts";
import { decimalRupees, formatRupees, toPaise } from "../services/demoSession.ts";
import type { DemoSession } from "../types/account.ts";
import { razorpayRequiredEndpoints } from "../types/admin.ts";
import type {
  AdminAuditEntry,
  AdminTestMode,
  AuditVerifyResult,
  RazorpayConfigResult,
  RazorpayOrderStatusResult,
} from "../types/admin.ts";
import type { PayerPayment } from "../types/payment.ts";

type DemoScenario = (typeof scenarios)[number];

const scenarioTitles: Record<DemoScenario["title"], string> = {
  everyday: "Everyday purchase",
  unfamiliar: "Unfamiliar supplier",
  coerced: "Coerced KYC transfer",
  flagged: "Flagged recipient",
};

// ─── Admin Login (/admin/login) ───────────────────────────────────────────────

export function AdminLogin({
  onSession,
  expired,
  registrationBlocked = false,
}: {
  onSession: (session: DemoSession) => void;
  expired: boolean;
  registrationBlocked?: boolean;
}) {
  const [contact, setContact] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const session = await accountApi.login("admin", contact.trim());
      onSession(session);
    } catch (err) {
      setError(
        err instanceof AccountError
          ? err.message
          : "Could not sign in. Check the demo service and retry.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function trySample() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const session = await accountApi.login("admin", "", true);
      onSession(session);
    } catch (err) {
      setError(
        err instanceof AccountError
          ? err.message
          : "Could not load sample admin. Check the demo service and retry.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-stage admin-auth-stage">
      <div className="auth-ambient" aria-hidden="true">
        <span className="auth-sculpt-bar auth-sculpt-left" />
        <span className="auth-sculpt-bar auth-sculpt-right" />
      </div>
      <section
        className="card workspace-card admin-login-card"
        aria-labelledby="admin-login-heading"
      >
        <div className="admin-login-header">
          <div className="symbol caution">
            <Icon name="shieldAlert" />
          </div>
          <div>
            <p className="eyebrow">Admin access only · No public registration</p>
            <h1 id="admin-login-heading">Admin Payment Testing Portal</h1>
            <p className="card-lead">
              Sign in with a provisioned demo admin identity to test Mock UPI interventions and
              preview the Razorpay sandbox integration.
            </p>
          </div>
        </div>

        {registrationBlocked && (
          <div className="notice" role="alert">
            <p>
              Public admin registration is disabled. Use the provisioned demo admin credentials to
              sign in.
            </p>
          </div>
        )}

        {expired && (
          <div className="notice" role="alert">
            <p>Your admin session expired. Sign in again to continue.</p>
          </div>
        )}

        <form onSubmit={(e) => void submit(e)} className="admin-login-form">
          <div className="form-field">
            <label>
              Provisioned admin email
              <input
                type="text"
                autoComplete="username"
                placeholder="admin@pauseguard.test"
                value={contact}
                onChange={(e) => setContact(e.target.value)}
                disabled={busy}
                required
              />
            </label>
          </div>

          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}

          <div className="actions">
            <button className="primary" type="submit" disabled={busy || !contact.trim()}>
              {busy ? (
                <>
                  <span className="spinner" aria-hidden="true" /> Signing in…
                </>
              ) : (
                <>
                  <Icon name="shield" size={16} /> Sign in as admin
                </>
              )}
            </button>
            <button
              className="secondary"
              type="button"
              disabled={busy}
              onClick={() => void trySample()}
            >
              Open sample admin
            </button>
            <a className="text-button" href="/">
              Return to homepage
            </a>
          </div>
        </form>

        <div className="admin-login-meta">
          <span className="pill neutral">
            <Icon name="lock" size={13} /> Provisioned demo identity:{" "}
            <code>admin@pauseguard.test</code>
          </span>
          <span className="pill neutral">Server-enforced role boundary</span>
        </div>
      </section>
    </div>
  );
}

// ─── Mode A — Mock UPI Testing Panel ──────────────────────────────────────────

type MockUpiPhase = "configure" | "running";

function MockUpiPanel({ token, accountId }: { token: string; accountId: string }) {
  const [phase, setPhase] = useState<MockUpiPhase>("configure");
  const [paymentId, setPaymentId] = useState<string>();
  const [syntheticSession, setSyntheticSession] = useState<DemoSession>();
  const [syntheticSafeLock, setSyntheticSafeLock] = useState(false);
  const [contextBusy, setContextBusy] = useState(false);

  // Test payment builder state
  const [selectedScenario, setSelectedScenario] = useState<DemoScenario | null>(scenarios[2]);
  const [beneficiary, setBeneficiary] = useState<string>(scenarios[2].beneficiary);
  const [amount, setAmount] = useState<string>(scenarios[2].amount);
  const [purpose, setPurpose] = useState<string>(scenarios[2].purpose);
  const [invalidAmount, setInvalidAmount] = useState(false);
  const [busy, setBusy] = useState(false);
  const [runError, setRunError] = useState("");

  // Audit evidence state
  const [auditPayment, setAuditPayment] = useState<PayerPayment | null>(null);
  const [auditEvents, setAuditEvents] = useState<AdminAuditEntry[]>([]);
  const [auditVerify, setAuditVerify] = useState<AuditVerifyResult | null>(null);
  const [auditError, setAuditError] = useState("");
  const [recentTests, setRecentTests] = useState<PayerPayment[]>([]);

  const fetchAuditData = useCallback(
    async (targetPaymentId?: string) => {
      const [auditRes, verifyRes] = await Promise.all([
        adminMockApi.getAudit(token, targetPaymentId),
        adminMockApi.verifyAuditChain(token),
      ]);
      return { auditRes, verifyRes };
    },
    [token],
  );

  const loadAudit = useCallback(
    async (targetPaymentId?: string) => {
      try {
        setAuditError("");
        const { auditRes, verifyRes } = await fetchAuditData(targetPaymentId);
        setAuditVerify(verifyRes);
        if (targetPaymentId) {
          setAuditPayment(auditRes.payments[0] ?? null);
          setAuditEvents(auditRes.events);
        } else {
          setRecentTests(auditRes.payments);
        }
      } catch (err) {
        setAuditError(
          err instanceof AccountError ? err.message : "Unable to load mock audit evidence.",
        );
      }
    },
    [fetchAuditData],
  );

  useEffect(() => {
    let active = true;
    void fetchAuditData().then(
      ({ auditRes, verifyRes }) => {
        if (!active) return;
        setAuditError("");
        setAuditVerify(verifyRes);
        setRecentTests(auditRes.payments);
      },
      (err: unknown) => {
        if (!active) return;
        setAuditError(
          err instanceof AccountError ? err.message : "Unable to load mock audit evidence.",
        );
      },
    );
    return () => {
      active = false;
    };
  }, [fetchAuditData]);

  async function toggleSafeLock(nextValue: boolean) {
    if (contextBusy) return;
    setContextBusy(true);
    setRunError("");
    try {
      const nextSession = await adminMockApi.getSyntheticPayerSession(token, nextValue);
      setSyntheticSession(nextSession);
      setSyntheticSafeLock(nextSession.profile.safeLock);
    } catch (err) {
      setRunError(
        err instanceof AccountError ? err.message : "Could not update synthetic payer Safe-Lock.",
      );
    } finally {
      setContextBusy(false);
    }
  }

  function applyScenario(scenario: DemoScenario) {
    setSelectedScenario(scenario);
    setBeneficiary(scenario.beneficiary);
    setAmount(scenario.amount);
    setPurpose(scenario.purpose);
    setInvalidAmount(false);
    setRunError("");
  }

  async function runTest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const paise = toPaise(amount);
    if (!paise) {
      setInvalidAmount(true);
      return;
    }
    setInvalidAmount(false);
    setBusy(true);
    setRunError("");
    try {
      // Obtain or refresh an explicitly authorized synthetic payer session.
      // Admin tokens cannot call /api/v2/payments directly.
      const payerCtx =
        syntheticSession && syntheticSession.expiresAt > Date.now() + 30_000
          ? syntheticSession
          : await adminMockApi.getSyntheticPayerSession(token, syntheticSafeLock);
      setSyntheticSession(payerCtx);

      const idempotency_key = `admin-test:${accountId}:${Date.now()}`;
      const result = await adminCreatePayment(
        payerCtx.token,
        { beneficiary_id: beneficiary, amount_paise: paise, purpose, idempotency_key },
        defaultReviewDuration,
      );
      setPaymentId(result.payment.id);
      setPhase("running");
      await loadAudit(result.payment.id);
    } catch (err) {
      if (err instanceof AccountError) {
        setRunError(err.message);
      } else {
        const key = paymentError(err).key;
        setRunError(
          key === "accessError"
            ? "Synthetic payer context was rejected. Check that the local mock service is running."
            : `Test payment failed (${key}). Check the inputs and retry.`,
        );
      }
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setPaymentId(undefined);
    setAuditPayment(null);
    setAuditEvents([]);
    setPhase("configure");
    setRunError("");
    void loadAudit();
  }

  const parsedPaise = toPaise(amount) ?? 0;

  if (phase === "running" && paymentId && syntheticSession) {
    return (
      <div className="admin-test-running">
        <div className="admin-section-label">
          <span className="pill mint">
            <Icon name="activity" size={13} /> Canonical Mock UPI State
          </span>
          <span className="pill neutral">
            Synthetic Payer Context · {syntheticSession.profile.id}
          </span>
          {syntheticSafeLock && (
            <span className="pill danger">
              <Icon name="lock" size={13} /> Safe-Lock ON
            </span>
          )}
        </div>

        <PaymentStatus
          role="payer"
          token={syntheticSession.token}
          id={paymentId}
          locale="en"
          onClose={reset}
        />

        {/* Audit & Risk Evidence Card */}
        <section className="admin-audit-card" aria-label="Mock audit evidence and risk evaluation">
          <div className="admin-audit-header">
            <div>
              <p className="eyebrow">Mock audit evidence · Synthetic</p>
              <h3>Risk Evaluation &amp; State Transitions</h3>
            </div>
            <button type="button" className="secondary" onClick={() => void loadAudit(paymentId)}>
              Refresh evidence
            </button>
          </div>

          {auditError && (
            <p className="field-error" role="alert">
              {auditError}
            </p>
          )}

          {auditPayment && (
            <dl className="payment-details admin-audit-metrics">
              <div>
                <dt>Authoritative Status</dt>
                <dd>
                  <code>{auditPayment.status}</code>
                </dd>
              </div>
              <div>
                <dt>Tier &amp; Risk Score</dt>
                <dd>
                  Tier {auditPayment.tier} · Score {auditPayment.risk_score}/100
                </dd>
              </div>
              <div>
                <dt>Version &amp; Amount</dt>
                <dd>
                  v{auditPayment.version} · {auditPayment.amount_paise} paise
                </dd>
              </div>
            </dl>
          )}

          {auditPayment && (
            <div className="admin-reason-row">
              <span className="admin-reason-label">Reason codes:</span>
              {auditPayment.reason_codes.length > 0 ? (
                auditPayment.reason_codes.map((code) => (
                  <code key={code} className="admin-code-chip">
                    {code}
                  </code>
                ))
              ) : (
                <span className="field-help">None triggered</span>
              )}
            </div>
          )}

          {auditVerify && (
            <div className="admin-hash-status">
              <span className={`pill ${auditVerify.valid ? "mint" : "danger"}`}>
                <Icon name={auditVerify.valid ? "checkCircle" : "alertTriangle"} size={13} />
                {auditVerify.valid ? "Hash chain verified" : "Hash mismatch"}
              </span>
              <span className="field-help">
                {auditVerify.total_events} total mock events · Head:{" "}
                <code>{auditVerify.head_hash.slice(0, 12)}…</code>
              </span>
            </div>
          )}

          {auditEvents.length > 0 && (
            <ol className="admin-audit-timeline">
              {auditEvents.map((ev) => (
                <li key={ev.seq} className="admin-audit-event">
                  <div className="admin-event-top">
                    <span className="pill neutral">
                      #{ev.seq} · {ev.event}
                    </span>
                    <code>
                      {ev.fromStatus ?? "INIT"} → {ev.toStatus} (v{ev.version})
                    </code>
                  </div>
                  <div className="admin-event-meta">
                    <span>Actor: {ev.actorRole}</span>
                    <span>
                      Hash: <code>{ev.hash.slice(0, 14)}…</code>
                    </span>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </section>

        <div className="actions">
          <button className="secondary" type="button" onClick={reset}>
            <Icon name="zap" size={16} /> Back to test builder
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-mode-panel">
      <div className="admin-section-label">
        <p className="admin-mode-desc">
          Run synthetic payments through PauseGuard's canonical <code>/api/v2/payments</code> engine
          using an isolated synthetic payer context. Guardian review, Safe-Lock, warnings, and
          separate payer confirmation rules remain enforced.
        </p>
      </div>

      {/* Synthetic Payer Isolation & Safe-Lock Toggle */}
      <div className="admin-context-bar">
        <div className="admin-context-info">
          <span className="pill neutral">
            <Icon name="shield" size={13} /> Context: <code>admin-synthetic-payer</code>
          </span>
          <span className="field-help">
            Admin token cannot call payer endpoints directly or view other users' payments.
          </span>
        </div>
        <button
          type="button"
          className={syntheticSafeLock ? "reject" : "secondary"}
          aria-pressed={syntheticSafeLock}
          disabled={contextBusy}
          onClick={() => void toggleSafeLock(!syntheticSafeLock)}
        >
          <Icon name={syntheticSafeLock ? "lock" : "unlock"} size={15} />
          <span>Safe-Lock: {syntheticSafeLock ? "ON (Blocks test)" : "OFF"}</span>
        </button>
      </div>

      {/* Scenario selector */}
      <div className="scenarios">
        <h2>Quick risk scenarios</h2>
        <div className="scenario-list">
          {scenarios.map((scenario) => (
            <button
              key={scenario.title}
              type="button"
              className="scenario"
              aria-pressed={selectedScenario?.title === scenario.title}
              onClick={() => applyScenario(scenario)}
            >
              <span
                className={`pill ${scenario.tag === "blocked" ? "danger" : scenario.tag === "guardianReview" || scenario.tag === "warning" ? "caution" : "mint"}`}
              >
                {scenario.tag === "guardianReview" ? "Guardian review" : scenario.tag}
              </span>
              <strong>{scenarioTitles[scenario.title]}</strong>
            </button>
          ))}
        </div>
      </div>

      {/* Custom configuration form */}
      <form onSubmit={(e) => void runTest(e)} className="admin-test-form">
        <div className="form-fields">
          <div className="form-field">
            <label>
              Beneficiary
              <select
                value={beneficiary}
                onChange={(e) => {
                  setBeneficiary(e.target.value);
                  setSelectedScenario(null);
                }}
              >
                {Object.entries(beneficiaries).map(([id, name]) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="form-field">
            <label>
              Purpose
              <select
                value={purpose}
                onChange={(e) => {
                  setPurpose(e.target.value);
                  setSelectedScenario(null);
                }}
              >
                {Object.entries(purposes).map(([id, label]) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="form-field full">
            <label htmlFor="admin-amount-input">Amount (INR)</label>
            <div className={`amount-field${invalidAmount ? " field-invalid" : ""}`}>
              <span aria-hidden="true">₹</span>
              <input
                id="admin-amount-input"
                type="text"
                inputMode="decimal"
                aria-invalid={invalidAmount}
                placeholder="0.00"
                value={amount}
                onChange={(e) => {
                  setAmount(e.target.value);
                  setInvalidAmount(false);
                  setSelectedScenario(null);
                }}
                disabled={busy}
              />
            </div>
            {invalidAmount && (
              <span className="field-error" role="alert">
                Enter a positive rupee amount with up to two decimal places.
              </span>
            )}
          </div>
        </div>

        {runError && (
          <p className="field-error" role="alert">
            {runError}
          </p>
        )}

        <div className="actions">
          <button className="primary" type="submit" disabled={busy}>
            {busy ? (
              <>
                <span className="spinner" aria-hidden="true" /> Creating synthetic payment…
              </>
            ) : (
              <>
                <Icon name="zap" size={16} /> Create synthetic test payment
              </>
            )}
          </button>
        </div>
      </form>

      {/* Payload preview */}
      <dl className="payment-details admin-preview-summary">
        <div>
          <dt>Amount (integer paise)</dt>
          <dd>
            {parsedPaise > 0
              ? `${formatRupees(parsedPaise)} (${parsedPaise})`
              : `₹${decimalRupees(0)} (0)`}
          </dd>
        </div>
        <div>
          <dt>Beneficiary ID</dt>
          <dd>{beneficiaries[beneficiary as keyof typeof beneficiaries] ?? beneficiary}</dd>
        </div>
        <div>
          <dt>Purpose</dt>
          <dd>{purposes[purpose as keyof typeof purposes] ?? purpose}</dd>
        </div>
      </dl>

      {/* Recent synthetic tests table */}
      {recentTests.length > 0 && (
        <section className="admin-recent-section" aria-label="Recent synthetic test runs">
          <h3>Recent synthetic test runs ({recentTests.length})</h3>
          <ul className="admin-recent-list">
            {recentTests.slice(0, 5).map((item) => (
              <li key={item.id} className="admin-recent-item">
                <div>
                  <code>{item.id}</code>
                  <span className="field-help">
                    {formatRupees(item.amount_paise)} · Tier {item.tier} · Score {item.risk_score}
                  </span>
                </div>
                <span
                  className={`pill ${item.status === "EXECUTED" ? "mint" : item.status === "REJECTED" || item.status === "CANCELLED" ? "danger" : "caution"}`}
                >
                  {item.status}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

// ─── Mode B — Razorpay Test Mode Panel ────────────────────────────────────────

type RazorpayCheckoutLifecycle =
  | "idle"
  | "creating"
  | "ready_for_checkout"
  | "opening_checkout"
  | "verifying"
  | "verified"
  | "cancelled"
  | "failed";

interface RazorpayCheckoutSuccessPayload {
  razorpay_payment_id: string;
  razorpay_order_id?: string;
  razorpay_signature: string;
}

interface RazorpayCheckoutInstance {
  open: () => void;
  on?: (
    event: string,
    cb: (payload: { error?: { description?: string; reason?: string; code?: string } }) => void,
  ) => void;
}

type RazorpayCheckoutCtor = new (options: Record<string, unknown>) => RazorpayCheckoutInstance;

function createIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `rzp-idem-${crypto.randomUUID()}`;
  }
  return `rzp-idem-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function RazorpayPanel({
  token,
  accountId,
  onStatusChange,
}: {
  token: string;
  accountId: string;
  onStatusChange?: (status: "checking" | "ready" | "unavailable") => void;
}) {
  const [configState, setConfigState] = useState<"checking" | "ready" | "unavailable">("checking");
  const [config, setConfig] = useState<RazorpayConfigResult | null>(null);
  const [configError, setConfigError] = useState("");

  const [amount, setAmount] = useState("500.00");
  const [receipt, setReceipt] = useState("");
  const [notesPurpose, setNotesPurpose] = useState("merchant_checkout_test");
  const [orderIdempotencyKey, setOrderIdempotencyKey] = useState<string>(() =>
    createIdempotencyKey(),
  );

  const [lookupOrderId, setLookupOrderId] = useState("");
  const [currentOrder, setCurrentOrder] = useState<RazorpayOrderResult | null>(null);
  const [orderStatus, setOrderStatus] = useState<RazorpayOrderStatusResult | null>(null);
  const [verifyResult, setVerifyResult] = useState<RazorpayVerifyResult | null>(null);
  const [recentOrders, setRecentOrders] = useState<RazorpayOrderStatusResult[]>([]);

  const [lifecycle, setLifecycle] = useState<RazorpayCheckoutLifecycle>("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const [statusMsg, setStatusMsg] = useState("");

  const [manualPaymentId, setManualPaymentId] = useState("");
  const [manualSignature, setManualSignature] = useState("");

  const fetchValidatedConfig = useCallback(async (): Promise<RazorpayConfigResult> => {
    const cfg = await razorpayApi.getConfig(token);
    validateRazorpayTestKey(cfg.key_id);
    return cfg;
  }, [token]);

  const applyConfigSuccess = useCallback(
    (cfg: RazorpayConfigResult) => {
      setConfigError("");
      setConfig(cfg);
      setConfigState("ready");
      onStatusChange?.("ready");
    },
    [onStatusChange],
  );

  const applyConfigError = useCallback(
    (err: unknown) => {
      setConfig(null);
      setConfigState("unavailable");
      onStatusChange?.("unavailable");
      if (err instanceof AccountError || err instanceof AdminApiError) {
        setConfigError(err.message);
      } else {
        setConfigError("Razorpay Test Mode sandbox is unavailable.");
      }
    },
    [onStatusChange],
  );

  const refreshConfig = useCallback(async () => {
    setConfigState("checking");
    onStatusChange?.("checking");
    setConfigError("");
    try {
      const cfg = await fetchValidatedConfig();
      applyConfigSuccess(cfg);
    } catch (err) {
      applyConfigError(err);
    }
  }, [fetchValidatedConfig, applyConfigSuccess, applyConfigError, onStatusChange]);

  useEffect(() => {
    let active = true;
    void fetchValidatedConfig().then(
      (cfg) => {
        if (active) applyConfigSuccess(cfg);
      },
      (err: unknown) => {
        if (active) applyConfigError(err);
      },
    );
    return () => {
      active = false;
    };
  }, [fetchValidatedConfig, applyConfigSuccess, applyConfigError]);

  const amountPaise = toPaise(amount);

  const recordOrderHistory = useCallback((snapshot: RazorpayOrderStatusResult) => {
    setRecentOrders((prev) => {
      const filtered = prev.filter((item) => item.razorpay_order_id !== snapshot.razorpay_order_id);
      return [snapshot, ...filtered].slice(0, 5);
    });
  }, []);

  const inspectOrder = useCallback(
    async (targetOrderId: string) => {
      const trimmed = targetOrderId.trim();
      if (!trimmed) return;
      setErrorMsg("");
      try {
        const status = await razorpayApi.getOrderStatus(token, trimmed);
        setOrderStatus(status);
        setLookupOrderId(status.razorpay_order_id);
        recordOrderHistory(status);
        return status;
      } catch (err) {
        const message =
          err instanceof AccountError || err instanceof AdminApiError
            ? err.message
            : "Could not retrieve Razorpay order status.";
        setErrorMsg(message);
        return undefined;
      }
    },
    [token, recordOrderHistory],
  );

  const submitVerification = useCallback(
    async (payload: {
      razorpay_order_id: string;
      razorpay_payment_id: string;
      razorpay_signature: string;
    }) => {
      setLifecycle("verifying");
      setErrorMsg("");
      setStatusMsg("Verifying HMAC signature and reconciling with Razorpay provider...");
      try {
        const verified = await razorpayApi.verifyPayment(token, payload);
        if (!verified.verified || !verified.reconciled_with_provider) {
          setVerifyResult(null);
          setLifecycle("failed");
          setErrorMsg("Backend verification returned unverified status. Payment is not complete.");
          setStatusMsg("");
          return;
        }
        setVerifyResult(verified);
        setLifecycle("verified");
        setStatusMsg("Signature verified via backend HMAC and reconciled with Razorpay Test Mode.");
        await inspectOrder(verified.razorpay_order_id);
      } catch (err) {
        setVerifyResult(null);
        setLifecycle("failed");
        setStatusMsg("");
        setErrorMsg(
          err instanceof AccountError || err instanceof AdminApiError
            ? err.message
            : "Backend HMAC signature verification failed.",
        );
      }
    },
    [token, inspectOrder],
  );

  async function handleCreateOrder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (configState !== "ready" || !config) return;
    if (amountPaise === null) {
      setErrorMsg("Enter a valid positive INR amount (e.g., 500.00) before creating a test order.");
      return;
    }
    setLifecycle("creating");
    setErrorMsg("");
    setStatusMsg("Creating isolated Razorpay Test Mode order...");
    setVerifyResult(null);
    try {
      const created = await razorpayApi.createOrder(token, amountPaise, {
        receipt: receipt.trim() || undefined,
        notes: notesPurpose.trim()
          ? { purpose: notesPurpose.trim(), admin_id: accountId, sandbox_mode: "test_only" }
          : { admin_id: accountId, sandbox_mode: "test_only" },
        idempotencyKey: orderIdempotencyKey,
      });
      validateRazorpayTestKey(created.key_id);
      setCurrentOrder(created);
      setLookupOrderId(created.razorpay_order_id);
      setOrderStatus({
        id: created.id,
        razorpay_order_id: created.razorpay_order_id,
        amount_paise: created.amount_paise,
        currency: created.currency,
        status: created.status,
        receipt: created.receipt,
        key_id: created.key_id,
        created_at: created.created_at,
        payments: [],
      });
      recordOrderHistory({
        id: created.id,
        razorpay_order_id: created.razorpay_order_id,
        amount_paise: created.amount_paise,
        currency: created.currency,
        status: created.status,
        receipt: created.receipt,
        key_id: created.key_id,
        created_at: created.created_at,
        payments: [],
      });
      setOrderIdempotencyKey(createIdempotencyKey());
      setLifecycle("ready_for_checkout");
      setStatusMsg("Test order created on backend. Launch Razorpay Test Checkout to continue.");
    } catch (err) {
      setLifecycle("failed");
      setStatusMsg("");
      setErrorMsg(
        err instanceof AccountError || err instanceof AdminApiError
          ? err.message
          : "Could not create Razorpay test order.",
      );
    }
  }

  async function openCheckout() {
    if (configState !== "ready" || !currentOrder || !config) return;
    let activeKey: string;
    try {
      activeKey = validateRazorpayTestKey(currentOrder.key_id || config.key_id);
    } catch (err) {
      setLifecycle("failed");
      setErrorMsg(err instanceof AdminApiError ? err.message : "Invalid Razorpay test key.");
      return;
    }

    setLifecycle("opening_checkout");
    setErrorMsg("");
    setStatusMsg("Loading Razorpay Test Checkout SDK...");
    try {
      await loadRazorpayCheckoutScript();
      const win = window as unknown as { Razorpay?: RazorpayCheckoutCtor };
      if (typeof win.Razorpay !== "function") {
        throw new AdminApiError("Razorpay Checkout constructor unavailable after script load.");
      }

      const instance = new win.Razorpay({
        key: activeKey,
        amount: currentOrder.amount_paise,
        currency: currentOrder.currency,
        name: "PauseGuard Merchant Sandbox",
        description: "TEST ONLY · Isolated from P2P UPI Ledger",
        order_id: currentOrder.razorpay_order_id,
        notes: {
          purpose: notesPurpose.trim() || "merchant_checkout_test",
          sandbox_mode: "test_only",
        },
        theme: { color: "#10b981" },
        modal: {
          ondismiss: () => {
            setLifecycle("cancelled");
            setStatusMsg("Checkout dismissed before completion. Backend order remains unverified.");
          },
        },
        handler: async (callbackPayload: RazorpayCheckoutSuccessPayload) => {
          setStatusMsg("Checkout callback received. Forwarding signature to backend...");
          await submitVerification({
            razorpay_order_id: callbackPayload.razorpay_order_id || currentOrder.razorpay_order_id,
            razorpay_payment_id: callbackPayload.razorpay_payment_id,
            razorpay_signature: callbackPayload.razorpay_signature,
          });
        },
      });

      instance.on?.("payment.failed", (failureEvent) => {
        const desc =
          failureEvent?.error?.description ||
          failureEvent?.error?.reason ||
          "Razorpay Test Checkout reported payment failure.";
        setLifecycle("failed");
        setStatusMsg("");
        setErrorMsg(`Checkout failed: ${desc}`);
      });

      setStatusMsg("Razorpay Test Checkout opened. Complete or dismiss the modal to proceed.");
      instance.open();
    } catch (err) {
      setLifecycle("failed");
      setStatusMsg("");
      setErrorMsg(
        err instanceof AdminApiError || err instanceof AccountError
          ? err.message
          : "Could not launch Razorpay Test Checkout.",
      );
    }
  }

  async function handleManualVerify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!currentOrder) return;
    if (!manualPaymentId.trim() || !manualSignature.trim()) {
      setErrorMsg("Enter both razorpay_payment_id and 64-character HMAC signature to verify.");
      return;
    }
    await submitVerification({
      razorpay_order_id: currentOrder.razorpay_order_id,
      razorpay_payment_id: manualPaymentId.trim(),
      razorpay_signature: manualSignature.trim(),
    });
  }

  const busy =
    lifecycle === "creating" || lifecycle === "opening_checkout" || lifecycle === "verifying";
  const effectiveStatus =
    orderStatus?.status ?? verifyResult?.status ?? currentOrder?.status ?? "not_created";
  const verifiedBadge = verifyResult?.verified && verifyResult?.reconciled_with_provider;

  return (
    <div className="admin-mode-panel">
      {/* Status Banner */}
      <div className="admin-razorpay-unavailable">
        <div className="admin-section-label">
          {configState === "ready" ? (
            <>
              <span className="pill mint">
                <Icon name="checkCircle" size={13} /> TEST ONLY · Sandbox Active
              </span>
              <span className="pill neutral">ISOLATED MERCHANT FLOW · NO P2P LEDGER MUTATION</span>
            </>
          ) : configState === "checking" ? (
            <span className="pill neutral">
              <Icon name="clock" size={13} /> TEST ONLY · Checking backend config…
            </span>
          ) : (
            <>
              <span className="pill caution">
                <Icon name="alertTriangle" size={13} /> TEST ONLY · Backend Disabled / Unavailable
              </span>
              <span className="pill neutral">FAIL-CLOSED</span>
            </>
          )}
          <button
            type="button"
            className="text-button"
            onClick={() => void refreshConfig()}
            disabled={configState === "checking" || busy}
          >
            Refresh status
          </button>
        </div>
        <p className="admin-mode-desc">
          Admin-only Razorpay Test Mode merchant sandbox. Uses backend-supplied{" "}
          <code>rzp_test_*</code> keys only, verifies HMAC-SHA256 signatures server-side, and never
          authorizes or modifies PauseGuard Mock UPI transfers.
        </p>
        {configError && (
          <div className="notice" role="alert">
            <span>{configError}</span>
          </div>
        )}
      </div>

      {/* Order Creation Form */}
      <form className="card" onSubmit={handleCreateOrder}>
        <div className="card-header">
          <div className="symbol">
            <Icon name="zap" />
          </div>
          <div className="grow">
            <p className="eyebrow">Step 1 · Server-side merchant order</p>
            <h2>Create Razorpay Test Order</h2>
          </div>
          <span className="pill neutral">Admin: {accountId}</span>
        </div>

        <div className="form-fields" style={{ marginTop: ".75rem" }}>
          <label className="field">
            <span>Amount (INR)</span>
            <input
              type="text"
              inputMode="decimal"
              value={amount}
              onChange={(e) => {
                setAmount(e.target.value);
                setOrderIdempotencyKey(createIdempotencyKey());
              }}
              placeholder="500.00"
              disabled={configState !== "ready" || busy}
            />
            <small className="form-note">
              Integer amount_paise:{" "}
              {amountPaise !== null
                ? `${amountPaise.toLocaleString("en-IN")} paise`
                : "Invalid amount"}
            </small>
          </label>

          <label className="field">
            <span>Receipt reference (optional)</span>
            <input
              type="text"
              value={receipt}
              onChange={(e) => {
                setReceipt(e.target.value);
                setOrderIdempotencyKey(createIdempotencyKey());
              }}
              placeholder="rcpt_admin_test_001"
              maxLength={128}
              disabled={configState !== "ready" || busy}
            />
          </label>

          <label className="field">
            <span>Merchant test note</span>
            <input
              type="text"
              value={notesPurpose}
              onChange={(e) => {
                setNotesPurpose(e.target.value);
                setOrderIdempotencyKey(createIdempotencyKey());
              }}
              placeholder="merchant_checkout_test"
              disabled={configState !== "ready" || busy}
            />
          </label>
        </div>

        <div className="actions" style={{ marginTop: "1rem" }}>
          <button
            className="primary"
            type="submit"
            disabled={configState !== "ready" || amountPaise === null || busy}
          >
            <Icon name="zap" size={16} />
            {lifecycle === "creating" ? "Creating order…" : "Create Test Order"}
          </button>
          <span className="form-note">
            Idempotency key: <code>{orderIdempotencyKey}</code>
          </span>
        </div>
      </form>

      {/* Active Order Checkout & Server Verification */}
      <div className="card admin-razorpay-preview">
        <div className="card-header">
          <div className={`symbol ${verifiedBadge ? "mint" : "caution"}`}>
            <Icon name={verifiedBadge ? "shieldCheck" : "lock"} />
          </div>
          <div className="grow">
            <p className="eyebrow">Step 2 &amp; 3 · Checkout &amp; server HMAC reconciliation</p>
            <h2>Razorpay Merchant Test Checkout</h2>
          </div>
          {verifiedBadge ? (
            <span className="pill mint">Verified &amp; Reconciled</span>
          ) : currentOrder ? (
            <span className="pill caution">{effectiveStatus.toUpperCase()}</span>
          ) : (
            <span className="pill neutral">No active order</span>
          )}
        </div>

        <dl className="payment-details admin-razorpay-fields">
          <div>
            <dt>Razorpay Order ID</dt>
            <dd>
              <code>{currentOrder?.razorpay_order_id ?? "— (create order first)"}</code>
            </dd>
          </div>
          <div>
            <dt>Razorpay Payment ID</dt>
            <dd>
              <code>
                {verifyResult?.razorpay_payment_id ??
                  orderStatus?.payments?.[0]?.id ??
                  "— (pending callback)"}
              </code>
            </dd>
          </div>
          <div>
            <dt>Amount &amp; Currency</dt>
            <dd>
              {currentOrder
                ? `${formatRupees(currentOrder.amount_paise)} · ${currentOrder.currency} (${currentOrder.amount_paise} paise)`
                : "₹0.00 · INR (0 paise)"}
            </dd>
          </div>
          <div>
            <dt>Signature Verification</dt>
            <dd>
              {verifiedBadge
                ? "Verified (HMAC-SHA256 & Reconciled)"
                : lifecycle === "failed"
                  ? "Verification failed / unverified"
                  : "Server-side HMAC required"}
            </dd>
          </div>
          <div>
            <dt>Reconciliation Status</dt>
            <dd>
              {orderStatus
                ? `${orderStatus.status} (${orderStatus.payments.length} payment record${orderStatus.payments.length === 1 ? "" : "s"})`
                : "Pending"}
            </dd>
          </div>
          <div>
            <dt>Public Test Key</dt>
            <dd>
              <code>{currentOrder?.key_id ?? config?.key_id ?? "Unavailable"}</code>
            </dd>
          </div>
        </dl>

        {statusMsg && (
          <div className="admin-hash-status" role="status" style={{ marginTop: ".75rem" }}>
            <span className={`pill ${verifiedBadge ? "mint" : "neutral"}`}>
              <Icon name={verifiedBadge ? "checkCircle" : "info"} size={13} />
              {verifiedBadge ? "Verified" : "Status"}
            </span>
            <span className="field-help">{statusMsg}</span>
          </div>
        )}

        {errorMsg && (
          <div className="notice" role="alert">
            <span>{errorMsg}</span>
          </div>
        )}

        <div className="actions" style={{ marginTop: "1rem" }}>
          <button
            className="primary"
            type="button"
            disabled={configState !== "ready" || !currentOrder || busy}
            onClick={() => void openCheckout()}
          >
            <Icon name="external" size={16} />
            {lifecycle === "opening_checkout"
              ? "Opening Checkout…"
              : lifecycle === "verifying"
                ? "Verifying Signature…"
                : "Open Razorpay Test Checkout"}
          </button>

          {currentOrder && (
            <button
              className="secondary"
              type="button"
              disabled={busy}
              onClick={() => void inspectOrder(currentOrder.razorpay_order_id)}
            >
              Refresh Order Status
            </button>
          )}
        </div>

        <details style={{ marginTop: "1rem" }}>
          <summary style={{ cursor: "pointer", fontSize: ".9rem", color: "var(--muted)" }}>
            Server HMAC Verification &amp; Signature Diagnostic (for offline / negative tests)
          </summary>
          <form
            onSubmit={handleManualVerify}
            className="form-fields"
            style={{ marginTop: ".75rem" }}
          >
            <label className="field">
              <span>Razorpay Payment ID</span>
              <input
                type="text"
                value={manualPaymentId}
                onChange={(e) => setManualPaymentId(e.target.value)}
                placeholder="pay_test_..."
                disabled={!currentOrder || busy}
              />
            </label>
            <label className="field">
              <span>HMAC-SHA256 Signature (64 hex chars)</span>
              <input
                type="text"
                value={manualSignature}
                onChange={(e) => setManualSignature(e.target.value)}
                placeholder="64-character signature from backend/checkout"
                disabled={!currentOrder || busy}
              />
            </label>
            <div className="actions" style={{ alignSelf: "end" }}>
              <button className="secondary" type="submit" disabled={!currentOrder || busy}>
                Verify Signature on Backend
              </button>
            </div>
          </form>
        </details>

        <p className="form-note" style={{ marginTop: ".75rem" }}>
          Security invariant: checkout never marks a payment verified from client-side callbacks
          alone.
          <code>key_secret</code> stays strictly on the FastAPI backend, and PauseGuard P2P/UPI
          state cannot be altered here.
        </p>
      </div>

      {/* Order Lookup & History */}
      <div className="card">
        <div className="card-header">
          <div className="symbol">
            <Icon name="activity" />
          </div>
          <div className="grow">
            <p className="eyebrow">Order inspection &amp; history</p>
            <h2>Stored Merchant Order &amp; Payments</h2>
          </div>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void inspectOrder(lookupOrderId);
          }}
          className="actions"
          style={{ marginTop: ".75rem" }}
        >
          <input
            type="text"
            aria-label="Inspect Razorpay order ID"
            value={lookupOrderId}
            onChange={(e) => setLookupOrderId(e.target.value)}
            placeholder="order_... or rzp_ord_..."
            style={{ flex: "1 1 16rem" }}
          />
          <button className="secondary" type="submit" disabled={!lookupOrderId.trim() || busy}>
            Fetch Order Status
          </button>
        </form>

        {orderStatus && (
          <div style={{ marginTop: "1rem" }}>
            <p className="form-note">
              Order <code>{orderStatus.razorpay_order_id}</code> ({orderStatus.id}) · Status:{" "}
              <strong>{orderStatus.status}</strong> · {formatRupees(orderStatus.amount_paise)}
            </p>
            {orderStatus.payments.length === 0 ? (
              <p className="form-note" style={{ marginTop: ".35rem" }}>
                No captured payment records on this order yet.
              </p>
            ) : (
              <ul className="admin-recent-list" style={{ marginTop: ".5rem" }}>
                {orderStatus.payments.map((pay) => (
                  <li key={pay.id} className="admin-recent-item">
                    <div>
                      <code>{pay.id}</code>
                      <span>{pay.method ? `Method: ${pay.method}` : "Method: sandbox"}</span>
                    </div>
                    <span className={`pill ${pay.status === "captured" ? "mint" : "neutral"}`}>
                      {pay.status}
                    </span>
                    <span>{formatRupees(pay.amount_paise)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {recentOrders.length > 0 && (
          <div style={{ marginTop: "1rem" }}>
            <p className="eyebrow">Session order history</p>
            <ul className="admin-recent-list" style={{ marginTop: ".4rem" }}>
              {recentOrders.map((ord) => (
                <li key={ord.razorpay_order_id} className="admin-recent-item">
                  <div>
                    <code>{ord.razorpay_order_id}</code>
                    <span>
                      {formatRupees(ord.amount_paise)} · {ord.currency}
                    </span>
                  </div>
                  <span className={`pill ${ord.status === "paid" ? "mint" : "neutral"}`}>
                    {ord.status}
                  </span>
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => void inspectOrder(ord.razorpay_order_id)}
                  >
                    Inspect
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Canonical backend endpoints */}
      <div className="card admin-endpoints-card">
        <div className="card-header">
          <div className="symbol">
            <Icon name="fileText" />
          </div>
          <div className="grow">
            <p className="eyebrow">Backend contract</p>
            <h2>Canonical FastAPI Sandbox Endpoints</h2>
          </div>
          <span className={`pill ${configState === "ready" ? "mint" : "caution"}`}>
            {configState === "ready"
              ? "Connected"
              : configState === "checking"
                ? "Checking"
                : "Unavailable"}
          </span>
        </div>
        <ul className="admin-endpoint-list">
          {razorpayRequiredEndpoints.map((ep) => (
            <li key={ep.path} className="admin-endpoint-item">
              <span
                className={`pill ${ep.method === "POST" ? "caution" : "mint"} admin-method-pill`}
              >
                {ep.method}
              </span>
              <code className="admin-endpoint-path">{ep.path}</code>
              <span className="admin-endpoint-note">{ep.note}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

// ─── Mode C: Policy Lab Simulation ───────────────────────────────────────────

function PolicyLabPanel({ token }: { token: string }) {
  const [sampleSize, setSampleSize] = useState(120);
  const [seed, setSeed] = useState(42);
  const [baselineRupees, setBaselineRupees] = useState(50000);
  const [personalDeviation, setPersonalDeviation] = useState(5.0);
  const [businessDeviation, setBusinessDeviation] = useState(10.0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<PolicyLabSimulationResult | null>(null);

  async function runSimulation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const res = await policyLabApi.simulate(token, {
        sample_size: sampleSize,
        seed,
        baseline_a_threshold_paise: Math.max(100, Math.round(baselineRupees * 100)),
        personal_deviation_threshold: personalDeviation,
        business_deviation_threshold: businessDeviation,
      });
      setReport(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run Policy Lab benchmark.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="admin-panel-content">
      <div className="panel-section-head">
        <div>
          <p className="eyebrow">Mode C · Synthetic Held-Out Policy Lab</p>
          <h2>Threshold Calibration &amp; Friction Benchmarking</h2>
        </div>
        <span className="pill neutral">Held-Out Test Split · Synthetic Data</span>
      </div>

      <form className="policy-lab-form" onSubmit={runSimulation}>
        <div className="form-row">
          <label>
            Sample size
            <input
              type="number"
              min={12}
              max={500}
              value={sampleSize}
              onChange={(e) => setSampleSize(Number(e.target.value) || 60)}
            />
          </label>
          <label>
            Random seed
            <input
              type="number"
              min={0}
              value={seed}
              onChange={(e) => setSeed(Number(e.target.value) || 0)}
            />
          </label>
          <label>
            Baseline A threshold (INR)
            <input
              type="number"
              min={100}
              value={baselineRupees}
              onChange={(e) => setBaselineRupees(Number(e.target.value) || 10000)}
            />
          </label>
          <label>
            Personal deviation (x)
            <input
              type="number"
              step={0.5}
              min={2}
              max={20}
              value={personalDeviation}
              onChange={(e) => setPersonalDeviation(Number(e.target.value) || 5)}
            />
          </label>
          <label>
            Business deviation (x)
            <input
              type="number"
              step={0.5}
              min={3}
              max={30}
              value={businessDeviation}
              onChange={(e) => setBusinessDeviation(Number(e.target.value) || 10)}
            />
          </label>
        </div>

        {error && (
          <div className="notice" role="alert">
            <p>{error}</p>
          </div>
        )}

        <div className="actions">
          <button type="submit" className="primary" disabled={busy}>
            <Icon name="activity" size={16} />
            <span>{busy ? "Running simulation..." : "Run Policy Lab Simulation"}</span>
          </button>
        </div>
      </form>

      {report && (
        <div className="detail-panel" aria-label="Policy Lab Report">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <strong>Evaluated {report.total_scenarios_evaluated} held-out test scenarios</strong>
            <span className="pill mint">{report.evaluation_latency_ms} ms</span>
          </div>
          <p className="field-help">{report.declaration}</p>
          <div className="policy-metrics-grid">
            {Object.values(report.policy_metrics).map((m) => (
              <div key={m.policy_name} className="metric-card">
                <strong>{m.policy_name}</strong>
                <p>
                  Precision:{" "}
                  {m.precision.rate !== null ? `${Math.round(m.precision.rate * 100)}%` : "N/A"}
                </p>
                <p>
                  Recall: {m.recall.rate !== null ? `${Math.round(m.recall.rate * 100)}%` : "N/A"}
                </p>
                <p>
                  Business Disruption:{" "}
                  {m.business_disruption_rate.rate !== null
                    ? `${Math.round(m.business_disruption_rate.rate * 100)}%`
                    : "N/A"}
                </p>
                <p>Friction Cost Score: {m.friction_cost_score ?? 0}</p>
              </div>
            ))}
          </div>
          {report.scam_category_breakdown && (
            <div>
              <strong>Scam Category Breakdown</strong>
              <ul className="audit-list">
                {Object.entries(report.scam_category_breakdown).map(([cat, info]) => (
                  <li key={cat} className="audit-item">
                    <code>{cat}</code>
                    <span>
                      Total: {info.total} · Policy C catch rate:{" "}
                      {info.policies["Policy C (Profile-Aware PauseGuard)"]?.flag_rate !== null &&
                      info.policies["Policy C (Profile-Aware PauseGuard)"]?.flag_rate !== undefined
                        ? `${Math.round((info.policies["Policy C (Profile-Aware PauseGuard)"].flag_rate ?? 0) * 100)}%`
                        : "N/A"}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Admin Dashboard ──────────────────────────────────────────────────────────

export function Admin({ token, accountId }: { token: string; accountId: string }) {
  const [mode, setMode] = useState<AdminTestMode>("mock-upi");
  const [razorpayTabState, setRazorpayTabState] = useState<"checking" | "ready" | "unavailable">(
    "checking",
  );

  const handleRazorpayStatusChange = useCallback((next: "checking" | "ready" | "unavailable") => {
    setRazorpayTabState(next);
  }, []);

  return (
    <div className="admin-dashboard">
      <div className="admin-header">
        <div className="admin-header-copy">
          <p className="eyebrow">
            <span className="line" /> Admin testing workspace
          </p>
          <h1>
            Payment Testing <em>Dashboard</em>
          </h1>
          <p>
            Isolated sandbox to verify Mock UPI interventions and execute admin-only Razorpay Test
            Mode checkouts.
          </p>
        </div>
        <div className="admin-header-badges">
          <span className="pill neutral">
            <Icon name="shield" size={13} /> Admin Role Enforced
          </span>
          <span className="demo-badge">
            <span />
            Synthetic Only · No Real Money
          </span>
        </div>
      </div>

      <div className="admin-mode-tabs" role="tablist" aria-label="Payment testing mode">
        <button
          role="tab"
          id="tab-mock-upi"
          type="button"
          aria-selected={mode === "mock-upi"}
          aria-controls="panel-admin-mode"
          className={`admin-tab${mode === "mock-upi" ? " admin-tab-active" : ""}`}
          onClick={() => setMode("mock-upi")}
        >
          <Icon name="activity" size={16} />
          <span>Mode A — Mock UPI</span>
          <span className="pill mint">Ready</span>
        </button>
        <button
          role="tab"
          id="tab-razorpay"
          type="button"
          aria-selected={mode === "razorpay"}
          aria-controls="panel-admin-mode"
          className={`admin-tab${mode === "razorpay" ? " admin-tab-active" : ""}`}
          onClick={() => setMode("razorpay")}
        >
          <Icon name="zap" size={16} />
          <span>Mode B — Razorpay Test Mode</span>
          <span className={`pill ${razorpayTabState === "ready" ? "mint" : "caution"}`}>
            {razorpayTabState === "ready"
              ? "TEST ONLY · Active"
              : razorpayTabState === "unavailable"
                ? "TEST ONLY · Unavailable"
                : "TEST ONLY"}
          </span>
        </button>
        <button
          role="tab"
          id="tab-policy-lab"
          type="button"
          aria-selected={mode === "policy-lab"}
          aria-controls="panel-admin-mode"
          className={`admin-tab${mode === "policy-lab" ? " admin-tab-active" : ""}`}
          onClick={() => setMode("policy-lab")}
        >
          <Icon name="shieldAlert" size={16} />
          <span>Mode C — Policy Lab</span>
          <span className="pill neutral">Synthetic Lab</span>
        </button>
      </div>

      <div
        id="panel-admin-mode"
        className="card workspace-card admin-panel-card"
        role="tabpanel"
        aria-labelledby={
          mode === "mock-upi"
            ? "tab-mock-upi"
            : mode === "razorpay"
              ? "tab-razorpay"
              : "tab-policy-lab"
        }
      >
        {mode === "mock-upi" ? (
          <MockUpiPanel token={token} accountId={accountId} />
        ) : mode === "razorpay" ? (
          <RazorpayPanel
            token={token}
            accountId={accountId}
            onStatusChange={handleRazorpayStatusChange}
          />
        ) : (
          <PolicyLabPanel token={token} />
        )}
      </div>
    </div>
  );
}
