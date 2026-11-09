# PauseGuard V2 — Canonical Architecture (9 Nov 2026)

## Problem and product boundary
Risk-adaptive intervention for authorized push payment fraud in India. This is a **proposed integration layer**. It has no inherent capability to intercept outside Google Pay/PhonePe P2P transactions, read bank-wide balances, freeze a bank account, reverse UPI settlement, or obtain DPIP/telecom data.

## Payment workflow
1. Authenticate payer using an approved identity system. Categorize account as personal / professional / small_business / enterprise with appropriate verification and user preferences. A self-selected type cannot lower hard security limits.
2. Payer initiates payment. **Backend** verifies recipient ID, input, amount in integer paise, idempotency key, available capabilities.
3. Risk-context service supplies transaction/recipient history, risk registry, velocity, beneficiary verification and optional **consented, minimal** location metadata. No location is required for basic operation.
4. Fast synchronous **deterministic** policy evaluates hard blocks and context. Behavioral ML/graph signals are advisory; unavailable models yield an explicitly degraded, more cautious policy. Unverified purpose/claims never count as beneficiary proof.
5. Tier 0 proceed with normal payment authorization; Tier 1 warning; Tier 2 independent step-up; Tier 3 high-risk independent intervention (guardian is only an optional route).
6. If guardian route is elected/enrolled, backend records `AWAITING_GUARDIAN` and 30-second deadline. Outbox requests in-app and optional voice call. **Call answer ≠ payment approval.** Human review must use a secure, bound authorization channel with backend validation.
7. AI advisor prepares a report in parallel during guardian interval. On timeout backend moves `AWAITING_FALLBACK_REVIEW`; report may suggest next verification but **cannot execute a payment**. If no independent safe route exists, payment stays restricted or expires; no automatic bypass.
8. Payer confirms allowed payment. Backend enforces fresh hard-block/Safe-Lock check and uses atomic ledger transaction in mock environment. External merchant gateway has its own async settlement status/reconciliation contract.
9. Durable audit event, privacy-preserving notification, redacted reporting guidance. Outbox dispatches notifications **after** successful state commit.

## Core trust boundaries
- Frontend and web/mobile clients are **untrusted**; user-supplied role, amount thresholds, recipient claims and coordinates are untrusted inputs.
- Authentication server is trusted only after verifying its cryptographic claims; a real IAM is a **production prerequisite**.
- AI service is **untrusted advisory compute**; its tool outputs, chat text and proposed risk scores may contain prompt injection or hallucination.
- Guardian communication provider cannot confer authorization merely because a call connected or a DTMF key was pressed. Bind approvals to guardian login, transaction ID, expiry and anti-replay token.
- External ledger anchors prove only that a particular event hash existed at/after anchoring, **not that the original input or risk conclusion was truthful**.
- An admin dashboard must not possess unrestricted money-moving or silent-audit-edit privileges.

## Performance strategy
- Fast synchronous policy path for ordinary payments; AI never blocks low-risk decisions merely to finish reasoning.
- Parallelize bounded advisory work with the guardian notification window; after deadline, use available verified evidence.
- Cache vetted reference data carefully, versioned and with expiry. Avoid caching sensitive authentication outcomes.
- Measure p50/p95/p99 actual latency, provider call-connection rate, false-positive and missed-fraud simulation rates; do not invent performance claims.

## Suggested implementation layers
React/Tailwind views → FastAPI API/auth/middleware → payment state service + deterministic policy + actor-bound approval → SQL database + audit/outbox → optional ML/graph, telephony, gateway, external audit anchor.

## Design invariants
- Strongly suspicious requests are not bypassed by 'urgent', location, family approval, business profile or self-chosen limit.
- Phone call never starts for everyday transactions solely due to high amount.
- Every high-risk timeout remains nonexecuted unless separate independently verified requirements are met.
- Distinct payer final confirmation, valid guardian role, idempotency, terminal state irreversibility, audit after commit.
- If provider is down, no invisible fail-open behavior.
