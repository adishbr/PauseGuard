# PauseGuard V2 — Backend Architecture & Implementation Plan (Revised)

**Author:** Komal (Member 1 — Core Backend & Integration Lead)  
**Branch:** `feature/komal-backend`  
**Date:** 2026-11-10  
**Database Decision:** **Supabase PostgreSQL** (replaces local SQLite)  
**Status:** 🟡 AWAITING APPROVAL — Planning artifact only. No application code, package installations, cloud resources, or migrations executed until approved.

---

## 1. Goal Description & Background Context

PauseGuard is a risk-adaptive intervention layer for Authorized Push Payment (APP) fraud in India. It acts on a mock-rail payment architecture where the backend is the **sole execution authority**. AI models and call providers provide **advisory signals only** and never possess execution privileges.

This revised plan pivots the persistence architecture from local SQLite to **Supabase PostgreSQL**. While SQLite is simple for local toys, financial safety invariants—specifically row-level locking (`SELECT ... FOR UPDATE`), transaction-bound atomic ledger debits, strict uniqueness constraints under concurrent load, and atomic audit persistence—require an ACID-compliant relational database engine.

This plan details the complete backend implementation strategy, canonical V2 contracts, database schema, Alembic migration pipeline, concurrency model, and full eight-module roadmap.

---

## 2. User Review Required & Critical Alerts

> [!IMPORTANT]
> **Database Architecture Decision:** We are adopting **Supabase PostgreSQL** as the primary authoritative database. Migrations will be managed strictly via **Alembic**, not `SQLAlchemy.metadata.create_all()`. Application startup must never alter production/cloud schemas implicitly.

> [!WARNING]
> **Guardian Concurrency Correction (PAY-06):** In the V2 state machine, neither `READY_TO_EXECUTE` (the target of guardian approval) nor `AWAITING_FALLBACK_REVIEW` (the target of timeout activation) is a terminal state. Concurrency tests must verify that exactly one authoritative transition leaves `AWAITING_GUARDIAN`, without incorrectly asserting that every outcome must be terminal.

> [!CAUTION]
> **Zero Real Money Invariant:** PauseGuard is a mock prototype. Account balances, transfers, and ledger debits operate exclusively on mock records. The planned Razorpay integration is strictly an optional **Test Mode (`rzp_test_...`) sandbox** for admin-only merchant checkout demonstrations and must never handle real funds.

---

## 3. Current Backend Implementation Inventory

### 3.1 Present (Verified)

| Component | Path / Location | Verified State |
|---|---|---|
| Python Runtime | `backend/.venv/` | Python 3.12.10 verified |
| Core Frameworks | `.venv/Lib/site-packages` | FastAPI 0.162.2, SQLAlchemy 2.1.8, Pydantic 2.14.3, Uvicorn 0.54.0 |
| Testing Tools | `.venv/Lib/site-packages` | pytest 9.2.0, HTTPX 0.28.1 |
| Config & Async | `.venv/Lib/site-packages` | python-dotenv 1.2.4, websockets 17.4 |
| Backend Scaffolding | `backend/app/{api,auth,integrations,models,policies,services}/` | Directories exist with `.gitkeep` |
| Migrations Scaffolding | `backend/migrations/` | Directory exists with `.gitkeep` |
| Safety & Intelligence Scaffolding | `safety/`, `intelligence/`, `synthetic_data/` | Directories exist with `.gitkeep` |
| Git Configuration | `.gitignore` | Ignores `.env`, `.env.*`, `__pycache__`, `*.db` |

### 3.2 Missing (To Be Implemented)

> [!CAUTION]
> Zero application source code exists in the repository. All subdirectories contain only `.gitkeep`.

