# PostgreSQL Integration & CI Verification Report (V4.1)

**Branch:** `fix/hydrogen-final-v4-1-closure` (from `release/pauseguard-v4-1-final`)  
**Worktree:** `D:\PauseGuard-Hydrogen-Integration`

---

## 1. Root Cause of Earlier PR #20 & Run #43471306451 Failures

Inspection of `origin/feature/member-4-postgres-ci` (`86c6c71` and its revert `dcfcdec`) and `backend/tests_integration/` identified three concrete issues that prevented clean PostgreSQL CI execution:

1. **Duplicate Unimported Test in `backend/tests_integration/test_integration.py`:**
   - Lines 803–903 of `backend/tests_integration/test_integration.py` contained a duplicate copy of `test_concurrent_cancellation_and_confirmation_are_serialized` (whose authoritative copy with imports already lives in `backend/tests_integration/test_payment_ledger_integration.py`).
   - `test_integration.py` did **not** import `_seed_test_payer`, `Payment`, `PaymentStatus`, `DurablePaymentEngine`, `PaymentConfirmRequest`, `ThreadPoolExecutor`, `HTTPException`, or `ledger_entries_for_payment`, causing an immediate `NameError` at runtime when the test ran.
2. **Pre-PR #26 Guardian Deadline Rollback Bug:**
   - When `86c6c71` was pushed (13:51 IST), PR #26 (`9ccc5c0`, 21:19 IST — `GuardianLateDecisionOutcome` + `JSONResponse(409)`) had not yet been implemented, so late guardian decisions raised `HTTPException(409)` inside `transaction_scope` and rolled back the `AWAITING_FALLBACK_REVIEW` transition.
3. **Missing `0003_razorpay_merchant_sandbox.py` in `backend/tests_integration/migrations/versions/`:**
   - `backend/migrations/versions/` included `0003_razorpay_merchant_sandbox.py` (revising `0002_durable_payment_ledger`), while `backend/tests_integration/migrations/versions/` stopped at `0002_durable_payment_ledger.py`.

---

## 2. Repairs Implemented on `release/pauseguard-v4-1-final`

1. **[backend/tests_integration/test_integration.py](file:///D:/PauseGuard-Hydrogen-Integration/backend/tests_integration/test_integration.py):** Removed the duplicate unimported `test_concurrent_cancellation_and_confirmation_are_serialized` function at the end of `test_integration.py` (retaining the authoritative version in `test_payment_ledger_integration.py`).
2. **[backend/tests_integration/migrations/versions/0003_razorpay_merchant_sandbox.py](file:///D:/PauseGuard-Hydrogen-Integration/backend/tests_integration/migrations/versions/0003_razorpay_merchant_sandbox.py):** Synced revision `0003_razorpay_merchant_sandbox` into the integration test migration directory so `command.upgrade(config, "head")` and `command.downgrade(config, "base")` cover all three revisions (`0001` → `0002` → `0003`).
3. **[backend/tests_integration/test_payment_ledger_integration.py](file:///D:/PauseGuard-Hydrogen-Integration/backend/tests_integration/test_payment_ledger_integration.py):** Integrated PR #26's `TestGuardianDeadlineTransaction` suite, fixed `test_safe_lock_remains_enforced_after_timeout` (previously expecting `423` on an `AWAITING_FALLBACK_REVIEW` payment that `confirm_payment` rejects with `409` before the live Safe-Lock check) to test both the `AWAITING_FALLBACK_REVIEW` (`409`) guard and a `READY_TO_EXECUTE` + engaged Safe-Lock (`423`) guard with zero debits, and added `test_other_payer_cannot_probe_confirm_idempotency_key_in_postgresql` (16 tests total in `TestGuardianDeadlineTransaction`).
4. **[.github/workflows/python-ci.yml](file:///D:/PauseGuard-Hydrogen-Integration/.github/workflows/python-ci.yml):** Restored the isolated `postgres-integration` job using `postgres:16` service container, healthcheck (`pg_isready`), disposable `pauseguard_test_ci` database (`127.0.0.1:5432`), and `python -m pytest -c backend/pytest_integration.ini backend/tests_integration -v`. Added `"integration/**"`, `"release/**"`, and `"fix/**"` to `on.push.branches`.

---

## 3. Verification Executed Locally vs. CI Gate

- **Collection & Static Verification (Executed Locally):**
  ```powershell
  python -m pytest --collect-only -c backend/pytest_integration.ini backend/tests_integration -q
  ```
  - **Result:** **71 tests collected in 0.28s** (`42` in `test_integration.py` + `29` in `test_payment_ledger_integration.py`) with 0 import or syntax errors.
- **Offline Migration & Regression Verification (Executed Locally):**
  - `backend/tests/test_migrations.py` and `backend/tests/test_v41_closure_regressions.py` pass within the **1,031 passed** offline suite.
- **Live PostgreSQL Execution Status:**
  - **Local Host:** **BLOCKED** — Windows service `com.docker.service` is `Stopped` (`open //./pipe/docker_engine: The system cannot find the file specified`), and no local `postgres.exe` / `psql` binary is installed.
  - **GitHub Actions Runner (`postgres-integration` job):** Configured and pushed on `fix/hydrogen-final-v4-1-closure` to trigger automatically on GitHub Actions. Because `adishbr/PauseGuard` is private and `gh` CLI is absent, verify the `postgres-integration` job status on the PR check tab before merging to `main`.

