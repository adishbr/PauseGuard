# PauseGuard V5.0 — Observed Verification & Test Evidence

> **Branch:** `integration/v5-release`  
> **Scope Disclosure:** All verification runs below reflect local mock-mode execution against offline fixtures, FastAPI TestClient, Vite dev proxy, and headless Chromium Playwright E2E. PostgreSQL integration suites in `backend/tests_integration/` await remote PostgreSQL CI execution where local Docker/PostgreSQL is not started.

## 1. Automated Test Execution Summary

| Suite | Command | Result |
| :--- | :--- | :--- |
| Backend + Intelligence Pytest | `pytest tests backend/tests -q` | **1075 passed**, 52 subtests passed, 0 failed (`15.60s`) |
| Frontend Build + TypeScript | `npm run build` (`tsc -b && vite build`) | Passed (`485ms`, 0 errors) |
| Frontend Lint | `npm run lint` (`oxlint src tests mocks`) | **0 warnings, 0 errors** (`216ms`) |
| Frontend Unit & Contract Tests | `npm test` (`node --test tests/payment.test.mjs`) | **23 passed**, 0 failed (`701ms`) |
| Live Browser E2E (Chrome + FastAPI) | `node --test tests/e2e-real-backend.test.mjs` | **5 passed**, 0 failed (`49.89s` post-convergence, V4.1 flows + V5 Email/OTP/KYC/Durable Invites + single-use WS tickets) |

## 2. Local Latency Benchmark (Observed Synthetic Mock-Mode Runs)
- `POST /api/v2/payments` (`N=40`, TestClient mock mode): `p50 = 5.175 ms`, `p95 = 6.354 ms`
- `POST /api/v2/policy-lab/simulate` (`sample_size=120`, `N=10`): `p50 = 6.94 ms`, `p95 = 32.956 ms`
- `GET /api/v2/metrics` sampled HTTP middleware distribution (`N=50`): `p50 = 2.141 ms`, `p95 = 4.117 ms`

## 3. V5 20-Test Acceptance Matrix Coverage
1. Self-guardianship / same-person alt-account block: `test_v5_identity_auth.py`
2. Admin role registration forbidden: `test_v5_identity_auth.py`
3. Expired/used/wrong OTP & brute-force lockout: `test_v5_identity_auth.py`
4. Independent human guardian invite + KYC + consent -> `ACTIVE`: `test_v5_identity_auth.py`
5. Guardian revocation blocks future approvals: `test_v5_identity_auth.py`
6. Payee/amount edit invalidates prior approval (`409` on stale confirm): `test_v5_gate4_appeals_retry.py`
7. 30s guardian deadline expiry -> `AWAITING_FALLBACK_REVIEW`, never auto-executed: `test_v5_acceptance_matrix.py`
8. Compromised guardian suspension + backup guardian failover: `test_v5_gate4_appeals_retry.py`
9. Safe retry preserves `parent_payment_id` & `RETRY_OF_PARENT` audit lineage: `test_v5_gate4_appeals_retry.py`
10. Analyst resolves appeal; payer self-approval blocked (`403`): `test_v5_gate4_appeals_retry.py`
11. Anti-smurfing `subject_id` ignored/restricted for non-analysts: `test_v5_identity_auth.py`
12. Single-use `/api/v2/ws/ticket` enforcement & plaintext token rejection: `test_v5_gate5_ws_outbox.py`
13. Durable `NotificationOutbox` & stub failover boundaries: `test_v5_gate5_ws_outbox.py`
14. Redacted guardian notifications (zero amount/beneficiary leakage): `test_v5_gate5_ws_outbox.py`
15. Policy Lab `friction_cost_score`, scam breakdown & calibration: `test_v5_gate5_intelligence.py`
16. Mock bank pre-execution adapter, HMAC webhook verification & replay idempotency: `test_v5_gate6_bank_adapter.py`
17. Razorpay Test Mode isolation (`rzp_live_*` rejection, Admin-only RBAC): `test_v5_gate6_bank_adapter.py`
18. Concurrent payment confirmation single-debit idempotency: `test_v5_acceptance_matrix.py`
19. Production mode fail-closed assertions across demo auth, local OTP, mock KYC, stubs & bank adapter: `test_v5_acceptance_matrix.py`
20. End-to-end UI journey (V5 signup -> OTP -> KYC -> Invite/Accept -> High-Risk Approval -> Execution + WS tickets): `frontend/tests/e2e-real-backend.test.mjs`

