# PauseGuard V4.1 — Team Handoff & Integration Status

**Workspace:** `D:\PauseGuard`  
**Current Integration Branch:** `integration/komal-adish-v4-1`  
**Latest Local Commit SHA:** `4a3a530eb8d25501d35afed17a87749bef820d0c`  
**Latest `origin/main` SHA:** `c8f63d106d5576eeccadbcfaa8c55e4ed9a0f6cf`  
**Canonical Remote Repository:** `https://github.com/adishbr/celestial.git`  
**Date:** November 13, 2026  

---

## 1. Completed Modules & Core Capabilities

### A. Core Backend & Durable Payment Engine (Komal)
- **FastAPI Foundation (`/api/v2`):** Canonical V2 routing, middleware for correlation IDs (`X-Correlation-ID`), strict schema validation with Pydantic V2 (`extra="forbid"`).
- **Durable Payment State Machine:**
  - Idempotent payment creation with `DurablePaymentEngine`.
  - Authoritative status transitions: `CREATED -> AWAITING_WARNING -> AWAITING_GUARDIAN -> READY_TO_EXECUTE -> EXECUTED` (or terminal `REJECTED`, `CANCELLED`).
  - Strict 30/45/60s guardian timeout handling: transitions fail-closed to `AWAITING_FALLBACK_REVIEW` (never auto-approves on timeout).
  - Optimistic concurrency locking (`version` column) and PostgreSQL row-level advisory locking for audit chain integrity.
- **Durable Audit Hash-Chain (`/api/v2/audit/*`):** SHA-256 linear hash-chain persisted across transactions, verification endpoint (`/api/v2/audit/verify`), and cryptographic anchor checkpointing (`/api/v2/audit/anchors`).
- **Server-Side Authentication & Role Boundaries:**
  - Independent actor resolution via `TrustedActorContext` (payer, guardian, analyst, admin).
  - Disallows client-supplied actor ID or role assertions.
  - Fail-closed demo token handling (`is_demo_mode_allowed()`).
- **Razorpay Test Mode Merchant Sandbox (`/api/v2/sandbox/razorpay/*`):**
  - Fully decoupled merchant payment sandbox (isolated from mock UPI/P2P rails).
  - Admin-only access for order creation (`/orders`), checkout signature verification (`/verify`), and status history (`/orders/{order_id}`).
  - Inbound webhook receiver with raw HMAC-SHA256 verification and atomic replay protection.
- **Risk Advisory Route Integration (`POST /api/v2/risk/advice`):**
  - Integrated Gowtham's standalone `evaluate_advisory()` adapter.
  - Exception and timeout isolation: degrades gracefully to `make_degraded_advisory` (`advisory_score=None`, `can_authorize_payment=False`).
  - Validates caller payment context against evaluator signals.

### B. Core Frontend & Accessible Glassmorphic UI (Adish)
- **Vite + React 19 + Tailwind CSS:** Clean, responsive glassmorphic interfaces for Payer, Guardian, Admin, and Public landing.
- **Two-Window Demo Workspaces:**
  - Multi-window synchronized workflows between Payer and Guardian.
  - Real-time countdown timer bound to server's `guardian_deadline` with latency skew compensation.
  - Privacy-redacted review panel for guardians (hides unverified beneficiary names and exact amounts).
- **Accessibility & Multi-Language Support:**
  - Supports English (`en`), Hindi (`hi`), Kannada (`kn`), and Telugu (`te`) with variable Google Noto fonts.
  - Respects reduced-motion preferences (`prefers-reduced-motion`) and offers large-text accessibility toggles.
- **Admin Testing Portal (`/admin`):**
  - Mode A (Mock UPI test sandbox with synthetic payer context and audit chain inspection).
  - Mode B (Razorpay merchant test checkout preview).
- **Dual-Mode Dev Proxy:**
  - Configurable Vite proxy: standalone mock demo mode (default) vs real backend mode (`VITE_USE_REAL_BACKEND=true`).
  - Autonomous, port-safe test runner (`frontend/tests/test-runner.mjs`) with strict-port collision protection.

