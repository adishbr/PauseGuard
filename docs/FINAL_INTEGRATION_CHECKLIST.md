# PauseGuard V4.1 — Final Integration Checklist

**Release Candidate Branch:** `feat/razorpay-test-mode-completion` (PR #27 targeting `main`)  
**Worktree:** `D:\PauseGuard-Hydrogen-Integration` (`D:\PauseGuard` untouched)  

| Phase | Scope | Owner(s) | Status | Evidence / Notes |
|---|---|---|---|---|
| **0. Baseline & Safety** | Worktree isolation, PR #20/#24/#25/#26/#27 audit | All | **VERIFIED COMPLETE** | `D:\PauseGuard` untouched; PR branch cleanly contains all `origin/main` commits. |
| **1–2. PostgreSQL, Migration 0004 & Audit `append_seq` Repair** | Monotonic `audit_events_append_seq` + `append_seq`, fail-closed backfill, `pg_advisory_xact_lock`, concurrency/tamper regression tests | Member 4 / Member 1 | **VERIFIED IN POSTGRESQL 16 CI** | **76 passed** (`3.82s` pull_request run `43483777510`; `4.96s` push run `43483764496`) in GitHub Actions `postgres:16` service (`backend/tests_integration/`). Local Docker stopped (`com.docker.service`). |
| **3. Payment, Transaction, Razorpay Sandbox & WS Hardening** | Savepoint `begin_nested()`, `/confirm` authz-before-idempotency, post-commit WS broadcast, bounded `evaluate_advisory`, Razorpay admin config/sandbox | Member 1 / Member 3 / Member 4 | **VERIFIED COMPLETE** | **1,035 passed, 52 subtests passed** (`14.31s`) in `python -m pytest tests backend/tests -q`. |
| **4–5. Frontend & Tracked Live E2E** | Mode A (`/__pauseguard/demo`) + Mode B (`VITE_USE_REAL_BACKEND=true`), WS, Safe-Lock (`423`), 30s fallback, 401 expiry, Razorpay Test Mode UI | Member 2 / Member 1 | **VERIFIED COMPLETE** | `npm run build` (0 errors), `npm run lint` (0 errors/warnings), `21/21` unit tests, `17/17` mock browser tests, and `4/4` live FastAPI Playwright E2E tests (`frontend/tests/e2e-real-backend.test.mjs`) pass. |
| **6. Main Merge Gate** | Gate merge into `main` pending final doc CI confirmation & human approval | Release | **PR #27 OPEN / READY FOR REVIEW** | Both Python CI & PostgreSQL 16 integration CI green on code commit `4b9f262`; doc update re-verified via CI prior to review (not auto-merged). |
| **7–9. Runbook & V5 Backlog** | `FINAL_RELEASE_RUNBOOK.md`, `POSTGRESQL_CI_VERIFICATION.md`, `V5_PRODUCT_BACKLOG.md` | Release | **VERIFIED COMPLETE** | All release and V5 backlog docs updated under `docs/`. |
