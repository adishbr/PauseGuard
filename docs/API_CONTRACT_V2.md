# API Contract V2 — starter implementation

**Base:** `/api/v2`. **All money:** integer `amount_paise`. **Prototype authentication:** `Authorization: Bearer <LOCAL_DEMO_TOKEN>`; production must use proper identity/access control.

| Method | Endpoint | Status | Role | Behavior |
|---|---|---|---|---|
| GET | /health | Implemented | Public | Local mock server status |
| GET | /profile | Implemented | Authenticated | profile and notification preference |
| POST | /payments | Implemented | Payer | create risk-evaluated mock payment; idempotency key |
| GET | /payments/{id} | Implemented | Payer, assigned guardian | guardian gets redacted view |
| POST | /payments/{id}/warning/acknowledge | Implemented | Payer | warning to `READY_TO_EXECUTE` |
| POST | /payments/{id}/guardian/decision | Implemented | Assigned guardian | approve→ready; reject→rejected; enforce time window |
| POST | /payments/{id}/fallback/activate | Implemented | Payer | only at/after deadline, move to `AWAITING_FALLBACK_REVIEW` |
| POST | /payments/{id}/cancel | Implemented | Payer | cancel eligible pending payment |
| POST | /payments/{id}/confirm | Implemented | Payer | atomic mock ledger debit with idempotency key |
| POST | /safe-lock | Implemented | Payer | switch on/off mock Safe-Lock |
| GET | /audit/verify | Implemented | Admin | verify local hash chain |
| POST | /guardian/enroll | Planned | Authenticated | confirm opt-in and guardian authorization |
| GET | /guardian/calls/{id}/status | Planned | Authorized | provider call delivery/answered status |
| POST | /guardian/calls/provider-callback | Planned | Provider verified webhook | signed provider status, never authorize alone |
| POST | /risk/advice | Planned internal | Risk service | bounded advisory, no payment state modification |
| POST | /payments/{id}/step-up/verify | Planned | Payer + trusted verification | strong independent verification, not self-declaration |
| POST | /policy-lab/simulate | Planned | Analyst | synthetic policy comparison |
| POST | /anchors | Planned | Service/admin | external audit hash checkpoint only |

## Create request
```json
{
 "beneficiary_id":"supplier_new",
 "amount_paise":5500000,
 "purpose":"kyc_verification",
 "idempotency_key":"new_unique_key_001"
}
```

## Create response (payer)
```json
{
 "id":"pg_...",
 "status":"AWAITING_GUARDIAN",
 "tier":3,
 "risk_score":100,
 "reason_codes":["RC_NEW_BENEFICIARY","RC_LARGE_DEVIATION","RC_COERCION_PURPOSE","RC_CUSTOMER_ALERT_PREFERENCE"],
 "amount_paise":5500000,
 "beneficiary_id":"supplier_new",
 "purpose":"kyc_verification",
 "guardian_deadline":"2026-11-09T10:00:30+00:00",
 "version":1
}
```
Scores here are examples of a synthetic heuristic.

## Guardian response
Guardian sees only `id`, `status`, `tier`, `guardian_deadline`, and a short generic message; sensitive amount/recipient/purpose never exposed by default.

## 30-second timeout
At expiry: `AWAITING_GUARDIAN` → `AWAITING_FALLBACK_REVIEW`. Advisory response must include `can_authorize_payment: false`. No silent pass or payment execution. A further trusted independent-verification flow must be implemented separately and reviewed.

## Unimplemented backend-wide rules
Real auth, signed webhook verification, durable outbox, rate limiting, WebSockets, actual transaction reconciliation, separate bank/gateway state, async AI model and reliable cross-worker state transitions are planned—not disguised as implemented.
