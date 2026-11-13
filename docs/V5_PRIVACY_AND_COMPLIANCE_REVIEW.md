# PauseGuard V5.0 — Privacy, Data Protection & Compliance Review

## 1. Data Minimization & Role Separation
- **Identity Assurance Privacy (`backend/app/services/identity_assurance_service.py`):** Raw synthetic identity document references are normalized solely in memory to compute an irreversible HMAC-SHA256 `trusted_person_ref` and immediately discarded; raw document strings are never persisted or exposed in API responses.
- **Guardian Privacy Redaction (`RedactedPaymentView` & `sanitize_notification_payload`):** Assigned guardians receive strict risk classification and deadline alerts without payer balances, beneficiary IDs, exact `amount_paise`, or private payment purpose strings.
- **Contact Verification vs. Identity Assurance vs. Session Auth:** Emails, salted HMAC OTP challenges (`otp_challenges`), hashed bearer sessions (`user_sessions`), and independent personhood assertions (`identity_assurances`) are modeled separately to prevent multi-account self-guardianship collusion.

## 2. Consent, Revocation & Fail-Closed Guarantees
- Guardian enrollment requires independent human KYC, explicit opt-in consent (`consent_confirmed=True`), and supports immediate payer revocation (`/invitations/{id}/revoke`) and emergency compromise suspension (`/invitations/{id}/suspend`).
- **No Unattended Execution:** Guardian deadline expiry transitions payments cleanly to `AWAITING_FALLBACK_REVIEW` and never auto-executes transfers.
- **AI Advisory Constraint:** Fraud intelligence modules return advisory risk scores/reason codes (`can_authorize_payment = False`); execution occurs strictly inside server-side state machine transitions.
- **Honest Non-Claims:** Synthetic scenario Policy Lab benchmarks (`is_synthetic = True`) do not represent production bank accuracy or regulatory certification.

