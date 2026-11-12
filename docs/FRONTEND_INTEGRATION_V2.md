# Frontend Integration Guide (V2 API)

Author: Komal (Member 1 — Core Backend & Integration Lead)  
Target Audience: Adish (Member 2 — Frontend Lead) & Teammates  
API Base URL: `http://127.0.0.1:8000/api/v2`  
WebSocket Endpoint: `ws://127.0.0.1:8000/api/v2/ws?token={TOKEN}`  

---

## 1. Prototype Authentication & Demo Tokens

PauseGuard enforces strict server-side authorization. Client-supplied role claims and actor headers are ignored.
For local/test development, authenticate using standard HTTP Authorization Bearer headers:

```http
Authorization: Bearer <TOKEN>
```

| Token | Server-Resolved Role | User ID | Permissions / Capabilities |
|---|---|---|---|
| `demo-token-payer` | `payer` | `00000000-0000-0000-0000-000000000001` | Create payments, view full transactions, acknowledge warnings, confirm execution, cancel, toggle Safe-Lock |
| `demo-token-guardian` | `guardian` | `00000000-0000-0000-0000-000000000002` | View guardian dashboard, approve/reject pending reviews (receives redacted privacy-safe views only) |
| `demo-token-analyst` | `analyst` | `00000000-0000-0000-0000-000000000003` | Access audit chains, run Policy Lab comparative simulations |
| `demo-token-admin` | `admin` | `00000000-0000-0000-0000-000000000004` | Full inspection, checkpoint audit anchors, system health verification |
| `demo-token-other-payer` | `payer` | `00000000-0000-0000-0000-000000000005` | Distinct payer identity for cross-account boundary and isolation testing |

> **Security Note:** In production, synthetic demo tokens fail closed. In local demo mode, requests return `X-Correlation-ID` headers for end-to-end tracing.

---

## 2. API Endpoint Matrix

All currency amounts are strictly integer **`amount_paise`** (₹1.00 = 100 paise). All request models forbid unexpected parameters (`extra="forbid"`).

### 2.1 Payments & State Machine (`/api/v2/payments`)

| Method | Endpoint | Authorized Roles | Description |
|---|---|---|---|
| `POST` | `/api/v2/payments` | `payer` | Create risk-evaluated payment. If Tier 3, starts 30s guardian countdown. |
| `GET` | `/api/v2/payments` | `payer`, `guardian`, `analyst`, `admin` | Paginated payment history (`?limit=20&offset=0`). |
| `GET` | `/api/v2/payments/{id}` | `payer`, `assigned_guardian`, `admin` | View payment. Full view for payer; redacted view for guardian. |
| `GET` | `/api/v2/payments/{id}/events` | `payer`, `assigned_guardian`, `admin` | Audit/lifecycle timeline events for this payment. |
| `GET` | `/api/v2/payments/{id}/risk` | `payer`, `assigned_guardian`, `admin` | Risk explanation (tier, requires_guardian, reasons). |
| `GET` | `/api/v2/payments/{id}/evidence` | `payer`, `analyst`, `admin` | Privacy-minimized redacted evidence packet. |
| `POST` | `/api/v2/payments/{id}/warning/acknowledge` | `payer` | Payer acknowledges Tier 1 warning -> `READY_TO_EXECUTE`. |
| `POST` | `/api/v2/payments/{id}/guardian/decision` | `assigned_guardian` | Guardian submits `APPROVE` or `REJECT` within 30s. |
| `POST` | `/api/v2/payments/{id}/fallback/activate` | `payer` | At/after 30s timeout, payer transitions to fallback review. |
| `POST` | `/api/v2/payments/{id}/cancel` | `payer` | Payer cancels eligible non-terminal payment. |
| `POST` | `/api/v2/payments/{id}/confirm` | `payer` | Payer executes final payment. Atomic ledger debit. |

### 2.2 Account & Ledger (`/api/v2/account`)

