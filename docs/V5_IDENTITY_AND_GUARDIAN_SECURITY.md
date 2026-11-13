# PauseGuard V5.0 — Identity Assurance & Guardian Security Design

> **Threat Focus:** Eliminating fake guardians, payer self-approval via secondary emails, OTP brute-force, session hijacking, and raw KYC data retention.

---

## 1. Separation of Trust Layers

| Layer | Question Answered | Mechanism in V5.0 | Insufficient Alone For |
| :--- | :--- | :--- | :--- |
| **1. Contact Verification** | Does the user currently control email/phone X? | 6-digit CSPRNG OTP, HMAC-SHA256 salted digest in `otp_challenges`, max 5 tries, 300s TTL, 30s cooldown | Proving distinct legal identity from payer |
| **2. Authentication** | Is this request from account A? | `scrypt` salted password hash -> opaque 256-bit bearer token stored as SHA-256 digest in `user_sessions` | Authorizing payments or claiming admin roles |
| **3. Identity Assurance** | Has a trusted authority verified human H? | Server-issued `IdentityAssurance` (`trusted_person_ref`) via `IdentityAssuranceProvider` | Payment execution without safe lock / payer confirm |

---

## 2. Anti-Collusion & Anti-Self-Guardianship Controls

1. **Email & User ID Distinctness Check:** Invitation creation and acceptance reject matching user IDs or normalized emails.
2. **Opaque `TrustedPersonRef` Equality Check:** Even if Attacker Alice registers `alice@example.com` (Payer) and `alice.alt@example.com` (Guardian) and verifies two phone numbers/emails, if `SyntheticLocalIdentityProvider` resolves both to the same underlying synthetic person reference, `/invitations/{id}/accept` fails closed with `403 Forbidden` and logs an audit event.
3. **Guardian Consent & Instant Revocation:** A guardian enrollment becomes `ACTIVE` only after explicit guardian acceptance + consent. Either the payer or the enrolled guardian can revoke at any time (`REVOKED`), immediately preventing further payment assignments or approvals.

---

## 3. Privacy & Secret Hygiene

- **Passwords:** `hashlib.scrypt(n=2**14, r=8, p=1)` with 16-byte per-user CSPRNG salt. Never logged or serialized.
- **OTP Codes:** Generated via `secrets.randbelow(1_000_000)` (`06d`), stored solely as `HMAC-SHA256(pepper, salt || otp)`. Deleted/invalidated upon expiry, consumption, or max-attempt lockout. Never written to logs or audit events.
- **Session & Invite Tokens:** Returned once upon issuance; stored strictly as `SHA-256(token)`.
- **Synthetic KYC Evidence:** Only non-reversible opaque `trusted_person_ref` (`tpr_...`) and provider evidence hash stored; raw document references discarded immediately after verification.
- **Role Safety:** Public signup accepts strictly `"payer"` or `"guardian"`. `"admin"` and `"analyst"` registration attempts return `403 Forbidden`.

