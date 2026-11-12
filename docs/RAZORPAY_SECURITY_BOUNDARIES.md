# Razorpay Test Mode — Security Boundaries

## 1. Purpose

PauseGuard V2 supports optional Razorpay Test Mode for an isolated merchant sandbox demonstration.

Razorpay Test Mode is separate from the normal simulated UPI/P2P payment flow. It must never process real money or replace the existing mock payment engine.

## 2. Implemented Security Utilities

### Sandbox configuration and access control

File: `backend/app/integrations/razorpay_sandbox.py`

- Requires explicit `PAUSEGUARD_RAZORPAY_TEST_ENABLED=true`.
- Reads only `RZP_TEST_KEY_ID` and `RZP_TEST_KEY_SECRET`.
- Rejects missing credentials and non-test key prefixes.
- Hides credentials from the configuration object's representation.
- Requires a trusted backend actor with the Admin role.

Important: The helper does not authenticate users itself. The API layer must obtain the actor through trusted backend authentication.

### Payment signature verification

File: `backend/app/integrations/razorpay_signatures.py`

- Verifies payment signatures using HMAC-SHA256.
- Uses the `order_id|payment_id` message format.
- Uses constant-time signature comparison.
- Rejects malformed signatures and invalid inputs.

### Webhook signature verification

File: `backend/app/integrations/razorpay_signatures.py`

- Verifies HMAC-SHA256 signatures against the original raw request body.
- Rejects empty bodies, malformed signatures and missing secrets.
- Does not parse or trust webhook event data before verification.

### Webhook replay protection

File: `backend/app/integrations/razorpay_replay_guard.py`

- Tracks previously seen event IDs.
- Rejects duplicate IDs while retained.
- Uses thread-safe access.
- Enforces a configurable maximum event capacity.

## 3. Important Limitations

These utilities are security building blocks, not a complete Razorpay integration.

- Replay protection is in-memory and does not survive process restarts.
- Event IDs can be accepted again after capacity eviction.
- Production replay protection requires durable, shared storage and an atomic uniqueness constraint.
- Admin authorization depends on trusted backend authentication.
- Key-prefix validation does not prove that credentials are genuine.
- Signature tests use synthetic secrets and do not establish live provider connectivity.
- No Razorpay SDK, order creation endpoint, payment execution, settlement or webhook route has been implemented.
- No external Razorpay API requests are made by these utilities.

## 4. Security Requirements for Future Integration

Before connecting these utilities to backend routes:

1. Obtain backend-owner approval for API and payment-state changes.
2. Keep Razorpay Test Mode restricted to authenticated administrators.
3. Store credentials only in approved server-side secret storage.
4. Verify webhook signatures against the exact raw request body.
5. Persist webhook event IDs atomically to prevent replay across workers.
6. Reconcile provider outcomes with server-side order records.
7. Never treat a webhook or guardian approval alone as permission to execute a payment.
8. Preserve Safe-Lock and hard-policy checks.
9. Keep Razorpay merchant sandbox outcomes separate from mock P2P ledger state.
10. Fail closed when verification or reconciliation fails.

## 5. Verification

Backend test command:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -v
```

Latest recorded result:

- 482 passed
- 1 warning
- 0 failures

The warning concerns Starlette TestClient's use of httpx and is unrelated to these security utilities.

## 6. Scope

This work is an independent Member 4 security contribution.

It does not modify canonical payment states, shared API contracts, existing mock payment execution, or production payment infrastructure.

No real-money transactions or production credentials are involved.