| Method | Endpoint | Authorized Roles | Description |
|---|---|---|---|
| `GET` | `/api/v2/account/balance` | Authenticated | Current mock balance in paise and total ledger entries. |

### 2.3 Safe-Lock & Safety Controls (`/api/v2/safe-lock`, `/api/v2/safety`)

| Method | Endpoint | Authorized Roles | Description |
|---|---|---|---|
| `POST` | `/api/v2/safe-lock` | `payer`, `admin` | Engage (`{"is_locked": true}`) or disengage Safe-Lock. |
| `GET` | `/api/v2/safe-lock` | `payer`, `admin` | Inspect current binary Safe-Lock state and version. |
| `POST` | `/api/v2/safety/purpose-challenge` | Authenticated | Detect coercion, threat, or impersonation keywords in purpose. |
| `POST` | `/api/v2/safety/anti-smurfing/check` | Authenticated | Evaluate rapid transfer frequency & structuring structuring limits. |

### 2.4 Audit & Recovery Assist (`/api/v2/audit`, `/api/v2/recovery`)

| Method | Endpoint | Authorized Roles | Description |
|---|---|---|---|
| `GET` | `/api/v2/audit/verify` | Authenticated | Verify cryptographic SHA-256 hash-chain integrity. |
| `POST` | `/api/v2/audit/anchors` | `analyst`, `admin` | Export tamper-evident checkpoint receipt for external anchoring. |
| `GET` | `/api/v2/recovery/guide` | Authenticated | National Cyber Crime 1930 helpline and victim aftercare steps. |

### 2.5 Intelligence & Policy Lab (`/api/v2/risk`, `/api/v2/policy-lab`)

| Method | Endpoint | Authorized Roles | Description |
|---|---|---|---|
| `POST` | `/api/v2/risk/advice` | Authenticated | Compute multidimensional advisory signals (`can_authorize_payment: false`). |
| `POST` | `/api/v2/policy-lab/simulate` | `analyst`, `admin` | Run benchmark comparing Baseline A, Baseline B, and PauseGuard Policy C. |

### 2.6 Guardian Dashboard & Telephony (`/api/v2/guardian`)

| Method | Endpoint | Authorized Roles | Description |
|---|---|---|---|
| `GET` | `/api/v2/guardian/dashboard` | `guardian`, `admin` | Summary of active guardianships and pending review list. |
| `POST` | `/api/v2/guardian/enroll` | `payer` | Explicit opt-in enrollment of trusted guardian. |
| `GET` | `/api/v2/guardian/status` | Authenticated | Check whether current user has an enrolled guardian. |
| `POST` | `/api/v2/guardian/revoke` | `payer` | Revoke active guardian enrollment. |
| `GET` | `/api/v2/guardian/calls/{id}/status` | Authenticated | Telephony call delivery/answered status (call answer != approval). |

---

## 3. Real-Time WebSocket Streaming (`/api/v2/ws`)

### 3.1 Connection Handshake
Connect using WebSocket client with query parameter token:
```
ws://127.0.0.1:8000/api/v2/ws?token=demo-token-payer
```

Upon connection, the server immediately confirms the session:
```json
{
  "type": "CONNECTION_ESTABLISHED",
  "user_id": "00000000-0000-0000-0000-000000000001",
  "roles": ["payer"]
}
```

Keepalive Ping-Pong:
- Client sends: `{"type": "PING"}`
- Server replies: `{"type": "PONG"}`

### 3.2 Role-Based Broadcast Events
When a payment changes state (e.g., created, guardian approved, confirmed), the backend broadcasts to connected sockets:

**Payer receives Full View:**
```json
{
  "event_type": "PAYMENT_AWAITING_GUARDIAN",
  "payment_id": "pg_a1b2c3d4e5f67890",
  "status": "AWAITING_GUARDIAN",
  "tier": 3,
  "amount_paise": 5500000,
  "guardian_deadline": "2026-11-12T16:00:30.000000+00:00",
  "timestamp": "2026-11-12T16:00:00.000000+00:00"
}
```

