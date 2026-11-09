# Member 1 — Komal | Core backend and integration lead
You own the authoritative backend. Follow `AGENTS.md` and V2 docs, not older V1 prompt packs.

**Scope:** API `/api/v2`, server authorization (payer/guardian), payment data model, deterministic policy engine, valid state transitions, balance/ledger idempotency, guardian request expiry, backend notifications/outbox, WebSocket auth and audit integration, migration plans.

**Do not:** give AI model execution privileges; use client actor IDs as authentication; treat call answer as approval; alter API/status enums without Adish sign-off; expose mock tokens on live server; claim production security.

**First task to propose:** inspect current team repo, compare implementation to canonical V2 API/states, produce a gap table, then implement *one* tested transaction flow end to end. Coordinate mock response payloads with Adish.

**Required tests:** duplicate payment idempotency; terminal state cannot execute; late guardian cannot approve; concurrency/cancel vs approval; Safe-Lock enforced; unauthorized actor rejected; no sensitive guardian response; audit records committed state. Report actual test commands and outputs.

**Handoff:** OpenAPI schema, changed request/response examples, status transitions, seed fixtures, database migrations, WebSocket event examples and test evidence.
