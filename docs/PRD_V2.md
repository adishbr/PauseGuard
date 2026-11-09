# Product requirements — PauseGuard V2
## Objective
Demonstrate explainable, proportional fraud intervention before a mock account-to-account payment executes, plus safe recovery guidance, without converting every adult or business payment into family-supervised activity.

## Primary personas
Personal UPI payer; working professional; verified small business owner; enterprise operator with optional maker-checker; explicitly enrolled guardian; internal analyst with redacted synthetic scenarios. A selected role is not proof of identity.

## Functional requirements
- FR-01: Authenticate payer/guardian separately; authorize all reads, commands and event streams.
- FR-02: Store money as integer paise. Idempotent creation and execution.
- FR-03: Compare payment to account-specific baseline, hard risk signals and anti-smurfing.
- FR-04: Deterministic four-tier policy, clear reason codes, risk-score provenance.
- FR-05: Guardian enrollment opt-in, minimal disclosure, configurable first-response deadline (start 30s for demo), verified decision channel.
- FR-06: AI co-pilot produces bounded structured advice, never approval authority; handles unavailability/timeouts safely.
- FR-07: Business profiles and maker-checker are optional/verified; business label not blanket exemption.
- FR-08: Purpose challenge, anti-smurfing, simulated Safe-Lock and fraud reporting evidence export.
- FR-09: Offline/failed provider flows preserve authoritative state and cannot silently release a pending payment.
- FR-10: Localization, accessible UI, audit chain and synthetic Policy Lab with labelled limitations.

## Nonfunctional requirements
- Security: least privilege, no secrets in repo, input validation, safe webhook verification, CSRF/CORS policies, rate limits, secure sessions, evidence privacy.
- Consistency: atomic state changes, terminal-state immutability and duplicate payment prevention.
- Reliability: disconnections/retries handled with server state re-fetch; bounded AI/telephony latency.
- Performance: measure real p50/p95 and alert fatigue; no arbitrary promised sub-millisecond latency.
- Privacy: location consent, optional guardian, audio only with lawful capture and proper notice; short retention for sensitive review signals.
- Research integrity: synthetic outcomes labelled, no claims of RBI/NPCI approval.

## Acceptance gate for first integrated demo
A mock payer can initiate and inspect a payment; policy assigns tier; opted-in guardian securely rejects a critical case; payment ends `REJECTED` and mock balances do not move. A guardian timeout does not cause execution; authorized business payment doesn't necessarily trigger guardians; retries cannot double-charge.

## Not in scope of this iteration
Production live-bank integrations, arbitrary real UPI P2P interception, real card/merchant settlements, mobile-number location tracing, automatic call recording without permission, crypto wallet transfers, guaranteed recovery, actual fraud accuracy claims, or an "unhackable" website.

## Unresolved decisions to record in `docs/DECISIONS.md`
Verified identity provider, cloud host, caller provider and pricing, nature of independently verified beneficiary registry, retention window, legal privacy review, organizer pre-build restrictions.
