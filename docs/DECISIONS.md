# Architecture Decision Log
## Approved — 2026-11-09 (proposed V2 design)
- V2 APIs `/api/v2`, payment state machine is canonical. V1 integration kit deprecated for new implementation.
- Mock payer-to-payee ledger is core demo; optional merchant sandbox is separate.
- Profile-aware risk, not amount-only guardian checks.
- Opt-in guardian/authorized checker, 30s initial call-review window, never auto approval on timeout.
- AI advisory parallel to review; unavailable AI cannot authorize anything.
- No real third-party geolocation from phone number.
- No Solana/Phantom as UPI payment rail; potential audit-only research.
- Komal and Adish core owners; Gowtham risk and Policy Lab; Jeevan safety and QA.

## Awaiting explicit team sign-off
- Exact guardian call provider and opt-in/recording process.
- Whether to use hosted Supabase Postgres vs local SQLite during early development.
- Whether ECC Minimal is installed and its release SHA/version.
- Verified ownership + approved SHA/license for any external code reuse.
- Host and auth identity solution; real-world data or payments remain excluded without partner review.
- Hackathon policy on pre-build work and what may be shown as coded onsite.

> Every revised decision must record date, proposer, approvers (Komal + Adish for core contract), reasons, trade-offs, affected files, tests, and migration action.
