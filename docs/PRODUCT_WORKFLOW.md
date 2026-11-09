# Product workflow — explain it to a new teammate in 5 minutes

## The problem
In Authorized Push Payment (APP) fraud, a real customer may authorize a transfer while a fraudster has deceived or coerced them. Standard authentication doesn't prove their intent is informed. Our product provides *proportionate* interventions before a payment, while respecting adult privacy and legitimate high-volume business payments.

## Complete sequence
1. **Join / sign in:** identity and account role verified (prototype uses fake credentials; production requires real IAM). Select personal, professional, small business or enterprise profile; self-selection alone is not verified business status.
2. **Customer preferences:** optional guardian enrollment, accessibility language, personal notification threshold and response-window preference (e.g. 30/45/60 s). Preferences cannot bypass hard fraud blocks.
3. **Prepare payment:** payer enters beneficiary, purpose, `amount_paise`, and a unique idempotency key. Backend creates `CREATED` record with server identity and timestamps.
4. **Evaluate context:** deterministic checks use payer history, beneficiary verification, velocity/anti-smurfing, device/account history, and mock registry. Optional ML and NetworkX signals are advisory; external consented transcript evidence may be analyzed if available.
5. **Choose policy tier:** Tier 0 allow, Tier 1 explainable warn, Tier 2 strong independent step-up, Tier 3 high-risk restriction or authorized independent review. Amount alone does not force guardian for all businesses.
6. **Conditional guardian route:** only opted-in, risk-eligible users. Backend saves `AWAITING_GUARDIAN` and a server deadline; may dispatch privacy-safe notification or opted-in call. *Answering a call is not payment approval.* Guardian uses authenticated channel.
7. **Parallel AI Safety Co-Pilot:** can precompute structured risk advice during review. Cannot see arbitrary phone calls, locate people from mobile numbers, directly release a payment or override confirmed threats.
8. **Fallback on deadline:** `AWAITING_FALLBACK_REVIEW`; offer permissible independent verification only if policy supports it. AI opinion cannot substitute for trustworthy external evidence. No reply never means consent.
9. **Final payer confirmation:** backend checks current state, actor, hard risks, Safe-Lock, idempotency and mock ledger atomically; external gateway checkout only if independently integrated for approved merchant cases.
10. **Aftercare:** append tamper-evident audit (not tamper-proof), produce redacted evidence, route victim to bank and official cybercrime reporting; do not promise recovery or reverse an already settled UPI transfer.

## Four demonstration scenarios
- ₹100 routine merchant payment: T0 and no guardian.
- ₹50,000 familiar-pattern business supplier: may be T0/T1; verify independently as risk warrants, no universal fixed amount threshold.
- ₹55,000 suspicious KYC/police pressure: T3; authorized guardian can reject; after timeout AI can advise but cannot execute.
- 5 smaller transfers to bypass a large-payment check: rolling velocity detects pattern, applies controls and creates audit/reporting records.

## Team interfaces
- **Komal:** backend state/policy/auth, canonical payment API and database.
- **Adish:** payer and guardian frontend, WebSocket client, privacy and accessible UI.
- **Gowtham:** behavioral, graph, transcript advisory and synthetic Policy Lab; returns typed `RiskSignals` only.
- **Jeevan:** anti-smurf/purpose/lock, audit, recovery, localization and QA; never edits core states without coordinated PR.

## Reality boundary
Mock payments prove application logic only. We cannot intercept arbitrary external UPI transfers, freeze real bank accounts, get real-time phone-number locations, or cancel completed UPI by writing code in this project.
