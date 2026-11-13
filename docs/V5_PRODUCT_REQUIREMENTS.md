# PauseGuard V5.0 — Product Requirements & Baseline Gap Matrix

> **Status:** Gate 1 Design Specification (Frozen Baseline: V4.1 `fix/v4-1-gate0-closure` @ `10a365f`)  
> **Scope:** Mock-rail UPI APP-fraud intervention prototype & bank/fintech-ready integration architecture. Real money, live UPI settlement, direct bank account interception, production IAM, and real government e-KYC (Aadhaar/PAN APIs) remain **strictly out of scope** without formal authorization.

---

## 1. Mission & Non-Negotiable Security Invariants

1. **Payer, Guardian, Analyst, Admin** roles are authenticated and enforced exclusively server-side. Client-supplied `user_id`, `role`, `subject_id`, or `trusted_person_ref` claims are ignored or rejected.
2. **Contact Verification != Identity Assurance != Authentication:**
   - Separate emails or OTP-verified phone numbers never prove that a payer and guardian are different human beings.
   - Server-issued `IdentityAssurance` records establish an opaque `trusted_person_ref`; self-guardianship and same-person multi-account collusion are blocked fail-closed.
3. **Human Guardian Authority & Privacy:**
   - 30-second guardian timeout **never** auto-executes a payment.
   - AI risk intelligence provides advisory signals only (`can_authorize_payment = False`).
   - Guardians see redacted payment metadata (no exact rupee/paise amount, account numbers, or raw purpose details).
4. **Local/Sandbox Adapters Explicitly Labeled:**
   - Local OTP, synthetic identity assurance, and mock bank pre-execution adapters fail closed in production environments unless backed by authorized external providers.
   - Razorpay stays isolated in admin-only **Test Mode** (`rzp_test_*`); `rzp_live_*` keys are rejected.

---

## 2. Verified V4.1 → V5.0 Gap Matrix

| Subsystem | Current V4.1 Status | Verified Codebase Reality | V5.0 Target (Gate) |
| :--- | :--- | :--- | :--- |
| Health, Readiness, Config | `IMPLEMENTED` | `/api/v2/health`, frozen Pydantic `Settings`, correlation ID middleware | Preserve + metrics hooks (Gate 7) |
| Demo Auth & Role Boundaries | `IMPLEMENTED` | 5 synthetic identities, `/api/v2/demo/session` loopback-gated, strict RBAC (`test_demo_auth.py`) | Preserve demo routes cleanly alongside V5 real account auth (Gate 2) |
| Real Account Signup, Login & Password Hashing | `MISSING` | No `user_accounts` / `user_sessions` DB tables or `/api/v2/auth/signup\|login` endpoints | Durable scrypt-hashed accounts & hashed server sessions (Gate 2) |
| OTP Challenge & Verification Provider | `MISSING` | No `OtpChallenge` persistence, provider abstraction, or cooldown/lockout logic | `OtpProvider` interface + `DeterministicLocalOtpProvider` (Gate 2) |
| Provider-Agnostic Identity Assurance | `MISSING` | No opaque `trusted_person_ref` assurance records or duplicate-human rejection | `IdentityAssurance` model + `SyntheticLocalIdentityProvider` (Gate 2) |
| Durable Guardian Enrollment & Invites | `PARTIAL` | `GuardianService` uses in-memory `_enrollments`/`_verified_identities` dict; lost on restart | DB-backed invitation state machine, primary+backup guardians (Gate 2–4) |
| Payment State Machine & Immutable Snapshot | `PARTIAL` | 11 canonical statuses, idempotent DB ledger; `AWAITING_STEP_UP` unused, no payee/amount change invalidation | Approval snapshot checks, safe retry lineage, WebAuthn step-up (Gate 4) |
| False-Alert Appeals & Safe Retry | `MISSING` | Rejected payments terminate cleanly without review-request appeal trail | `PaymentAppeal` review workflow + safe retry (Gate 4) |
| WebSocket Security & Outbox Notifications | `PARTIAL` | `/api/v2/ws` accepts long-lived bearer token in query param; no persistent outbox or push | Short-lived `/api/v2/ws/ticket` + durable outbox + push/SMS stubs (Gate 5) |
| Risk Advisory, Calibration & Policy Lab | `PARTIAL` | Deterministic scoring, coercion cues, mule heuristics, `/policy-lab/simulate` | Extended scam taxonomy, latency/calibration metrics, interactive UI (Gate 5) |
| Anti-Smurfing Subject Boundary | `PARTIAL` | `safety.py:114` falls back to client `request.subject_id` even for non-analysts | Enforce server `actor.user_id` for payers/guardians (Gate 2) |
| Bank Pre-Execution Adapter | `MISSING` | Mock execution occurs directly inside engine without provider/webhook boundary | `PaymentIntentProvider` / `BankAdapter` contract + local simulator (Gate 6) |
| Razorpay Merchant Test Mode Isolation | `IMPLEMENTED` | Isolated admin-only Test Mode routes & signed webhook handler (`rzp_test_*`) | Keep strictly separated from UPI pre-execution + clean UI framing (Gate 3/6) |
| Live Aadhaar/PAN e-KYC / Live UPI Settlement | `BLOCKED` | Explicitly out of scope without bank/UIDAI/NPCI legal & credential approval | Remain interface-ready only; never simulate unauthorized live rails |

