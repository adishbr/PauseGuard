# PauseGuard V4.1 — Final Integration Checklist

**Release Candidate Branch:** `release/pauseguard-v4-1-final` (also synced to `integration/hydrogen-final-v4-1`)  
**Worktree:** `D:\PauseGuard-Hydrogen-Integration`  
**Base Baseline:** `origin/main` (`77be6ef`, including PR #25)

| Phase | Scope | Owner(s) | Status | Evidence / Notes |
|---|---|---|---|---|
| **0. Baseline & Safety** | Worktree isolation, PR #20/#24/#25/#26 audit | All | **VERIFIED COMPLETE** | `D:\PauseGuard` (`main`) untouched; release worktree isolated. |
| **1–2. PostgreSQL & CI Repair** | Fix `test_integration.py` duplicate `NameError`, sync `0003` migration, restore `postgres-integration` CI job | Member 4 / Member 1 | **IMPLEMENTED (CI GATED)** | **70 tests collected** cleanly in `backend/tests_integration/`; local Docker daemon stopped (`com.docker.service`); `.github/workflows/python-ci.yml` updated & pushed for GitHub Actions `postgres:16` verification. |
| **3. Payment & Security QA** | Auth bridge (PR #24), Guardian late-decision 409 (PR #26), `/confirm` authz-before-idempotency fix | Member 1 / Member 4 | **VERIFIED COMPLETE** | **1,025 passed, 52 subtests passed** in `python -m pytest tests backend/tests -q`. |
| **4–5. Frontend & Live E2E** | Mode A (`/__pauseguard/demo`) + Mode B (`VITE_USE_REAL_BACKEND=true`), WS, 30s fallback, Safe-Lock | Member 2 / Member 1 | **VERIFIED COMPLETE** | `npm run build`, `npm run lint`, `21/21` unit tests, `16/16` mock browser tests, and `3/3` live FastAPI Playwright E2E tests pass. |
| **6. Main Merge Gate** | Gate merge into `main` until GitHub Actions `postgres-integration` job passes on private repo | Release | **BLOCKED ON REMOTE CI CHECK** | Per Phase 6 rules, `main` is not merged before live PostgreSQL CI verification is confirmed green on GitHub. |
| **7–9. Runbook & V5 Backlog** | `FINAL_RELEASE_RUNBOOK.md`, `POSTGRESQL_CI_VERIFICATION.md`, `V5_PRODUCT_BACKLOG.md` | Release | **VERIFIED COMPLETE** | All release and V5 backlog docs written under `docs/`. |
