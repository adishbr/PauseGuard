# PostgreSQL Integration & CI Verification Report (V4.1)

**Branch:** `release/pauseguard-v4-1-final`  
**Worktree:** `D:\PauseGuard-Hydrogen-Integration`

---

## 1. Root Cause of Earlier PR #20 Revert (`86c6c71` → `dcfcdec`)

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
3. **[backend/tests_integration/test_payment_ledger_integration.py](file:///D:/PauseGuard-Hydrogen-Integration/backend/tests_integration/test_payment_ledger_integration.py):** Integrated PR #26's 14 `TestGuardianDeadlineTransaction` tests (`9ccc5c0`) and added `test_guardian_cannot_replay_payer_confirm_idempotency_key_in_postgresql` (15 tests total in `TestGuardianDeadlineTransaction`).
4. **[.github/workflows/python-ci.yml](file:///D:/PauseGuard-Hydrogen-Integration/.github/workflows/python-ci.yml):** Restored the isolated `postgres-integration` job using `postgres:16` service container, healthcheck (`pg_isready`), disposable `pauseguard_test_ci` database (`127.0.0.1:5432`), and `python -m pytest -c backend/pytest_integration.ini backend/tests_integration -v`. Added `"integration/**"` and `"release/**"` to `on.push.branches`.

---

## 3. Verification Executed Locally vs. CI Gate

- **Collection & Static Verification (Executed Locally):**
  ```powershell
  python -m pytest --collect-only -c backend/pytest_integration.ini backend/tests_integration -q
  ```
  - **Result:** **70 tests collected in 0.57s** (`42` in `test_integration.py` + `28` in `test_payment_ledger_integration.py`) with 0 import or syntax errors.
- **Offline Migration Verification (Executed Locally):**
  - `backend/tests/test_migrations.py` passes as part of the **1,025 passed** offline suite, verifying `0001`, `0002`, and `0003` revision lineage and DDL operations.
- **Live PostgreSQL Execution Status:**
  - **Local Host:** **BLOCKED** — Windows service `com.docker.service` is `Stopped` (`open //./pipe/docker_engine: The system cannot find the file specified`), launching `Docker Desktop.exe` from this non-elevated shell did not start the daemon, and no local `postgres.exe` / `psql` binary is installed.
  - **GitHub Actions Runner (`postgres-integration` job):** Configured and pushed on `release/pauseguard-v4-1-final`. Because `adishbr/PauseGuard` is a private repository and `gh` CLI is not installed in this environment, the remote GitHub Actions check conclusion must be verified in the GitHub UI before merging into `main`.