**Guardian receives Redacted View (No amounts or recipient accounts):**
```json
{
  "event_type": "PAYMENT_AWAITING_GUARDIAN",
  "payment_id": "pg_a1b2c3d4e5f67890",
  "status": "AWAITING_GUARDIAN",
  "tier": 3,
  "guardian_deadline": "2026-11-12T16:00:30.000000+00:00",
  "timestamp": "2026-11-12T16:00:00.000000+00:00",
  "message": "PauseGuard security review required: Please review this transaction.",
  "redacted": true
}
```

---

## 4. Four Core Hackathon Demonstration Walkthroughs

### Scenario 1 — Routine Low-Risk Payment (T0)
1. **Create Payment:** `POST /api/v2/payments` (Bearer: `demo-token-payer`)
   ```json
   {
     "beneficiary_id": "trusted_utility_co",
     "amount_paise": 45000,
     "purpose": "Monthly electricity bill",
     "idempotency_key": "demo_t0_001"
   }
   ```
   *Response:* Status is `READY_TO_EXECUTE`, tier is `0`.
2. **Payer Confirms:** `POST /api/v2/payments/{id}/confirm` (Bearer: `demo-token-payer`)
   ```json
   { "idempotency_key": "demo_t0_confirm_001" }
   ```
   *Response:* Status is `EXECUTED`. Mock balance is debited in ledger.

---

### Scenario 2 — Coerced High-Risk Payment (T3 Guardian Review)
1. **Create High-Risk Payment:** `POST /api/v2/payments` (Bearer: `demo-token-payer`)
   ```json
   {
     "beneficiary_id": "unknown_collector",
     "amount_paise": 6000000,
     "purpose": "URGENT police clearance fine right now",
     "idempotency_key": "demo_t3_001"
   }
   ```
   *Response:* Status is `AWAITING_GUARDIAN`, tier is `3`, `guardian_deadline` is set to 30 seconds ahead.
2. **Guardian Dashboard:** `GET /api/v2/guardian/dashboard` (Bearer: `demo-token-guardian`)
   *Displays pending review in sanitized form.*
3. **Guardian Approves:** `POST /api/v2/payments/{id}/guardian/decision` (Bearer: `demo-token-guardian`)
   ```json
   { "decision": "APPROVE", "notes": "Verified by telephone" }
   ```
   *Response:* Status transitions to `READY_TO_EXECUTE` (Invariant: Guardian decision NEVER executes payment!).
4. **Payer Confirms Execution:** `POST /api/v2/payments/{id}/confirm` (Bearer: `demo-token-payer`)
   *Response:* Status transitions to `EXECUTED`.

---

### Scenario 3 — 30-Second Guardian Timeout & Fallback Review
1. **Create High-Risk Payment:** `POST /api/v2/payments` -> status `AWAITING_GUARDIAN`.
2. **Wait 30s:** Deadline expires. Guardian decision submitted after 30s returns `409 Conflict` (Expired).
3. **Payer Activates Fallback:** `POST /api/v2/payments/{id}/fallback/activate` (Bearer: `demo-token-payer`).
   *Response:* Status transitions to `AWAITING_FALLBACK_REVIEW`. (Invariant: Fallback review never authorizes automatic execution).

---

### Scenario 4 — Safe-Lock Lockout & Victim Recovery Assist
1. **Payer Engages Safe-Lock:** `POST /api/v2/safe-lock` (Bearer: `demo-token-payer`)
   ```json
   { "is_locked": true }
   ```
2. **Attempt Outbound Payment:** `POST /api/v2/payments`
   *Response:* Immediate `423 Locked`: `"Payment rejected: Safe-Lock is currently engaged"`.
3. **Fetch Recovery Guide:** `GET /api/v2/recovery/guide`
   *Displays official National Cybercrime Helpline 1930 and golden hour reporting steps.*
4. **Export Redacted Evidence:** `GET /api/v2/payments/{id}/evidence`
   *Exports sanitized evidence packet with masked personal data for cybercrime reporting.*

