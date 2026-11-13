# PauseGuard V5.0 — System & Migration Architecture

> **Status:** Gate 1 Architecture Blueprint (Extending V4.1 `/api/v2` + SQLAlchemy ORM)

---

## 1. Architectural Strategy: Extend, Don't Rebuild

V5 extends V4.1 in-place inside `backend/app/`, `intelligence/`, `safety/`, and `frontend/src/`:
- **Database Dual-Runtime Parity:** Every durable V5 table (`user_accounts`, `identity_assurances`, `otp_challenges`, `user_sessions`, `guardian_invitations`, and later Gate 4–6 tables) uses standard PostgreSQL-compatible SQLAlchemy ORM models (`UUID` PKs, `TIMESTAMP(timezone=True)`, `pk_`/`fk_`/`ck_`/`ix_` naming conventions) synced with sequential Alembic revisions starting at `0005_v5_identity_otp_enrollment` in both `backend/migrations/` and `backend/tests_integration/migrations/`.
- **Mock-Mode Developer & E2E Continuity:** When `PAUSEGUARD_MODE=mock` and `session_factory is None` (e.g., local Vite+FastAPI preview without Docker), services use an explicitly labeled, thread-safe `app.state` in-memory store with identical state transitions and invariants. When `session_factory` is absent and `mode != "mock"`, endpoints fail closed with `503 Service Unavailable`.

---

## 2. Core Provider Abstractions

```
+-------------------------------------------------------------------------+
|                           FastAPI (/api/v2)                             |
+-------------------+---------------------+---------------------+---------+
| Auth & Identity   | Guardian Lifecycle  | Payment & Appeals   | Sandbox |
| /auth/*           | /guardian/*         | /payments/*         | /razor- |
| /identity/*       |                     | /safety/*           | pay/*   |
+--------+----------+----------+----------+----------+----------+----+----+
         |                     |                     |               |
         v                     v                     v               v
+----------------+    +----------------+    +------------------+  +------+
| OtpProvider    |    | Identity       |    | PaymentIntent /  |  | RZP  |
| - LocalMock    |    | AssuranceProv  |    | BankAdapter      |  | Test |
| - StagedStub   |    | - SyntheticIDP |    | - MockBankRail   |  | Mode |
+----------------+    +----------------+    +------------------+  +------+
```

### Key Boundaries
1. **Authentication Resolver (`get_current_actor`)**
   - Checks `user_sessions` (DB or app mock store) using SHA-256 token hash first.
   - Only falls back to V4.1 `resolve_synthetic_token` if `is_demo_mode_allowed(settings)` is true.
   - Guarantees role bindings (`PAYER`, `GUARDIAN`, `ANALYST`, `ADMIN`) come exclusively from server state (`user_accounts.role` / `role_bindings`).
2. **Identity Assurance Isolation (`TrustedPersonRef`)**
   - `SyntheticLocalIdentityProvider` hashes normalized synthetic identity attributes with a server-only HMAC key into an opaque `trusted_person_ref` (`tpr_<hex>`) and checks uniqueness/conflict when a payer invites a guardian or a user attempts duplicate enrollment.
   - Never stores raw national ID strings or full document payloads.
3. **Bank Pre-Execution vs. Merchant Test Checkout**
   - Mock UPI pre-execution intervention remains governed by `DurablePaymentEngine` + `BankAdapter` pre-settlement holds.
   - `RazorpaySandboxClient` remains strictly admin-isolated for optional merchant checkout testing (`rzp_test_*`).

