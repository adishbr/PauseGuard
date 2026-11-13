# PauseGuard V5.0 — Threat Model (STRIDE + APP-Fraud Specific)

| Category | Threat Vector | Impact | V5 Mitigation & Gate |
| :--- | :--- | :--- | :--- |
| **Spoofing** | Payer signs up a sockpuppet guardian email to self-approve high-risk UPI transfer | Bypass of independent second-human check | `IdentityAssurance` compares opaque `trusted_person_ref`; rejects same human (`403`) + requires contact OTP + explicit guardian consent (Gate 2) |
| **Spoofing** | Attacker guesses 6-digit OTP or replays used invitation link | Unauthorized guardian link / account takeover | HMAC-SHA256 OTP hash, 5-attempt lockout, 300s TTL, cooldown, single-use invitation token hash (Gate 2) |
| **Privilege Escalation** | Attacker passes `"role": "admin"` on signup or arbitrary `subject_id` in `/anti-smurfing/check` | Unauthorized admin sandbox / victim velocity probing | Allowlist `"payer"\|"guardian"` on signup; ignore/reject client `subject_id` for non-analysts (Gate 2) |
| **Tampering** | Payer alters beneficiary or `amount_paise` after guardian grants approval | Bait-and-switch payment execution | Guardian approval binds immutable `(beneficiary_id, amount_paise, approval_hash)` snapshot; mismatch voids approval (Gate 4) |
| **Tampering** | Tampered Razorpay or Mock Bank webhook attempts fake settlement | False ledger state / bypass | Constant-time HMAC-SHA256 signature verification + replay ID tracking + isolated Test Mode check (Gate 6) |
| **Information Disclosure** | Guardian notification leaks exact transaction amount or account details; WS bearer leaked in query URL | Privacy violation & credential theft via proxy/server logs | Strict guardian field redaction (`RedactedPaymentView`); replace query token with single-use `/api/v2/ws/ticket` (Gate 5) |
| **Repudiation / AI Hallucination** | AI marks coercive call as safe (`risk=0`) and attempts auto-execution | Unchecked scam loss | AI outputs advisory signals only (`can_authorize_payment=False`); deterministic rules + human confirmation mandatory (V4.1 + Gate 5) |
| **Denial of Service / Coercion** | Scammer forces victim during 30s timeout or compromised guardian stonewalls legitimate appeal | Fund lockup or forced approval | 30s timeout fails safe to `AWAITING_FALLBACK_REVIEW`; backup guardian & analyst appeal workflow with safe retry (Gate 4) |

