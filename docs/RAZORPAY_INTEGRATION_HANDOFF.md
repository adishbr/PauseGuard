# PauseGuard V2 — Razorpay Test Mode Backend Integration Handoff

**Author:** Komal (Core Backend & Integration Lead, Member 1)  
**Recipient:** Adish (Frontend Lead, Member 2), Jeevan (QA & Security, Member 4), Team  
**Branch:** `feature/komal-razorpay-test`  
**Canonical API Namespace:** `/api/v2/sandbox/razorpay`  
**Status:** Complete, Verified, Fully Hardened  

---

## 1. Executive Summary & Architecture Boundary

PauseGuard provides an isolated, production-grade **Razorpay Test Mode Merchant Sandbox** backend.

### Strict Decoupling & Security Invariants
1. **Mock UPI/P2P State Machine Decoupling:**
   - Merchant payments are completely decoupled from PauseGuard's mock UPI/P2P peer-to-peer payment engine (`/api/v2/payments`).
   - Merchant checkouts do **NOT** invoke `evaluate_payment_policy`.
   - Webhook events or checkout confirmations **CANNOT** authorize, confirm, or execute mock P2P payments or mutate user mock balances (`can_authorize_p2p_payment: false` strictly enforced).
   - P2P ledger entries (`ledger_entries`) and mock accounts (`accounts`) are never debited or credited by Razorpay merchant transactions.
2. **Zero Real Money:**
   - Only Razorpay Test Mode keys (`rzp_test_*`) are permitted.
   - Live keys (`rzp_live_*`) are blocked fail-closed on startup and invocation.
3. **Admin Ownership & Cross-Admin Isolation:**
   - Sandbox order creation, payment verification, and order inspection require a trusted administrator (`UserRole.ADMIN`).
   - Non-admin roles (Payer, Guardian, Analyst) are rejected with `403 Forbidden`.
   - **Cross-admin isolation:** An authenticated admin can only inspect and verify orders created by themselves. Querying or verifying another admin's order is rejected with `403 Forbidden`.
4. **Admin-Scoped Idempotency:**
   - `POST /api/v2/sandbox/razorpay/orders` supports safe idempotency via the `Idempotency-Key` (or `X-Idempotency-Key`) header or `idempotency_key` in the request body.
   - Identical retries return the original order with `201 Created`.
   - Conflicting request parameters reusing the same idempotency key fail with `409 Conflict`.
   - Cross-caller key collisions fail with `409 Conflict`.
5. **Durable & Atomic Webhook Replay Protection:**
   - Inbound webhook events are deduplicated against retained event IDs in PostgreSQL (`razorpay_webhook_events`) with atomic uniqueness constraints (catching database race conditions).
   - The in-memory replay guard (`WebhookReplayGuard`) is explicitly restricted to local/test mock mode.
   - If durable storage is required (non-mock/production) but unavailable, the webhook receiver fails closed with `503 Service Unavailable`.
6. **Out-of-Order Webhook Downgrade Protection:**
   - If an order has already transitioned to `paid` (via checkout verification or `payment.captured`), subsequent delayed or out-of-order `payment.failed` webhook events are acknowledged but will **never** revert the order status to `failed`.
7. **Server-Side Verification & Provider Reconciliation:**
   - Client-reported statuses or amounts are never trusted.
   - Signatures are verified using constant-time HMAC-SHA256 (`order_id|payment_id`).
   - Amounts and order IDs are verified directly against Razorpay's provider API (`client.payment.fetch(payment_id)`).

---

## 2. Comparison with Frontend Branch (`feat/adish-frontend`)

Inspection of `origin/feat/adish-frontend` (`frontend/src/types/admin.ts` and `frontend/src/pages/Admin.tsx`) shows Adish established a draft UI structure for **Mode B — Razorpay Test Mode**, with placeholder endpoint paths pending backend confirmation:

### Endpoint Mapping Table

