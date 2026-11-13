# PauseGuard V4.1 — Final Integration Checklist

**Release Candidate Branch:** `fix/hydrogen-final-v4-1-closure` (from `release/pauseguard-v4-1-final` @ `16bb7d2`)  
**Worktree:** `D:\PauseGuard-Hydrogen-Integration`  
**Base Baseline:** `origin/main` (`77be6ef`, including PR #25)

| Phase | Scope | Owner(s) | Status | Evidence / Notes |
|---|---|---|---|---|
| **0. Baseline & Safety** | Worktree isolation, PR #20/#24/#25/#26 audit | All | **VERIFIED COMPLETE** | `D:\PauseGuard` (`main`) untouched; closure branch isolated. |
| **1–2. PostgreSQL & CI Repair** | Fix `test_integration.py`, sync `0003`, fix `test_safe_lock_remains_enforced_after_timeout`, trigger `fix/**` CI | Member 4 / Member 1 | **IMPLEMENTED (CI GATED)** | **71 tests collected** cleanly in `backend/tests_integration/`; local Docker stopped (`com.docker.service`); `.github/workflows/python-ci.yml` configured for GitHub Actions `postgres:16`. |
| **3. Payment, Transaction & WS Hardening** | Savepoint `begin_nested()`, `/confirm` authz-before-idempotency, post-commit WS broadcast + guardian `payer_id` routing, bounded `evaluate_advisory` | Member 1 / Member 3 / Member 4 | **VERIFIED COMPLETE** | **1,031 passed, 52 subtests passed** in `python -m pytest tests backend/tests -q` (includes `test_v41_closure_regressions.py`). |
| **4–5. Frontend & Tracked Live E2E** | Mode A (`/__pauseguard/demo`) + Mode B (`VITE_USE_REAL_BACKEND=true`), WS, Safe-Lock (`423`), 30s fallback, 401 expiry | Member 2 / Member 1 | **VERIFIED COMPLETE** | `npm run build`, `npm run lint`, `21/21` unit tests, `16/16` mock browser tests, and `3/3` tracked live FastAPI Playwright E2E tests (`frontend/tests/e2e-real-backend.test.mjs`) pass. |
| **6. Main Merge Gate** | Gate merge into `main` until GitHub Actions `postgres-integration` job passes | Release | **OPEN PR / AWAITING REMOTE CI CHECK** | Push `fix/hydrogen-final-v4-1-closure` for PR review and GitHub Actions `postgres:16` confirmation before merging to `main`. |
| **7–9. Runbook & V5 Backlog** | `FINAL_RELEASE_RUNBOOK.md`, `POSTGRESQL_CI_VERIFICATION.md`, `V5_PRODUCT_BACKLOG.md` | Release | **VERIFIED COMPLETE** | All release and V5 backlog docs updated under `docs/`. |