### C. Fraud Intelligence & Advisory Pipeline (Gowtham)
- **Fraud Intelligence Evaluators:**
  - Behavioral deviation baseline scoring (`intelligence/behavioral/baseline_evaluator.py`).
  - Synthetic mule transaction graph proximity scoring (`intelligence/mule_graph/graph_proximity.py`).
  - Consented call transcript coercion NLP heuristics (`intelligence/nlp/transcript_coercion.py`).
  - Rolling velocity and structured AML indicators (`intelligence/advisory/types.py`).
- **Standalone Advisory Adapter (`intelligence/advisory/adapter.py`):**
  - Clean decoupled boundary with non-negotiable payment safety invariants (`can_authorize_payment=False`, `can_execute_payment=False`, `advisory_only=True`).
  - Degraded mode builder (`make_degraded_advisory()`) for timeouts, exceptions, and context mismatches.

### D. Safety, Recovery & QA Hardening (Jeevan)
- **Safety Rails:**
  - Binary Safe-Lock toggle (`/api/v2/safe-lock`): immediate transfer blocking and confirmation abort.
  - Purpose Challenge coercion detector (`/api/v2/safety/purpose-challenge`).
  - Anti-Smurfing velocity checker (`/api/v2/safety/anti-smurfing/check`).
- **Victim Recovery:**
  - National cybercrime helpline 1930 recovery guide (`/api/v2/recovery/guide`).
  - Privacy-redacted evidence packet generation (`/api/v2/payments/{id}/evidence`).
- **Cross-Cutting QA:**
  - PostgreSQL durable fallback review tests (`backend/tests_integration/test_payment_ledger_integration.py`).
  - Integration regression suites (`tests/`).

---

## 2. Mock-Only vs Real-Backend Capabilities

| Capability | Mock Demo Mode (`mocks/`) | Real Backend (`/api/v2`) | Status & Boundary |
| :--- | :--- | :--- | :--- |
| **P2P Payment Lifecycle** | In-memory `Map` in `payment-api.ts` | SQLite / PostgreSQL `payments` table | Both implement canonical V2 states and integer `amount_paise`. |
| **Guardian Timeout** | In-memory clock check -> `AWAITING_FALLBACK_REVIEW` | Database timestamp check -> `AWAITING_FALLBACK_REVIEW` | Zero auto-approval on timeout in both modes. |
| **Audit Log** | In-memory hash list | Database `audit_events` table with advisory lock | Both enforce SHA-256 linear hash chaining. |
| **Authentication** | `mocks/accounts.ts` (`/__pauseguard/demo/*`) | Server `TrustedActorContext` via bearer token | Frontend currently logs in via mock demo session API. Real backend uses static/synthetic token registry. |
| **Real-Time Updates** | Client HTTP polling (`usePayment`) | WebSocket `/api/v2/ws/payments/{id}` | WebSocket operational in backend; frontend currently uses HTTP polling fallback. |
| **Risk Advisory** | Heuristic rule simulation | `evaluate_advisory()` adapter | Backend route `/api/v2/risk/advice` is wired to the live intelligence orchestrator. |
| **Razorpay Test Mode** | Simulated order generation in mock API | `RazorpayMerchantService` (Test Mode API / Mock Client) | Both modes enforce admin-only scoping and server-side HMAC signature verification. |

---

## 3. Test Verification Outcomes

| Suite | Tests Executed | Passed | Failed | Duration | Scope |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Backend & Intelligence Python Tests** | 995 | **995** | 0 | 9.62s | Core payment state machine, PostgreSQL ledger integration, risk adapter, policy lab, Razorpay, audit hash chain. |
| **Targeted Risk Route Tests** | 8 | **8** | 0 | 1.47s | `POST /api/v2/risk/advice` adapter integration, context mismatch degradation, exception handling, schema. |
| **Intelligence Adapter Tests** | 14 | **14** | 0 | 0.17s | Standalone adapter invariants, timing metadata, exception containment. |
| **Frontend Unit Tests** | 18 | **18** | 0 | 658ms | Integer paise conversion, review duration settings, Unicode decoding, Razorpay sandbox isolation. |
| **Frontend Linter** | 37 files | **0 errors, 0 warnings** | 0 | 126ms | `oxlint src tests mocks`. |
| **Frontend Production Build** | Client bundle | **SUCCESS** | 0 | 292ms | TypeScript compilation and Vite assets minification. |
| **Playwright Browser Tests** | 16 | **16** | 0 | 98.7s | End-to-end browser journeys: sign-in, mobile responsive, 30/45/60s review timers, Safe-Lock, guardian decline/accept/revoke. |

