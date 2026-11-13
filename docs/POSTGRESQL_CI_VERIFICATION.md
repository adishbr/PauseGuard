# PostgreSQL Integration & CI Verification Report (V4.1)

**Branch:** `feat/razorpay-test-mode-completion` (PR #27 targeting `main`)  
**Worktree:** `D:\PauseGuard-Hydrogen-Integration` (`D:\PauseGuard` untouched)

---

## 1. Root Cause of Concurrent Audit Hash-Chain Failure (`43479596624` / `43480031183`)

GitHub Actions `postgres-integration` runs `43479596624` (`push`) and `43480031183` (`pull_request`) failed exclusively in `TestSecurityHardeningPersistence::test_concurrent_audit_writes_hash_chain_continuity_with_advisory_lock` (`70 passed, 1 failed`):
- `AuditEvent.created_at` defaulted via PostgreSQL `func.now()`, which evaluates to `transaction_timestamp()` (fixed at **transaction BEGIN**, before acquiring `pg_advisory_xact_lock(74920491823)`), while `AuditEvent.id` was a random UUIDv4.
- When Transaction T1 started earlier (`t1`) than Transaction T2 (`t2 > t1`) and T2 acquired `pg_advisory_xact_lock` first, T2 wrote the genesis row with timestamp `t2`, then T1 linked `prev_hash = T2.event_hash` with earlier timestamp `t1 < t2`.
- Both `DurablePaymentEngine._append_audit_event` (`ORDER BY created_at DESC, id DESC`) and `verify_audit_chain` / integration assertions (`ORDER BY created_at ASC, id ASC`) ordered by `(created_at, id)`, causing subsequent writers to pick T2 again instead of T1 and genuinely **forking the hash chain** under concurrency.

*(Prior PR #20 / `test_safe_lock_remains_enforced_after_timeout` fixes from `release/pauseguard-v4-1-final` remain intact: removal of duplicate unimported test in `test_integration.py`, sync of `0003_razorpay_merchant_sandbox.py`, and `TestGuardianDeadlineTransaction` repairs.)*

---

## 2. Authoritative `append_seq` Audit Ordering Repair (`ef70296` / `4b9f262`)

1. **[backend/app/models/audit.py](file:///D:/PauseGuard-Hydrogen-Integration/backend/app/models/audit.py):** Added `AUDIT_EVENTS_APPEND_SEQ = Sequence("audit_events_append_seq", start=1, increment=1, metadata=Base.metadata)`, `append_seq: Mapped[int]` (`BigInteger`, `nullable=False`), `CheckConstraint("append_seq > 0", name="ck_audit_events_positive_append_seq")`, and unique `Index("ix_audit_events_append_seq", "append_seq", unique=True)`.
2. **[backend/app/services/durable_payment_engine.py](file:///D:/PauseGuard-Hydrogen-Integration/backend/app/services/durable_payment_engine.py) & [foundation_queries.py](file:///D:/PauseGuard-Hydrogen-Integration/backend/app/services/foundation_queries.py):**
   - Acquired `pg_advisory_xact_lock(74920491823)` before allocating `nextval('audit_events_append_seq')` (with `last_seq + 1` fallback on non-PostgreSQL/mock sessions).
   - Ordered tail lookup in `_append_audit_event`, chain reads in `get_payment_events` / `audit_events_for_payment`, and verification in `verify_audit_chain` strictly by `AuditEvent.append_seq` (tolerating positive monotonic gaps on rolled-back transactions while verifying genesis, links, and recomputed SHA-256 hashes).
3. **[backend/migrations/versions/0004_audit_append_sequence.py](file:///D:/PauseGuard-Hydrogen-Integration/backend/migrations/versions/0004_audit_append_sequence.py) & [backend/tests_integration/migrations/versions/0004_audit_append_sequence.py](file:///D:/PauseGuard-Hydrogen-Integration/backend/tests_integration/migrations/versions/0004_audit_append_sequence.py):** Added nullable column, fail-closed cryptographic chain backfill validator (`reconstruct_verified_chain_order` rejecting forks/cycles/orphans/multiple geneses), check constraint, `NOT NULL`, unique index, and aligned `audit_events_append_seq` sequence via `setval`.
4. **Regression Coverage (`test_migrations.py`, `test_phase4_durable_ledger.py`, `test_payment_ledger_integration.py`):** Added unit tests for `0004` chain reconstruction and fork/cycle/orphan rejection plus PostgreSQL tests for 8-thread concurrent hash chaining, 10x8 repeated rounds, inverted transaction-start timestamps, transaction rollbacks, fresh-session DB tamper detection, and concurrent mixed payment lifecycles.

---

## 3. Verified Execution Evidence

- **GitHub Actions `postgres:16` Integration CI (Commit `4b9f262`, Both Triggers Green):**
  - `pull_request` run `43483777510`: `Python tests` **success**; `PostgreSQL integration tests` **76 passed in 3.82s** (**success**).
  - `push` run `43483764496`: `Python tests` **success**; `PostgreSQL integration tests` **76 passed in 4.96s** (**success**).
- **Local Offline Collection & Migration Verification:**
  - `pytest --collect-only -c backend/pytest_integration.ini backend/tests_integration -q`: **76 tests collected in 0.56s** (`40` in `test_integration.py` + `36` in `test_payment_ledger_integration.py`).
  - `pytest tests backend/tests -q`: **1,035 passed, 1 warning, 52 subtests passed in 14.31s** (includes `test_migrations.py` & `test_v41_closure_regressions.py`).
- **Local Host Docker Note:** Windows service `com.docker.service` is `Stopped` and no local `postgres` / `psql` binary is installed, so live PostgreSQL 16 verification was executed via the authoritative GitHub Actions `postgres:16` service container.

