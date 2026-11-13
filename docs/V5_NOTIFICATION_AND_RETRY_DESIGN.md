# PauseGuard V5.0 — Notification Outbox & Safe Retry Architecture

## 1. Durable Notification Outbox (`notification_outbox`, Alembic `0007_v5_notification_outbox`)
- **Provider Abstraction (`backend/app/services/notification_service.py`):**
  - `InAppOutboxProvider` (`IN_APP`, active in both local mock and PostgreSQL DB modes).
  - `WebPushStubProvider` (`WEB_PUSH`, stubbed strictly in local/test mock mode; fails closed with `RuntimeError` in `production` / `mode != 'mock'`).
  - `SmsStubProvider` (`SMS_STUB`, stubbed strictly in local/test mock mode; fails closed in `production`).
- **Role-Based Redaction (`sanitize_notification_payload`):**
  - When `recipient_role != 'PAYER'`, strips `amount_paise`, `beneficiary_id`, `beneficiary`, `account_balance`, `payer_account`, `upi_pin` and enforces `"redacted": true` with an opaque review prompt.
  - Persisted post-action (within SQLAlchemy transaction before `commit()` in DB mode, and inside `V5MockIdentityStore` in local mock mode), guaranteeing cross-device/offline delivery even when WebSocket clients are disconnected.
- **Single-Use WebSocket Tickets (`POST /api/v2/ws/ticket` -> `/api/v2/ws?ticket=`):**
  - 30-second TTL, CSPRNG token (`pg_ws_*`), stored hashed (SHA-256) in server state and atomically marked `consumed_at` on first handshake.
  - Plaintext `pg_v5_*` session bearer tokens are rejected in WebSocket URL query parameters (`WS_1008_POLICY_VIOLATION`).

## 2. Payment Snapshot Invalidation, Appeals & Safe Retry (`0006_v5_appeals_retry_stepup`)
- **Snapshot Hash (`compute_approval_snapshot_hash`):** Binds `(payment_id, beneficiary_id, amount_paise)`. Modifying beneficiary or amount via `PATCH /api/v2/payments/{id}` clears prior guardian approval (`AWAITING_GUARDIAN`) and rejects stale `/confirm` calls with HTTP `409 Conflict`.
- **Compromised Guardian Suspension & Backup Failover:** Owning payer can suspend an active invitation via `POST /api/v2/guardian/invitations/{invitation_id}/suspend` and route fallback reviews to an independently enrolled `backup` slot guardian (`POST /api/v2/payments/{id}/fallback/backup`).
- **False-Alert Appeals (`payment_appeals`):** Payers can submit structured appeals (`POST /api/v2/payments/{id}/appeals`), but **only Analyst or Admin actors** can resolve them (`POST /api/v2/payments/{id}/appeals/{appeal_id}/resolve` — payer self-resolution rejected with `403`).
- **Safe Retry Lineage:** `POST /api/v2/payments/{id}/retry` preserves `parent_payment_id` and records `RETRY_OF_PARENT` in the immutable audit trail without bypassing Safe-Lock, step-up, or high-risk re-evaluation.