---

## 4. Open PRs & Upstream Status

- **Merged into `origin/main`:**
  - `PR #19`: Komal's Razorpay test mode integration (`72572d9`).
  - `PR #21`: Gowtham's standalone advisory adapter (`c8f63d1`).
  - `PR #22`: Member 4's backend QA integration and fallback review tests (`a0412c6`).
- **Branches Pending Review / In Progress:**
  - `integration/komal-adish-v4-1`: Active integration branch containing combined frontend-backend work.
  - `feature/member-4-postgres-ci` (`PR #20` / `dcfcdec`): PostgreSQL CI workflow configurations.
  - `feat/adish-frontend` (`950e97b`): Adish's frontend development branch (fully integrated into `integration/komal-adish-v4-1`).

---

## 5. Remaining Gaps & Blockers

1. **Identity & Auth Bridge for Pure Real-Backend Mode:**
   - The frontend's `accountApi.ts` currently requests sessions from `/__pauseguard/demo/session`.
   - In pure real-backend mode without Vite mock middleware, an authoritative token-vending endpoint (e.g. `/api/v2/auth/login` or `/api/v2/demo/token`) is needed so the frontend can receive valid `TrustedActorContext` bearer tokens directly from the FastAPI server.
2. **WebSocket Integration in Frontend:**
   - The FastAPI backend implements live event broadcasting via `/api/v2/ws/payments/{id}`.
   - The React frontend currently relies on HTTP interval polling. Replacing or augmenting polling with a real WebSocket listener will improve multi-window responsiveness.
3. **External Provider Sandbox Setup (Razorpay):**
   - Live Test Mode keys (`RZP_TEST_KEY_ID`, `RZP_TEST_KEY_SECRET`) must be provided in local `.env` only for live provider testing; mock client mode is currently tested and verified offline.

---

## 6. Work Assigned by Team Member

### 1 — Komal (Core Backend & Integration Lead)
- [x] Merge `origin/main` and resolve integration branch divergence.
- [x] Wire `evaluate_advisory()` into `/api/v2/risk/advice` with regression test suite.
- [x] Enforce server-side security invariants and fail-closed degraded risk advisory.
- [ ] Connect real backend identity/token issuance endpoint for seamless frontend proxying without mock middleware.
- [ ] Implement backend WebSocket listener hook for guardian decisions.

### 2 — Adish (Core Frontend & Integration Lead)
- [x] Design glassmorphic UI, responsive layouts, and multi-language support.
- [x] Build Payer and Guardian two-window workflow with real-time countdown timer.
- [x] Provide Admin Payment Testing Dashboard (Mock UPI + Razorpay sandbox tabs).
- [ ] Connect `usePayment` hook to backend WebSocket endpoint (`/api/v2/ws/payments/{id}`) with fallback to HTTP polling.
- [ ] Wire frontend Mode B Razorpay checkout button to call `razorpayApi.createOrder()` and mount Razorpay Checkout JS modal.

### 3 — Gowtham (Intelligence & Policy Lab)
- [x] Build behavioral deviation baseline evaluator and synthetic mule graph.
- [x] Build consented call transcript coercion NLP heuristics.
- [x] Author standalone `evaluate_advisory()` adapter (`PR #21`).
- [ ] Expand Policy Lab benchmark simulation datasets and scenario presets.
- [ ] Fine-tune heuristic weights for subtle coercion patterns.

### 4 — Jeevan (Safety & QA)
- [x] Implement Purpose Challenge and Anti-Smurfing safety services.
- [x] Implement Safe-Lock and 1930 recovery guidance endpoints.
- [x] Build PostgreSQL durable fallback review integration tests (`PR #22`).
- [ ] Complete CI PostgreSQL workflow verification (`PR #20`).
- [ ] Conduct end-to-end security penetration testing on cross-role actor impersonation.