| Adish Draft Path (`admin.ts`) | Canonical Backend Endpoint | Method | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| `/api/v2/admin/razorpay/order` | `/api/v2/sandbox/razorpay/orders` | `POST` | **Available** | Creates Test Mode order. Returns `key_id`, `razorpay_order_id`, and supports `Idempotency-Key`. |
| `/api/v2/admin/razorpay/verify` | `/api/v2/sandbox/razorpay/verify` | `POST` | **Available** | Verifies HMAC-SHA256 signature, validates admin ownership, and reconciles provider amount. |
| `/api/v2/admin/razorpay/status/{order_id}` | `/api/v2/sandbox/razorpay/orders/{order_id}` | `GET` | **Available** | Retrieves order details and payments list. Enforces admin ownership. Accepts either `rzp_ord_...` or `order_...`. |
| `/api/v2/admin/razorpay/config` | Included in `POST /orders` response | `N/A` | **Available** | The public Test Mode `key_id` is securely returned in the `POST /orders` response payload. No separate unauthenticated endpoint is required. |
| *(External Webhook)* | `/api/v2/sandbox/razorpay/webhook` | `POST` | **Available** | Public webhook receiver authenticated by `X-Razorpay-Signature`. Replay-protected and decoupled from P2P. |

> [!IMPORTANT]
> **No duplicate endpoints:** Per architectural contracts, `/api/v2/sandbox/razorpay` is the canonical backend namespace. Adish should point the admin service to these canonical paths.

---

## 3. Frontend Implementation Guide (Instructions for Adish)

### 3.1. Update `frontend/src/types/admin.ts`
Update `razorpayRequiredEndpoints` to reflect the canonical routes:
```typescript
export const razorpayRequiredEndpoints = [
  { method: 'POST', path: '/api/v2/sandbox/razorpay/orders',            note: 'Create a Razorpay test order server-side (returns public key_id)' },
  { method: 'POST', path: '/api/v2/sandbox/razorpay/verify',            note: 'Verify Razorpay payment signature (HMAC) and reconcile with provider' },
  { method: 'GET',  path: '/api/v2/sandbox/razorpay/orders/{order_id}', note: 'Fetch order and payment reconciliation status (Admin ownership enforced)' },
] as const
```

### 3.2. Update `frontend/src/pages/Admin.tsx` (RazorpayPanel)
In `frontend/src/pages/Admin.tsx`, connect the test checkout button to the backend:

