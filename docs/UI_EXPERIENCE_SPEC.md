# PauseGuard frontend UX and accessibility specification

## Screens owned by Adish
1. Login (mock vs real authentication clearly labelled), consent, profile type choice.
2. Payer home, beneficiary list, payment input in paise, purpose challenge.
3. Risk explanation (plain language, non-alarming, why and next step).
4. Four-tier outcomes; no invented direct approval from AI.
5. Guardian enrollment and revocation (opt-in, limited scope).
6. Guardian review card without transaction history or full recipient/amount by default.
7. Review countdown 30/45/60s and fallback status, backend-authoritative.
8. AI Co-Pilot transcript explanation and confidence limitations.
9. Business settings and legitimate recurring supplier payments.
10. Safe-Lock, help and Recovery Assist evidence export.
11. Analyst/Policy Lab with synthetic dataset labels.

## UX rules
- Senior-first: readable text, strong contrast, clear focus states, large touch targets, localization EN/KN/HI/TE, optional speech where supported.
- Warnings should be actionable: 'How to verify beneficiary' and 'Stop this payment'; no manipulative fear.
- Timeout never shows approved; reflect exact backend status.
- Guardian never sees more than the authorized fields and cannot browse payer history.
- Display reason codes via mapped plain-language messages, not raw developer strings.
- Business user sees no repeated guardian requests for normal amounts/new suppliers unless relevant risk requires review.
- Offline/reconnect shows 'Checking payment status', not success.
- All UI examples use synthetic account names and clear 'Demo' labels.

## Acceptance tests
Keyboard navigate primary flow; screen reader labels; multiple viewport sizes; localization labels fit; privacy fields absent from network payload for guardian; double-click payment doesn't double submit; clear error states and retry guidance.
