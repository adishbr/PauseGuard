# PauseGuard V4.1 — Final Release & Demonstration Runbook

**Release Candidate Branch:** `release/pauseguard-v4-1-final`  
**Integration Worktree:** `D:\PauseGuard-Hydrogen-Integration`

---

## 1. Prerequisites & Installation (Windows PowerShell)

```powershell
# 1. Backend Python 3.12 virtual environment
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt

# 2. Frontend Node dependencies
cd frontend
npm ci
cd ..
```

---

## 2. Running the Application

### Mode A — Standalone Mock Demo (Vite Middleware Only)
Uses in-process Vite mock middleware (`/__pauseguard/demo/*` and `/api/v2/*`). Supports fictional account registration, 30/45/60s review timer selector, and multi-window demo flows without starting FastAPI.

```powershell
cd frontend
npm run dev
# Open http://127.0.0.1:5173
```

### Mode B — Local FastAPI + React Real-Backend Integration (Loopback Only)
Connects the React frontend to FastAPI (`/api/v2/*` and `/api/v2/ws`) over `127.0.0.1`.

**Terminal 1 — FastAPI Backend (`127.0.0.1:8000`):**
```powershell
cd backend
$env:PAUSEGUARD_ENVIRONMENT = 'local'
$env:PAUSEGUARD_MODE = 'mock'
$env:PAUSEGUARD_ALLOW_DEMO_AUTH = 'true'
$env:PAUSEGUARD_ALLOW_DEMO_ADMIN = 'true'
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Terminal 2 — Vite Frontend (`127.0.0.1:5173`):**
```powershell
cd frontend
$env:VITE_USE_REAL_BACKEND = 'true'
$env:PAUSEGUARD_BACKEND_URL = 'http://127.0.0.1:8000'
npm run dev
```

### Mode C — Authorized Disposable PostgreSQL Integration Suite (Illustrative Local / Executed in CI)
Requires a running disposable local PostgreSQL instance on `127.0.0.1:5432` with a database prefixed `pauseguard_test_`:

```powershell
$env:PAUSEGUARD_POSTGRES_TEST_AUTHORIZED = 'true'
$env:PAUSEGUARD_POSTGRES_TEST_URL = 'postgresql+psycopg2://postgres@127.0.0.1:5432/pauseguard_test_ci'
$env:PAUSEGUARD_POSTGRES_TEST_PASSWORD = 'ci_only_disposable_password'
.\.venv\Scripts\python.exe -m pytest -c backend/pytest_integration.ini backend/tests_integration -v
```

---

## 3. Ten-Step Demonstration Script

1. **Payer Login:** Open `http://127.0.0.1:5173/payer/login` and click **Open sample payer** (issues a loopback-only session via `POST /api/v2/demo/session`).
2. **Suspicious Payment Creation:** Keep the prefilled high-risk scenario (`₹55,000`, `Willow Supplies`, `KYC or verification request`) and click **Check payment**. Observe transition to **Waiting for your guardian** (`AWAITING_GUARDIAN`) and explainable risk reason codes.
3. **Guardian Notification (Separate Window/Profile):** Open `http://127.0.0.1:5173/guardian/login` in a second browser profile, click **Open sample guardian**, and click **Open review** when surfaced via `/api/v2/guardian/dashboard` / WebSocket. Verify privacy redaction (no amount, payee name, or purpose shown).
4. **Guardian Approval / Rejection:**
   - Click **Approve review** → verify Payer window updates via WebSocket to **Ready for your confirmation** (`READY_TO_EXECUTE`) without auto-executing.
   - Or click **Reject payment** → verify both windows transition to terminal **Payment rejected** (`REJECTED`).
5. **Payer Final Confirmation:** After guardian approval, click **Confirm simulated payment** in the Payer window → verify **Simulated payment completed** (`EXECUTED`).
6. **Timeout Fallback (30s):** Create another high-risk payment and wait 30 seconds without guardian action → verify automatic transition to **Review window closed** (`AWAITING_FALLBACK_REVIEW`) with zero funds debited.
7. **Safe-Lock:** Navigate to `/payer/safety`, enable **Safe-Lock**, and save (`POST /api/v2/safe-lock`) → verify payment creation/confirmation is blocked (`423 Locked`).
8. **Audit Verification:** Query `GET /api/v2/payments/{payment_id}/events` (or inspect via Admin Sandbox) to view the SHA-256 hash-chained (`prev_hash` → `event_hash`) audit trail.
9. **Risk Advisory & Policy Lab:** Call `POST /api/v2/risk/advice` (advisory signals with `can_authorize_payment: false`) and `POST /api/v2/policy-lab/simulate` (comparing Baseline A, Baseline B, and PauseGuard Policy C on held-out synthetic test scenarios).
10. **Admin Razorpay Test Mode:** Open `http://127.0.0.1:5173/admin/login` (isolated merchant checkout sandbox under `/api/v2/sandbox/razorpay/*`, completely separate from the mock UPI P2P ledger).