```tsx
// Example implementation for RazorpayPanel in Admin.tsx
async function handleLaunchCheckout(amountPaise = 50000) {
  setBusy(true);
  try {
    // 1. Create order on canonical backend endpoint
    const orderRes = await fetch('/api/v2/sandbox/razorpay/orders', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`, // Admin token
        'Idempotency-Key': `idem_checkout_${Date.now()}`,
      },
      body: JSON.stringify({
        amount_paise: amountPaise,
        currency: 'INR',
        receipt: `rcpt_admin_${Date.now()}`,
        notes: { portal: 'admin_dashboard' },
      }),
    });

    if (!orderRes.ok) {
      throw new Error(`Order creation failed: ${await orderRes.text()}`);
    }
    const order = await orderRes.json();

    // 2. Open Razorpay Standard Checkout modal
    const options = {
      key: order.key_id, // Public test key (rzp_test_...)
      amount: order.amount_paise,
      currency: order.currency,
      name: 'PauseGuard Merchant Sandbox',
      description: 'Admin Test Checkout',
      order_id: order.razorpay_order_id,
      handler: async (response: {
        razorpay_order_id: string;
        razorpay_payment_id: string;
        razorpay_signature: string;
      }) => {
        // 3. Verify signature on canonical backend endpoint
        const verifyRes = await fetch('/api/v2/sandbox/razorpay/verify', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
          },
          body: JSON.stringify({
            razorpay_order_id: response.razorpay_order_id,
            razorpay_payment_id: response.razorpay_payment_id,
            razorpay_signature: response.razorpay_signature,
          }),
        });
        const verifyData = await verifyRes.json();
        setPreview((prev) => ({
          ...prev,
          orderId: verifyData.razorpay_order_id,
          paymentId: verifyData.razorpay_payment_id,
          verificationStatus: verifyData.verified ? 'verified' : 'failed',
          reconciliationStatus: verifyData.status === 'paid' ? 'captured' : 'failed',
        }));
      },
      prefill: {
        name: 'Demo Administrator',
        email: 'admin@pauseguard.test',
        contact: '9999999999',
      },
      theme: { color: '#0F172A' },
    };

    const rzp = new (window as any).Razorpay(options);
    rzp.open();
  } catch (err: any) {
    alert(err.message);
  } finally {
    setBusy(false);
  }
}
```

---

## 4. Complete API Specifications

### 4.1. `POST /api/v2/sandbox/razorpay/orders`
- **Role:** Administrator (`UserRole.ADMIN`).
- **Headers:**
  - `Authorization: Bearer <ADMIN_TOKEN>`
  - `Idempotency-Key: <unique_string>` (optional)
- **Request Body (`RazorpayOrderCreateRequest`):**
  ```json
  {
    "amount_paise": 50000,
    "currency": "INR",
    "receipt": "rcpt_hackathon_001",
    "notes": { "purpose": "merchant_test" },
    "idempotency_key": "idem_optional_in_body"
  }
  ```
- **Responses:**
  - `201 Created`: Returns `RazorpayOrderResponse`.
  - `403 Forbidden`: Non-admin caller.
  - `409 Conflict`: Idempotency collision across callers or conflicting parameters with the same key.
  - `422 Unprocessable Entity`: Negative/zero amount, non-INR currency, or extra fields.
  - `502 Bad Gateway`: Upstream Razorpay provider error.
  - `503 Service Unavailable`: Sandbox disabled or live key detected.

### 4.2. `POST /api/v2/sandbox/razorpay/verify`
- **Role:** Administrator (`UserRole.ADMIN`) who owns the order.
- **Headers:** `Authorization: Bearer <ADMIN_TOKEN>`
- **Request Body (`RazorpayVerifyRequest`):**
  ```json
  {
    "razorpay_order_id": "order_Q1w2E3r4T5y6U7",
    "razorpay_payment_id": "pay_Z9y8X7w6V5u4T3",
    "razorpay_signature": "60a4f6be592966e3b8a95f0c..."
  }
  ```
- **Responses:**
  - `200 OK`: Returns `RazorpayVerifyResponse` with `verified: true, status: "paid", reconciled_with_provider: true`.
  - `400 Bad Request`: Invalid signature, amount mismatch, order ID mismatch, or provider payment status not captured.
  - `403 Forbidden`: Non-admin or admin who does not own the order.
  - `404 Not Found`: Order not found.
  - `502 Bad Gateway`: Upstream provider reconciliation error.

### 4.3. `POST /api/v2/sandbox/razorpay/webhook`
- **Role:** Unauthenticated (Razorpay server-to-server).
- **Headers:** `X-Razorpay-Signature: <hmac_sha256_hex>`
- **Body:** Raw event JSON.
- **Responses:**
  - `200 OK`: Returns `RazorpayWebhookResponse` with `status: "processed"` or `status: "duplicate"`. `can_authorize_p2p_payment` is strictly `false`.
  - `400 Bad Request`: Missing signature header or invalid signature.
  - `503 Service Unavailable`: In-memory guard used in production or missing webhook secret.

### 4.4. `GET /api/v2/sandbox/razorpay/orders/{order_id}`
- **Role:** Administrator (`UserRole.ADMIN`) who owns the order.
- **Headers:** `Authorization: Bearer <ADMIN_TOKEN>`
- **Path Parameter:** `order_id` (either internal `rzp_ord_...` or Razorpay `order_...`).
- **Responses:**
  - `200 OK`: Returns order details, admin ID, receipt, and list of payments.
  - `403 Forbidden`: Admin caller does not own this order.
  - `404 Not Found`: Order not found.

---

## 5. Test Evidence & Readiness

```powershell
# Run all dedicated Razorpay integration and security tests:
.\backend\.venv\Scripts\python.exe -m pytest backend\tests\test_razorpay_integration.py backend\tests\test_razorpay_sandbox.py backend\tests\test_razorpay_signatures.py backend\tests\test_razorpay_replay_guard.py -v
# Result: 81 passed in 4.25s

# Run full repository offline test suite:
.\backend\.venv\Scripts\python.exe -m pytest tests backend\tests -q
# Result: 973 passed, 1 warning, 42 subtests passed in 26.05s
```

All 973 offline tests pass with zero errors. Git stash `stash@{0}` is preserved. Ready for independent review and frontend integration.
