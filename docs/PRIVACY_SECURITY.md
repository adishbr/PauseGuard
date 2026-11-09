# Security, privacy and threat-model decisions

## Financial privacy
- Consent-based guardian enrollment; no automatic guardian involvement for routine transfers.
- Guardian default payload: payment request reference, general risk label, request expiry; never exact amount, recipient, purpose or full transaction history unless clearly authorized and necessary.
- Independent guardian approval securely bound to transaction, account and expiry. A connected phone call, a spoofable caller ID, or a single phone-button press is not equivalent.
- Retain as little location, identity or chat history as possible. Support user consent, deletion policies and role-limited access.

## Calls
- Use an authorized Indian service-call provider if/when feasible, after testing regional calling rules and consent. Can simulate an in-app incoming-call screen before paying for real voice APIs.
- 30 seconds = configurable *first response* window, not guarantee that a call is connected or can be answered.
- Precompute sanitized advisory during wait; after no response, **fail to additional independent review**, not allow by default.
- Limit calls per user/day, quiet hours and do-not-disturb preferences where appropriate.

## Location and phone numbers
- Phone number alone is not a permission slip to access real-time device/cell-tower location. Public 'trace number' APIs often return only the prefix/circle or fake precision.
- For payer device, use `navigator.geolocation.getCurrentPosition()` under HTTPS with prior explicit opt-in; handle deny/unavailable/timeouts and provide a nonlocation path.
- Location is spoofable, can be irrelevant to APP scams, and can endanger privacy; it must **never** be the only signal allowing/rejecting a transfer. Avoid collecting a recipient's location without separately justified authorization.

## AI guardian
- AI is advisory and can be manipulated by a coached payer or a prompt-injected payment note.
- Structured output must be validated and provenance indicated: `user_claim` vs `trusted_source` vs `model_inference`.
- Independent verification could include a bank-verified merchant identity or validated beneficiary token from trusted payment infrastructure; mere 'hospital' text is not proof.
- Do not send PINs, OTPs, secrets or unnecessary personal payments to external model APIs.

## Blockchain/privileged admin
- SHA-256 chaining detects edits only if a prior trusted checkpoint exists. A powerful admin who can rewrite the database can also rewrite the local chain.
- Prefer write-once external checkpoints (separate cloud account or optional public chain) of periodic **hashes** only; never publish UPI IDs, names, phone numbers, locations, or private payment data on chain.
- Blockchain doesn't prevent credential theft, UI compromise, phishing, fake beneficiary data, account takeovers, or compromised policy decisions.

## Minimum production threat controls
Authentic identity provider, phishing-resistant MFA where appropriate, verified guardian enrollment, per-object authorization, CSRF protection for cookie auth, origin checks, input validation, rate limits, secrets manager, server-side event logs, least-privilege service roles, encrypt in transit/at rest, backup/restore, monitoring and incident response, independent penetration testing and secure coding practices.

**No system is unhackable**; these controls reduce and detect risk. The starter demo's bearer tokens are not a real identity solution and must NOT be exposed to the public Internet.