---

## 3. Essential V5 Acceptance Tests Map (1–20)

| Test # | Scenario Summary | Target Gate |
| :--- | :--- | :--- |
| 1 | Payer cannot enroll themselves or same-person alt account as guardian | Gate 2 |
| 2 | User cannot sign up as `admin` or claim admin role via API | Gate 2 |
| 3 | Expired/used/wrong OTP fails; brute-force locks challenge safely | Gate 2 |
| 4 | Different person completes guardian invite + independent KYC + explicit consent -> `ACTIVE` | Gate 2 |
| 5 | Existing active guardian revokes -> no new approvals; revoked guardian cannot act | Gate 2 |
| 6 | Payer modifies payee/amount after approval -> prior guardian approval invalidated | Gate 4 |
| 7 | 30s guardian timeout -> `AWAITING_FALLBACK_REVIEW`, NEVER auto-executed | Gate 4 |
| 8 | Compromised/suspended guardian blocked from acting; emergency fallback activates | Gate 4 |
| 9 | Safe retry on failed/appealed transaction preserves fraud context & links lineage | Gate 4 |
| 10 | Analyst resolves payer false-alert appeal; payer cannot self-approve appeal | Gate 4 |
| 11 | Client-supplied `subject_id` in anti-smurfing check rejected/ignored for payers | Gate 2 |
| 12 | WebSocket short-lived single-use ticket succeeds; expired/reused ticket rejected | Gate 5 |
| 13 | Notification outbox records delivery attempts & transitions cleanly without duplicates | Gate 5 |
| 14 | Guardian notification contains zero payment amount/payee account leakage | Gate 5 |
| 15 | High-risk coercion cues + mule risk trigger `AWAITING_STEP_UP` or `AWAITING_GUARDIAN` | Gate 5 |
| 16 | Bank pre-execution mock adapter rejects tampered webhook HMAC signature | Gate 6 |
| 17 | Razorpay sandbox rejects `rzp_live_*` and enforces admin-only boundary | Gate 6 |
| 18 | Concurrent duplicate confirmations/decisions yield single ledger execution | Gate 4/7 |
| 19 | Production mode fails closed on demo auth, local OTP/mock KYC, and mock payment mode | Gate 2/7 |
| 20 | End-to-end UI journey (Signup -> OTP -> Identity -> Invite -> Payment -> Guardian -> Confirm) | Gate 3/7 |

