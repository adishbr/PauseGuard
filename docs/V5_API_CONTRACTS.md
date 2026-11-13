# PauseGuard V5.0 — Canonical API Contracts (`/api/v2`)

> **Versioning Policy:** All endpoints live under `/api/v2`. V1 prefixes (`/api/v1`) and legacy statuses (`PENDING_REVIEW`) remain strictly prohibited. Monetary amounts use integer `amount_paise`.

---

## Gate 2 Contracts — Auth, OTP, Identity & Durable Guardian Invitations

### 1. Real Account Authentication (`/api/v2/auth`)
- `POST /api/v2/auth/signup`
  - **Request:** `{ "email": str, "password": str (min 8 chars), "full_name": str, "role": "payer" | "guardian" }`
  - **Rules:** `role="admin"` or `"analyst"` rejected with `403 Forbidden`. Password hashed with `hashlib.scrypt` + CSPRNG per-user salt. Creates `user_accounts` (`email_verified=False`) and automatically issues or awaits an email `OtpChallenge`.
  - **Response (`201`):** `{ "user_id": UUID, "email": str, "role": str, "email_verified": bool, "requires_otp_verification": true, "message": str }`
- `POST /api/v2/auth/otp/challenge`
  - **Request:** `{ "contact": str, "purpose": "signup_email" | "login_step_up" | "guardian_invite", "channel": "email" | "sms_stub" }`
  - **Rules:** Enforces resend cooldown (e.g., 30s) and hashes 6-digit CSPRNG OTP with HMAC-SHA256 + random salt. In explicit local/mock dev mode only (`PAUSEGUARD_MODE=mock`, `PAUSEGUARD_ENVIRONMENT in {"local", "test"}`), returns `dev_otp_preview` clearly flagged `is_mock_delivery=True` and never writes OTP to logs.
- `POST /api/v2/auth/otp/verify`
  - **Request:** `{ "challenge_id": UUID, "otp_code": str }`
  - **Rules:** Constant-time comparison; max 5 attempts per challenge; single-use; marks `email_verified=True` if `purpose == "signup_email"`.
- `POST /api/v2/auth/login`
  - **Request:** `{ "email": str, "password": str }`
  - **Rules:** Rejects invalid credentials (`401`) or unverified email (`403` with actionable detail). Issues opaque bearer token stored only as SHA-256 digest in `user_sessions` with TTL.
  - **Response (`200`):** `{ "access_token": str, "token_type": "bearer", "expires_at": ISO8601, "user_id": UUID, "email": str, "role": str, "identity_verified": bool, "is_synthetic": false }`
- `POST /api/v2/auth/logout` (Authenticated) -> revokes current session token hash cleanly (`200`).

### 2. Identity Assurance (`/api/v2/identity`)
- `POST /api/v2/identity/verify` (Authenticated)
  - **Request:** `{ "provider": "synthetic_local_idp", "full_name": str, "synthetic_document_ref": str, "consent_confirmed": true }`
  - **Rules:** Rejects `consent_confirmed=False` (`400`) and production usage (`503`). Never persists `synthetic_document_ref`; derives opaque `trusted_person_ref` and records `IdentityAssurance` (`level="SYNTHETIC_STANDARD"`, `is_mock_assurance=True`). Clients cannot supply `trusted_person_ref`.
- `GET /api/v2/identity/status` (Authenticated) -> returns active assurance metadata (`assurance_id`, `provider`, `level`, `verified_at`, `expires_at`, `revoked`).

### 3. Durable Guardian Enrollment & Invitations (`/api/v2/guardian`)
- `POST /api/v2/guardian/invitations` (Payer-only)
  - **Request:** `{ "guardian_email": str, "relationship": str, "role_slot": "primary" | "backup", "notification_channel": str }`
  - **Rules:** Cannot invite own email (`403/409`). Issues single-use high-entropy invitation token (hashed in DB), initializes state `PENDING`.
- `GET /api/v2/guardian/invitations` (Authenticated Payer or Invited Guardian) -> lists sent or received invitations.
- `POST /api/v2/guardian/invitations/{invitation_id}/accept` (Guardian-only)
  - **Request:** `{ "invite_token": str, "otp_challenge_id": UUID, "otp_code": str, "explicit_consent": true }`
  - **Rules:** Verifies token digest + OTP -> `CONTACT_VERIFIED` -> checks server `IdentityAssurance` (`412` if unverified) -> **blocks if guardian `trusted_person_ref` == payer `trusted_person_ref` (`403` collusion/self-guardianship blocked)** -> records `CONSENTED` & promotes to `ACTIVE`.
- `POST /api/v2/guardian/invitations/{invitation_id}/decline` (Guardian-only) -> transitions to `DECLINED`.
- `POST /api/v2/guardian/invitations/{invitation_id}/revoke` (Owning Payer or Active Guardian) -> transitions to `REVOKED` immediately.

---

## Gate 4–6 Target Contracts (Delivered in Subsequent Gates)

- **Gate 4 (Payment Integrity, Step-Up, Fallback & Appeals):**
  - `POST /api/v2/payments/{id}/step-up/verify`
  - `POST /api/v2/payments/{id}/appeals` & `POST /api/v2/payments/{id}/appeals/{appeal_id}/resolve` (Analyst/Admin only)
  - `POST /api/v2/payments/{id}/retry` (Safe retry preserving fraud lineage)
  - `POST /api/v2/guardian/backup/activate` & compromised guardian suspension endpoint
- **Gate 5 (Realtime Security & Notification Outbox):**
  - `POST /api/v2/ws/ticket` (Short-lived single-use WS ticket exchange replacing query tokens)
  - `GET /api/v2/notifications/outbox`
- **Gate 6 (Mock Bank Pre-Execution Adapter):**
  - `POST /api/v2/bank/intents`, `POST /api/v2/bank/webhooks/settlement` (HMAC-verified)

