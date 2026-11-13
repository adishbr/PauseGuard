# PauseGuard V4.1 — Final Integration Checklist

**Integration Branch:** `integration/hydrogen-final-v4-1`  
**Worktree:** `D:\PauseGuard-Hydrogen-Integration`  
**Base Baseline:** `origin/main` (`77be6ef`, including PR #25)

| Phase | Scope | Owner(s) | Status | Evidence / Notes |
|---|---|---|---|---|
| **A. Audit & Preservation** | Repo, branches, PRs #20/#24/#25/#26, contracts | All | **COMPLETE** | Worktree isolated from `D:\PauseGuard` (`main`) and `D:\PauseGuard_feature`. |
| **B. Backend Auth Bridge** | `/api/v2/demo/session`, `/api/v2/profile`, loopback proxy | Member 1 (Komal) | **VERIFIED COMPLETE** | Integrated PR #24 (`2981911`); `test_demo_auth.py` + `pytest` pass. |
| **C. Guardian Txn Safety** | `GuardianLateDecisionOutcome`, HTTP 409 atomic fallback | Member 1 (Komal) | **IMPLEMENTED / PG UNTESTED** | Cherry-picked PR #26 (`9ccc5c0`); unit tests pass; live PostgreSQL tests blocked locally (Docker daemon not running). |
| **D. Payment Engine & Authz** | Canonical V2 state machine, idempotency, Safe-Lock | Member 1 / Member 4 | **VERIFIED COMPLETE** | Fixed `payment_service.py` `/confirm` authz-before-idempotency order + added regression test in `test_phase3_full.py`. |
| **E. PostgreSQL & CI** | `tests_integration/`, PR #20 (`dcfcdec` reverted) | Member 4 (Jeevan) | **BLOCKED (ENV)** | Docker daemon not running & `psql` absent locally; PR #20 CI job was reverted on origin. |
| **F. Frontend Auth & Modes** | Mode A (`/__pauseguard/demo`), Mode B (`VITE_USE_REAL_BACKEND=true`) | Member 2 (Adish) | **VERIFIED COMPLETE** | Integrated `4358d1f` + `accountApi.review()` `/guardian/dashboard` fix; static-host 404 diagnostic verified. |
| **G. Signup Error Fix** | Static host 404 diagnostic & FastAPI mode notice | Member 2 (Adish) | **VERIFIED COMPLETE** | `Auth.tsx`, `accountApi.ts`, `adminApi.ts`, unit test pass. |
| **H–J. Payer, Guardian, WS** | Live `/api/v2/ws`, polling fallback, redaction, 30s fallback | Member 2 / Member 1 | **VERIFIED COMPLETE** | Live Playwright E2E against FastAPI (`127.0.0.1:8000`) passed. |
| **K–L. Intelligence & Policy Lab** | `POST /api/v2/risk/advice`, `POST /api/v2/policy-lab/simulate` | Member 3 (Gowtham) | **VERIFIED COMPLETE** | Already on `main`; `tests/intelligence/` + `test_risk_api.py` + `policy_lab` pass in full `pytest` suite (`1,025 passed`). |
| **M–O. Safety, Audit, Razorpay** | Safe-Lock, purpose challenge, SHA-256 chain, Razorpay webhook | Member 4 (Jeevan) | **VERIFIED COMPLETE** | PR #25 webhook validation on `main` (`77be6ef`); `test_razorpay_integration.py` (40 passed) + `tests/unit/` pass. |
| **P–Q. UI/UX, i18n, A11y** | WovenLock, Dark/Light mode, en/hi/kn/te, mobile | Member 2 (Adish) | **VERIFIED COMPLETE** | 16/16 Playwright browser tests + `tsc -b && vite build` + `oxlint` pass. |
| **U–Z. Readiness & Docs** | `.env.example`, checklist, progress log, readiness report | HYDROGEN | **COMPLETE** | Documented in `docs/` without exposing secrets. |

