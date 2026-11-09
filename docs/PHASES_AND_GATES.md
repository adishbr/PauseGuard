# Phases and integration acceptance gates
*Current design date: 9 Nov 2026. Check organizer rules for code written before 13–14 Nov.*

**Phase 0 — Agree and document.** Every teammate can explain the 10-step `PRODUCT_WORKFLOW.md`; verify legal prototype boundaries, V2 enums and API. No code needed before acceptance.

**Phase 1 — Vertical slice.** Komal's payment API/state machine + Adish's payer/guardian interfaces. Valid mock rejection, cancellation and no double execution. Gowtham/Jeevan develop typed mock signals/fixtures in parallel.

**Phase 2 — Adaptive protections.** Different personal/business baselines, purpose/velocity and Safe-Lock integrated. Tests include false positives and bypass attempts. No bypass by simply selecting business profile.

**Phase 3 — Guardian fallback.** Secure enrollment and minimal data, 30-second deadline, no automatic approval, mock telephony first; separate concurrent AI advisory with safe failure handling. Permissioned third-party calls are optional after core tests.

**Phase 4 — Insights and assistance.** Policy Lab using synthetic datasets, audit verification and Recovery Assist; UI localization and accessibility. Audit proofs only if justified.

**Phase 5 — External integration and operations.** Optional approved merchant sandbox, cloud Postgres and calls, secrets management, load and security tests; legal/provider review for any later real-world pilot.

### Non-negotiable merge gates
- Contracts match current V2, all IDs namespaced and validated.
- Authorized mock payment execution only after independent server-side checks.
- All terminal paths including concurrency/retries tested.
- Guardian privacy and timeout protections verified.
- Documentation and tests reflect actual result; no false 'working' or 'secure' labels.
- Pre-event implementation provenance matches competition rules.
