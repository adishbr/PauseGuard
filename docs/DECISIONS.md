# Architecture Decision Log
## Approved — 2026-11-09 (proposed V2 design)
- V2 APIs `/api/v2`, payment state machine is canonical. V1 integration kit deprecated for new implementation.
- Mock payer-to-payee ledger is core demo; optional merchant sandbox is separate.
- Profile-aware risk, not amount-only guardian checks.
- Opt-in guardian/authorized checker, 30s initial call-review window, never auto approval on timeout.
- AI advisory parallel to review; unavailable AI cannot authorize anything.
- No real third-party geolocation from phone number.
- No Solana/Phantom as UPI payment rail; potential audit-only research.
- Komal and Adish core owners; Gowtham risk and Policy Lab; Jeevan safety and QA.

## Approved — 2026-11-12 (Phase 3A: Provider-Independent Authorization Foundation & Security Hardening)
- **Date:** 2026-11-12
- **Proposer:** Komal (Member 1 — Core Backend Lead)
- **Approvers:** Komal + Adish (Core Architecture)
- **Decision:** Implemented provider-independent authorization and actor resolution core (`backend/app/auth/`) using typed `TrustedActorContext` and deterministic prototype demo tokens (`DEMO_TOKEN_REGISTRY`). Client-supplied role claims and actor headers are strictly rejected server-side. Deny-by-default access control and cross-account isolation are enforced.
- **Fail-Closed Demo Security:** Prototype demo authentication is disabled by default in `Settings` (`allow_demo_auth=False`). Explicit authorization is required to enable demo tokens (`PAUSEGUARD_ALLOW_DEMO_AUTH=true` or `Settings(allow_demo_auth=True)`). Even with explicit opt-in, demo tokens are strictly accepted only when `environment in ("local", "test")` AND `mode == "mock"`; they are unconditionally rejected in production or real mode.
- **Authoritative Guardian Enforcement:** Guardian enrollment is strictly authoritative server-side data (`get_authoritative_guardian_for_payer`). Callers cannot self-authorize or assign guardians for unenrolled payers. Client-supplied `assigned_guardian_id` must match server records or is rejected.
- **Decoupled Roles & Dependency Optimization:** Extracted `UserRole` to `app.models.roles` so application routing and auth dependencies never eagerly load ORM models onto `Base.metadata`. Streamlined `get_current_actor` to utilize FastAPI's injected `HTTPBearer` credentials directly.
- **Pending Decision Required:** Production IAM identity provider (Supabase Auth / Auth0 / external OIDC) remains undecided and awaiting explicit team sign-off; the authorization engine operates purely on resolved `TrustedActorContext`, allowing seamless plug-in of any production token verifier without changing downstream policy, state machine, or API code.
- **Invariants Enforced:** Guardian approval never executes a payment automatically; human review timeout never auto-executes; non-payers cannot execute payments; payers cannot act as guardians for their own transactions.
- **Affected Files:** `backend/app/config.py`, `backend/app/models/roles.py`, `backend/app/models/user.py`, `backend/app/services/payment_guards.py`, `backend/app/main.py`, `backend/app/auth/exceptions.py`, `backend/app/auth/schemas.py`, `backend/app/auth/identities.py`, `backend/app/auth/authorization.py`, `backend/app/auth/dependencies.py`, `backend/app/auth/router.py`, `backend/app/auth/__init__.py`.
- **Tests:** `backend/tests/test_auth.py`, `backend/tests/test_config.py`, `backend/tests/test_app.py`, `backend/tests/test_offline.py` (offline verification of fail-closed demo gating, authoritative guardian checks, 401/403 status codes, token resolution, role enforcement, and privacy view redaction).
- **Migration Action:** None required for database schema; purely application-level configuration and authorization layer.

## Awaiting explicit team sign-off
- Exact guardian call provider and opt-in/recording process.
- Whether to use hosted Supabase Postgres vs local SQLite during early development.
- Whether ECC Minimal is installed and its release SHA/version.
- Verified ownership + approved SHA/license for any external code reuse.
- Host and auth identity solution; real-world data or payments remain excluded without partner review.
- Hackathon policy on pre-build work and what may be shown as coded onsite.

> Every revised decision must record date, proposer, approvers (Komal + Adish for core contract), reasons, trade-offs, affected files, tests, and migration action.
