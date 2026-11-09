# Member 2 — Adish (Atish) | Core frontend and integration lead
You own payer/guardian React+TypeScript+Tailwind UI and integration with Komal's canonical API. Follow V2 docs.

**Scope:** onboarding/profile settings, account preference UX, payment form, status and rejection screens, guardian privacy-limited screen, secure decision workflow, opt-in consent, 30/45/60-second client countdown reflecting SERVER deadline, recoverable WebSocket status, accessible copy, responsive design, critical path demo and frontend tests.

**Do not:** generate a second independent payment backend, make AI approve on timeout, display full beneficiary/amount to guardian by default, mark payment executed before server confirms, or silently edit core API schemas.

**First task to propose:** inspect repo and Komal's agreed OpenAPI/mock fixture. Implement payer+guardian two-browser-window vertical slice with loading, error, reconnect and timeout states.

**Required tests:** separate identities/permission failures, no leaked guardian fields, exactly-once success display, late guardian UI state, mobile keyboard/accessibility, stop/retry handling and browser E2E flows. Tests must reflect real backend responses.

**Handoff:** screenshots/video notes, exact API payloads used, frontend dependencies, tests and issues requiring Komal review.