1. **Database Drivers & Migration Tooling:** `psycopg2-binary` (or `psycopg[binary]`) and `alembic` are **not installed** in `.venv`.
2. **Configuration & Credentials:** No `backend/requirements.txt`, no `.env.example`, no `alembic.ini`.
3. **Application Entrypoint:** No `backend/app/main.py`.
4. **Database & ORM Layer:** No `backend/app/models/database.py`, `payment.py`, `account.py`, `ledger.py`, `audit.py`.
5. **Alembic Environment:** No `backend/migrations/env.py`, `script.py.mako`, or migration versions.
6. **Domain Services:** No state machine, deterministic policy engine, guardian coordinator, or mock ledger service.
7. **API Routers:** No `backend/app/api/v2_payments.py`.
8. **Test Suite:** No test files in `tests/unit/`, `tests/integration/`, `tests/security/`.

---

## 4. Canonical V2 API Specification & Invariants (Cited)

### 4.1 Frozen V2 Payment State Machine

Canonical statuses from [PAYMENT_STATES_V2.md](file:///d:/PauseGuard/docs/PAYMENT_STATES_V2.md) L5-11:
- `CREATED`: Initial state at API ingestion.
- `AWAITING_WARNING`: Payer must acknowledge friction/warning.
- `AWAITING_STEP_UP`: Strong independent verification required (defined in enum; deferred route).
- `AWAITING_GUARDIAN`: Awaiting enrolled guardian decision until server UTC deadline.
- `AWAITING_FALLBACK_REVIEW`: Reached after guardian timeout; AI advice does NOT execute payment.
- `READY_TO_EXECUTE`: All required checks passed; awaiting payer final confirmation.
- **Terminal States (Irreversible):** `EXECUTED`, `REJECTED`, `CANCELLED`, `EXPIRED`, `FAILED`.

```mermaid
stateDiagram-v2
    [*] --> CREATED: POST /api/v2/payments
    CREATED --> READY_TO_EXECUTE: Tier 0 (Low Risk)
    CREATED --> AWAITING_WARNING: Tier 1 (Warn)
    CREATED --> AWAITING_GUARDIAN: Tier 3 (High Risk + Enrolled Guardian)
    CREATED --> AWAITING_FALLBACK_REVIEW: Tier 3 (High Risk + No Guardian)
    CREATED --> REJECTED: Hard Block (Registry / Policy)
    
    AWAITING_WARNING --> READY_TO_EXECUTE: Payer Acknowledges
    AWAITING_WARNING --> CANCELLED: Payer Cancels
    
    AWAITING_GUARDIAN --> READY_TO_EXECUTE: Guardian Approves (within 30s)
    AWAITING_GUARDIAN --> REJECTED: Guardian Rejects (within 30s)
    AWAITING_GUARDIAN --> CANCELLED: Payer Cancels
    AWAITING_GUARDIAN --> AWAITING_FALLBACK_REVIEW: Deadline Exceeded (30s Timeout)
    
    AWAITING_FALLBACK_REVIEW --> READY_TO_EXECUTE: Independent Evidence Satisfies Policy
    AWAITING_FALLBACK_REVIEW --> REJECTED: Coercion Confirmed / Denied
    AWAITING_FALLBACK_REVIEW --> CANCELLED: Payer Cancels
    AWAITING_FALLBACK_REVIEW --> EXPIRED: Session Expires
    
    READY_TO_EXECUTE --> EXECUTED: POST /confirm (Payer Confirm + Atomic Ledger Debit)
    READY_TO_EXECUTE --> CANCELLED: Payer Cancels
    READY_TO_EXECUTE --> REJECTED: Hard Risk Triggered at Confirm
    READY_TO_EXECUTE --> FAILED: Safe-Lock Active / Insufficient Balance
    
    EXECUTED --> [*]
    REJECTED --> [*]
    CANCELLED --> [*]
    EXPIRED --> [*]
    FAILED --> [*]
```

### 4.2 Canonical V2 API Endpoints

Source: [API_CONTRACT_V2.md](file:///d:/PauseGuard/docs/API_CONTRACT_V2.md) L5-25  
Base URL: `/api/v2`. Currency: `amount_paise` (integer).

| Method | Endpoint | Allowed Roles | Description |
|---|---|---|---|
| `GET` | `/health` | Public | System health and database connectivity probe |
| `GET` | `/profile` | Authenticated | Payer profile, notification preferences, account balance |
| `POST` | `/payments` | Payer | Create payment with `idempotency_key`, run deterministic policy |
| `GET` | `/payments/{id}` | Payer, Assigned Guardian | Fetch payment status (Guardian receives redacted view) |
| `POST` | `/payments/{id}/warning/acknowledge` | Payer | Transition `AWAITING_WARNING` → `READY_TO_EXECUTE` |
| `POST` | `/payments/{id}/guardian/decision` | Assigned Guardian | Approve (`READY_TO_EXECUTE`) or Reject (`REJECTED`) within window |
| `POST` | `/payments/{id}/fallback/activate` | Payer | Transition `AWAITING_GUARDIAN` → `AWAITING_FALLBACK_REVIEW` after deadline |
| `POST` | `/payments/{id}/cancel` | Payer | Cancel pending non-terminal payment (`CANCELLED`) |
| `POST` | `/payments/{id}/confirm` | Payer | Final execution: atomic ledger debit, recheck Safe-Lock/hard blocks |
| `POST` | `/safe-lock` | Payer | Toggle Safe-Lock flag (`is_locked: boolean`) |
| `GET` | `/audit/verify` | Admin | Verify cryptographic SHA-256 integrity of audit hash chain |
| `POST` | `/integrations/razorpay/create-order` | Admin | (Future Phase) Create Razorpay test-mode sandbox order |

### 4.3 Schemas

#### Payment Creation Request
Source: [API_CONTRACT_V2.md](file:///d:/PauseGuard/docs/API_CONTRACT_V2.md) L27-34
```json
{
  "beneficiary_id": "supplier_new",
  "amount_paise": 5500000,
  "purpose": "kyc_verification",
  "idempotency_key": "new_unique_key_001"
}
```

#### Payer Response View
Source: [API_CONTRACT_V2.md](file:///d:/PauseGuard/docs/API_CONTRACT_V2.md) L38-50
```json
{
  "id": "pg_01J...",
  "status": "AWAITING_GUARDIAN",
  "tier": 3,
  "risk_score": 100,
  "reason_codes": [
    "RC_NEW_BENEFICIARY",
    "RC_LARGE_DEVIATION",
    "RC_COERCION_PURPOSE",
    "RC_CUSTOMER_ALERT_PREFERENCE"
  ],
  "amount_paise": 5500000,
  "beneficiary_id": "supplier_new",
  "purpose": "kyc_verification",
  "guardian_deadline": "2026-11-10T10:00:30+00:00",
  "version": 1
}
```

#### Guardian Redacted Response View
Source: [API_CONTRACT_V2.md](file:///d:/PauseGuard/docs/API_CONTRACT_V2.md) L53-54 & [PRIVACY_SECURITY.md](file:///d:/PauseGuard/docs/PRIVACY_SECURITY.md) L4-5
```json
{
  "id": "pg_01J...",
  "status": "AWAITING_GUARDIAN",
  "tier": 3,
  "guardian_deadline": "2026-11-10T10:00:30+00:00",
  "summary_message": "A security review is requested for an unusual transaction."
}
```
*Note: Payer identity, beneficiary details, exact `amount_paise`, and transfer purpose are strictly omitted from the guardian payload.*

---

## 5. Supabase PostgreSQL Architecture & Persistence Model

### 5.1 Connection Architecture & Credentials

1. **Environment Variables:** Credentials reside solely in `backend/.env` (excluded by Git via `.gitignore`).
   ```bash
   # Transaction Pooler (Supavisor / pgbouncer) - Port 6543 (Recommended for FastAPI async/worker scaling)
   DATABASE_URL=postgresql://postgres.[PROJECT_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require
   
   # Direct Connection - Port 5432 (For Alembic DDL migrations)
   DIRECT_DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[PROJECT_REF].supabase.co:5432/postgres?sslmode=require
   
   # Test Database (Local Postgres or isolated test schema)
   TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/pauseguard_test
   ```
2. **Prepared Statements Handling:** When connecting through Supabase's transaction pooler (port 6543), SQLAlchemy's engine must be configured with `connect_args={"prepare_threshold": None}` or use session mode to prevent prepared-statement collision across multiplexed connections.
3. **No Frontend Direct Access:** Supabase's PostgREST public API, auto-generated GraphQL, and client-side database keys are **not used** for payment execution. All database writes flow through the authenticated FastAPI application.

### 5.2 Relational Data Model (DDL Specifications)

```mermaid
erDiagram
    USERS ||--o{ ACCOUNTS : owns
    USERS ||--o{ PAYMENTS : initiates
    ACCOUNTS ||--o{ LEDGER_ENTRIES : balance_entries
    PAYMENTS ||--o{ LEDGER_ENTRIES : generates
    PAYMENTS ||--o{ AUDIT_EVENTS : logs
    USERS ||--o{ IDEMPOTENCY_RECORDS : submits

    USERS {
        uuid id PK
        string role "payer, guardian, analyst, admin"
        string full_name
        string profile_type "personal, professional, small_business, enterprise"
        int notification_preference_paise
        boolean is_safe_locked
        datetime created_at
    }

    ACCOUNTS {
        uuid id PK
        uuid user_id FK
        bigint balance_paise "CHECK balance_paise >= 0"
        string currency "INR"
        int version
        datetime updated_at
    }

    PAYMENTS {
        string id PK "pg_..."
        uuid payer_id FK
        string beneficiary_id
        bigint amount_paise "CHECK amount_paise > 0"
        string purpose
        string status "V2 Enum"
        int tier "0, 1, 2, 3"
        int risk_score
        jsonb reason_codes
        string idempotency_key UK
        uuid assigned_guardian_id FK
        datetime guardian_deadline
        int version "Optimistic lock"
        datetime created_at
        datetime updated_at
    }

    LEDGER_ENTRIES {
        uuid id PK
        string payment_id FK
        uuid account_id FK
        bigint amount_paise
        string entry_type "DEBIT, CREDIT"
        string idempotency_key UK
        datetime created_at
    }

    AUDIT_EVENTS {
        uuid id PK
        string payment_id FK
        string event_type
        uuid actor_id
        string actor_role
        string prev_hash
        string event_hash
        jsonb payload_json
        datetime created_at
    }

    IDEMPOTENCY_RECORDS {
        string key PK
        uuid caller_id
        string endpoint
        string request_hash
        int response_status
        jsonb response_body
        datetime created_at
    }
```

### 5.3 Alembic Migration Strategy

1. **Configuration:** `alembic.ini` configured in `backend/` pointing to `migrations/`.
2. **Dynamic Target Metadata:** `backend/migrations/env.py` imports `Base.metadata` from `app.models.database`.
3. **Execution Command:**
   - Generate migration: `alembic revision --autogenerate -m "create_v2_core_tables"`
   - Apply migration: `alembic upgrade head`
4. **Zero `create_all()` in Code:** Application initialization in `main.py` will verify connectivity (`SELECT 1`), but will never run `Base.metadata.create_all(bind=engine)`. Migrations remain strictly auditable in version control.

### 5.4 Transactional Guarantees & Row Locking

For payment confirmation (`POST /payments/{id}/confirm`):
```python
# Atomic Mock Ledger Execution Pattern
with session.begin():
    # 1. Lock payment record
    payment = session.query(Payment).filter(
        Payment.id == payment_id
    ).with_for_update().one()
    
    # 2. Invariant: Status must be READY_TO_EXECUTE
    if payment.status != PaymentStatus.READY_TO_EXECUTE:
        raise InvalidStateTransitionError(f"Cannot confirm from {payment.status}")
        
    # 3. Invariant: Recheck Safe-Lock live
    user = session.query(User).filter(User.id == payment.payer_id).one()
    if user.is_safe_locked:
        payment.status = PaymentStatus.FAILED
        # Audit failure and abort
        ...
        return
        
    # 4. Lock payer account row
    account = session.query(Account).filter(
        Account.user_id == payment.payer_id
    ).with_for_update().one()
    
    # 5. Invariant: Check sufficient mock balance
    if account.balance_paise < payment.amount_paise:
        payment.status = PaymentStatus.FAILED
        ...
        return
        
    # 6. Execute atomic balance debit
    account.balance_paise -= payment.amount_paise
    account.version += 1
    
    # 7. Record immutable ledger entry
    ledger_entry = LedgerEntry(
        payment_id=payment.id,
        account_id=account.id,
        amount_paise=payment.amount_paise,
        entry_type="DEBIT",
        idempotency_key=f"debit_{payment.id}"
    )
    session.add(ledger_entry)
    
    # 8. Transition payment state
    payment.status = PaymentStatus.EXECUTED
    payment.version += 1
    
    # 9. Append atomic audit event
    audit_service.append_event_in_tx(
        session=session,
        payment_id=payment.id,
        event_type="PAYMENT_EXECUTED",
        actor=current_user
    )
# End of transaction: All rows commit atomically or roll back on error
```

---

## 6. Corrected Guardian Concurrency & Timeout Logic

### 6.1 State Machine Non-Terminal Invariant

In V2, the two competing outcomes of `AWAITING_GUARDIAN` are:
1. **Guardian Approval:** Target state is `READY_TO_EXECUTE` (**non-terminal**; payer confirmation still required).
2. **Guardian Timeout:** Target state is `AWAITING_FALLBACK_REVIEW` (**non-terminal**; fallback review options available).
*(Rejection transitions to `REJECTED`, which is terminal).*

### 6.2 Race Condition Resolution

When a guardian decision arrives at or near the 30-second boundary while a timeout transition is triggered:
- The database transaction obtains a row lock: `SELECT * FROM payments WHERE id = :id FOR UPDATE`.
- The transaction evaluates the condition:
  - If `now() <= payment.guardian_deadline` and `payment.status == 'AWAITING_GUARDIAN'`: Approval succeeds, transitioning to `READY_TO_EXECUTE`.
  - If `now() > payment.guardian_deadline`: Approval is rejected with HTTP 422 (`RC_GUARDIAN_DEADLINE_EXPIRED`). The record transitions to `AWAITING_FALLBACK_REVIEW`.
- Because row locking serializes execution, **exactly one outcome transitions the record**. The subsequent request encounters a state that is no longer `AWAITING_GUARDIAN` and is safely rejected.

---

## 7. Complete Eight-Module Integration Roadmap

The PauseGuard architecture consists of eight distinct modules distributed across team ownership:

```mermaid
flowchart LR
    subgraph CoreBackend["Core Backend (Komal)"]
        M1["Module 1: Core API & Auth"]
        M2["Module 2: State Machine & Policy"]
        M3["Module 3: Guardian Escalation"]
    end

    subgraph Frontend["Frontend Experience (Adish)"]
        M4["Module 4: Payer & Guardian UI"]
    end

    subgraph Intelligence["Intelligence & Lab (Gowtham)"]
        M5["Module 5: Behavioral Intelligence"]
        M6["Module 6: Mule Graph & Policy Lab"]
    end

    subgraph Safety["Safety & Auditing (Jeevan)"]
        M7["Module 7: Anti-Smurf & Safe-Lock"]
        M8["Module 8: Audit Chain & Recovery"]
    end

    M1 --> M2 --> M3
    M1 <--> M4
    M2 <--> M5
    M2 <--> M6
    M2 <--> M7
    M2 --> M8
```

| Module | Name & Scope | Lead Owner | Integration Points |
|---|---|---|---|
| **M1** | **Core API & Authorization Middleware**<br>`/api/v2/*`, bearer token role parsing, PostgreSQL connection pooler, request validation, Pydantic DTOs. | **Komal** | Serves Adish's UI, coordinates auth boundaries for all modules. |
| **M2** | **Payment State Machine & Deterministic Policy Engine**<br>Frozen V2 states, transitions, 4-tier risk classification, row-level locking, atomic mock ledger. | **Komal** | Evaluates M5 signals, executes M7 Safe-Lock, feeds M8 audit log. |
| **M3** | **Guardian Escalation & Call Simulation**<br>30s server deadline, redacted guardian notifications, in-app call simulator status endpoints. | **Komal** (with Adish) | Feeds Adish's dual-screen guardian view; respects 30s timeout rules. |
| **M4** | **Payer & Guardian User Interface**<br>React/TypeScript/Tailwind responsive screens, 30s countdown display, dual-browser demo, WebSocket/poll updates. | **Adish** | Consumes Komal's `/api/v2` endpoints; renders Gowtham's explanations. |
| **M5** | **Behavioral Intelligence & Anomaly Detection**<br>Baseline transaction models, typed `RiskSignals` payload, heuristic coercion analysis. Advisory only. | **Gowtham** | Ingested by Komal's policy engine before tier assignment. |
| **M6** | **Mule Account Graph & Synthetic Policy Lab**<br>NetworkX graph heuristics, synthetic benchmarking dataset, policy tuning simulator. | **Gowtham** | Offline analysis and test fixtures for deterministic policy validation. |
| **M7** | **Safety Interventions: Anti-Smurfing, Purpose & Safe-Lock**<br>Rolling velocity accumulator (5-transfer anti-smurf), purpose challenge classifier, Safe-Lock toggle. | **Jeevan** | Live recheck in Komal's final confirmation transaction. |
| **M8** | **Tamper-Evident Audit Chain, Recovery Assist & Merchant Sandbox**<br>SHA-256 hash chaining, verified incident export packet, Razorpay Test Mode checkout adapter. | **Jeevan** (with Komal) | Komal provides DB audit table; Jeevan implements chain verification. |

### 7.1 Optional Razorpay Test Mode Merchant Sandbox

- **Role:** Admin-only demonstration of merchant gateway checkout (separate from mock P2P transfers).
- **Configuration:** Restricted to Razorpay Test Mode keys (`RZP_TEST_KEY_ID`, `RZP_TEST_KEY_SECRET`).
- **Isolation:** Placed in `backend/app/integrations/razorpay_sandbox.py`.
- **Constraint:** Completely disabled for standard payer flows. No real money or bank accounts.

---

## 8. First Vertical-Slice Milestone

### 8.1 Scope of Milestone 1
Deliver a fully functional, tested, and verifiable mock payment cycle using Supabase PostgreSQL:
1. Environment configuration (`.env` loading, connection strings).
2. Alembic migration for core tables (`users`, `accounts`, `payments`, `ledger_entries`, `audit_events`, `idempotency_records`).
3. Core routes: `/health`, `/profile`, `/payments`, `/payments/{id}`, `/payments/{id}/guardian/decision`, `/payments/{id}/fallback/activate`, `/payments/{id}/confirm`, `/safe-lock`, `/audit/verify`.
4. Automated test suite executing against PostgreSQL proving idempotency, row-locking, and state immutability.

### 8.2 Proposed File Inventory (Milestone 1)

```
backend/
├── alembic.ini                         # [NEW] Alembic configuration
├── requirements.txt                    # [NEW] Pinned dependencies (including psycopg2-binary, alembic)
├── migrations/
│   ├── env.py                          # [NEW] Alembic target metadata & DB URL loader
│   ├── script.py.mako                  # [NEW] Migration script template
│   └── versions/                       # [NEW] Migration versions
│       └── 001_initial_v2_schema.py    # [NEW] Initial DDL migration
├── app/
│   ├── __init__.py                     # [NEW] Package marker
│   ├── main.py                         # [NEW] FastAPI factory, lifespan check, CORS, router inclusion
│   ├── config.py                       # [NEW] Pydantic Settings (DATABASE_URL, DIRECT_DATABASE_URL)
│   ├── api/
│   │   ├── __init__.py                 # [NEW] Package marker
│   │   └── v2_payments.py              # [NEW] /api/v2/* route handlers
│   ├── auth/
│   │   ├── __init__.py                 # [NEW] Package marker
│   │   └── bearer.py                   # [NEW] Mock Bearer token validator -> UserContext
│   ├── models/
│   │   ├── __init__.py                 # [NEW] Package marker
│   │   ├── database.py                 # [NEW] SQLAlchemy sessionmaker, engine, Base
│   │   ├── user.py                     # [NEW] User ORM model
│   │   ├── account.py                  # [NEW] Account ORM model (balance_paise)
│   │   ├── payment.py                  # [NEW] Payment ORM model (V2 statuses)
│   │   ├── ledger.py                   # [NEW] LedgerEntry ORM model
│   │   ├── audit.py                    # [NEW] AuditEvent ORM model
│   │   └── schemas.py                  # [NEW] Pydantic v2 Request/Response schemas
│   ├── policies/
│   │   ├── __init__.py                 # [NEW] Package marker
│   │   └── deterministic.py            # [NEW] 4-Tier deterministic policy evaluator
│   └── services/
│       ├── __init__.py                 # [NEW] Package marker
│       ├── state_machine.py            # [NEW] Transition engine with DB row-locking
│       ├── ledger.py                   # [NEW] Atomic debit & balance enforcement
│       ├── guardian.py                 # [NEW] Deadline & redaction logic
│       ├── safe_lock.py                # [NEW] Safe-Lock query & toggle
│       └── audit.py                    # [NEW] SHA-256 hash chaining service
tests/
├── conftest.py                         # [NEW] Test database fixtures, isolated transactions
├── unit/
│   ├── test_state_machine.py           # [NEW] Valid & invalid state transitions
│   ├── test_deterministic_policy.py    # [NEW] Tier 0-3 policy evaluations
│   └── test_audit_hash.py              # [NEW] Cryptographic hash verification
├── integration/
│   ├── test_pg_payment_lifecycle.py    # [NEW] Full create -> guardian -> confirm cycle
│   ├── test_idempotency_postgres.py    # [NEW] Duplicate key & conflict tests
│   └── test_guardian_timeout_pg.py     # [NEW] Deadline expiry & fallback activation
└── security/
    ├── test_role_authorization.py      # [NEW] Actor segregation & 403 checks
    ├── test_guardian_redaction.py      # [NEW] Privacy field scrubbing assertions
    └── test_concurrency_postgres.py    # [NEW] Real multi-threaded DB row-lock verification
```

---

## 8. Dependencies & Driver Setup Plan

### 8.1 New Packages to Install in `.venv`

| Package | Pinned Version | Rationale |
|---|---|---|
| `psycopg2-binary` | `2.9.10` | Standard, robust synchronous PostgreSQL driver for SQLAlchemy |
| `alembic` | `1.15.1` | Database migration management |
| `pydantic-settings`| `2.8.1` | Clean environment variable parsing with validation |

### 8.2 Updated `backend/requirements.txt` Specification
```txt
fastapi==0.162.2
uvicorn[standard]==0.54.0
sqlalchemy==2.1.8
psycopg2-binary==2.9.10
alembic==1.15.1
pydantic==2.14.3
pydantic-settings==2.8.1
python-dotenv==1.2.4
httpx==0.28.1
pytest==9.2.0
websockets==17.4
pyyaml==6.0.3
```

---

## 9. Verification & Acceptance Test Suite

### 9.1 Test Execution Matrix

All tests run via `python -m pytest tests/` against a real PostgreSQL instance (isolated test database or schema).

| Category | Test Function | Scenario & Security Invariant | Expected Outcome |
|---|---|---|---|
| **Idempotency** | `test_payment_creation_idempotency` | POST `/payments` twice with same `idempotency_key` and payload | Returns HTTP 200 with identical payment record; single DB row created. |
| **Idempotency** | `test_payment_creation_conflict` | POST `/payments` with same key but different `amount_paise` | Returns HTTP 409 Conflict. |
| **Idempotency** | `test_confirm_double_debit_protection` | Repeated POST `/confirm` calls with network retry simulation | Balance debited exactly once; second call returns already-executed status. |
| **Auth & Privacy** | `test_unauthorized_guardian_access` | Guardian A requests `/payments/{id}` for payment assigned to Guardian B | Returns HTTP 403 Forbidden. |
| **Auth & Privacy** | `test_guardian_payload_scrubbing` | Assigned guardian calls GET `/payments/{id}` | Response strictly omits `amount_paise`, `beneficiary_id`, `purpose`. |
| **Terminal States**| `test_executed_immutability` | Attempt any transition on an `EXECUTED` payment | Returns HTTP 409/422; state remains `EXECUTED`. |
| **Terminal States**| `test_rejected_immutability` | Malicious client attempts approve/confirm on `REJECTED` payment | Returns HTTP 409/422; state remains `REJECTED`. |
| **Concurrency** | `test_guardian_approve_vs_timeout_race` | Simultaneous guardian approval and fallback activation threads | Exactly one transition succeeds (`READY_TO_EXECUTE` or `AWAITING_FALLBACK_REVIEW`). |
| **Concurrency** | `test_concurrent_confirm_debit_lock` | Concurrent confirm calls on same payment using thread pool | Row lock serializes execution; balance decremented exactly once. |
| **Safe-Lock** | `test_safe_lock_enforcement_at_confirm` | User activates Safe-Lock while payment is `READY_TO_EXECUTE` | POST `/confirm` returns HTTP 422; status moves to `FAILED`; balance unchanged. |
| **Audit Chain** | `test_atomic_audit_event_committed` | Verify `audit_events` row existence immediately after `EXECUTED` | Hash chain links to previous event; tampering invalidates chain. |

---

## 10. Team Coordination & Decision Log Update

### 10.1 Joint Approval Requirement (Komal & Adish)
Per [AGENTS.md](file:///d:/PauseGuard/AGENTS.md) L26: **Komal and Adish jointly own and approve any core API and payment-state modifications.**
- Adish will receive the exported `contracts/openapi_v2.json` schema to build the frontend client.
- Mock response payloads and WebSocket event formats must be co-reviewed before frontend wire-up.

### 10.2 Proposed Update to `docs/DECISIONS.md`

> [!NOTE]
> This entry is proposed for team sign-off. It will NOT be written directly to `docs/DECISIONS.md` until reviewed by Komal and Adish.

```markdown
## Approved — 2026-11-10 (PostgreSQL Architecture Update)
- Primary Database: Supabase PostgreSQL replaces local SQLite for authoritative state.
- Migrations: Managed strictly via Alembic; SQLAlchemy create_all() prohibited in application runtime.
- Concurrency Control: PostgreSQL row-level locks (SELECT FOR UPDATE) on accounts and payments.
- Connection Strategy: Transaction pooler (port 6543) for application runtime; direct connection (port 5432) for Alembic migrations.
- Ledger & Audit: Stored in PostgreSQL with ACID transactional consistency; in-memory ledger discarded.
- Merchant Gateway: Razorpay Test Mode sandbox reserved as an optional admin-only demonstration.
```

---

## 11. Explicit Security Risks & Non-Scope Boundaries

1. **Local Demo Auth:** Bearer tokens use a static mapping for prototype testing. Must never be exposed to public networks without proper IAM integration.
2. **Telephony Invariant:** Answering a voice call or pressing a phone keypad is **not payment authorization**. Authorization requires an authenticated, transaction-bound digital signature.
3. **AI Boundary:** AI models provide advisory risk context only. AI output cannot authorize transactions, bypass Safe-Lock, or alter payment states.
4. **No Real Banking Rails:** PauseGuard cannot intercept external UPI transactions or reverse completed interbank settlements.

---

## 12. Summary: Proposed Next Action

Upon your explicit approval of this plan, the execution sequence will be:
1. Initialize `requirements.txt` and install `psycopg2-binary` and `alembic` in `.venv`.
2. Configure Alembic and generate initial migration scripts for Supabase PostgreSQL.
3. Build the core models, state machine, policy engine, and `/api/v2` endpoints.
4. Execute automated integration and concurrency tests, recording actual test runs.
5. Export `openapi_v2.json` for Adish's frontend integration.

**⏸️ STOPPED. Awaiting your approval before any file modifications or package installations.**

