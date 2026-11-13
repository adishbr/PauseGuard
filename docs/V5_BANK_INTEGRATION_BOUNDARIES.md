# PauseGuard V5.0 — Banking Integration Boundaries & Sandbox Isolation

## 1. Strict Prototype & Regulatory Scope Boundary
PauseGuard is an **APP-fraud pre-execution intervention prototype and integration architecture**:
- **Out of scope without formal bank/NPCI/UIDAI authorization:** Live NPCI UPI settlement, direct bank account interception, real-money transfers, and live Aadhaar/PAN e-KYC verification.
- Every local mock/sandbox component (`MockBankRailAdapter`, `SyntheticLocalIdentityProvider`, `DeterministicLocalOtpProvider`, `WebPushStubProvider`, `SmsStubProvider`) is explicitly flagged `is_mock = True` and **fails closed** outside `local`/`test` mock mode.

## 2. Bank Pre-Execution Intent & Settlement Adapter (`backend/app/integrations/bank_adapter.py`, `backend/app/api/bank.py`)
- **Interfaces:** `PaymentIntentProvider`, `PaymentExecutionProvider`, and `BankAdapter`.
- **Intent Registration (`POST /api/v2/bank/intents`):** Owning payers (or admins acting within RBAC bounds) register a pre-execution hold intent (`bnk_int_*`, `HOLD_PENDING`). Cannot bypass PauseGuard Safe-Lock, warning acknowledgment, step-up, or guardian approval.
- **Settlement Webhook Verification (`POST /api/v2/bank/webhooks/settlement`):**
  - Verifies raw-body HMAC-SHA256 signature (`X-PauseGuard-Bank-Signature`) via constant-time `hmac.compare_digest`.
  - Enforces event replay idempotency via `event_id` deduplication.
  - Enforces server state check: returns `409 Conflict` if a webhook claims `SETTLED` while PauseGuard's internal state is not `EXECUTED`.

## 3. Razorpay Test Mode Merchant Sandbox Isolation
- Mounted strictly on admin-only routes `/api/v2/sandbox/razorpay/*`.
- Enforces `rzp_test_*` Test Mode keys only (`rzp_live_*` keys fail closed in `load_sandbox_config`).
- Non-admin roles receive `403 Forbidden`; checkout signatures and webhooks remain isolated from PauseGuard P2P payments and ledger balances.

