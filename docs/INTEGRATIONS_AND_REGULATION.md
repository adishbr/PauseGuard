# External integrations and verified limits — 9 November 2026

## Official RBI guidance (don't claim RBI endorsement)
1. **RBI Authentication mechanisms for digital payment transactions Directions, 2025:** effective April 1, 2026 for providers/participants; two distinct authentication factors unless exempted, and at least one dynamic for non-card-present payments. Guardian/AI review is not a substitute for legally required authentication. https://rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=12898
2. **RBI Commercial Banks – Digital Payment Security Controls Directions, 2026**, updated October 1, 2026, discusses risk-based adaptive authentication using customer profile, transaction patterns and other factors, along with security lifecycle controls. This is an obligation for in-scope banks, NOT a certification of PauseGuard. https://www.rbi.org.in/SCRIPTS/BS_ViewMasDirections.aspx?id=13642
3. **NPCI UPI FAQ** says TPAP onboarding is through a sponsor bank and merchant access typically through an acquiring bank. Our independent PWA cannot intercept arbitrary P2P UPI. https://www.npci.org.in/what-we-do/upi/faqs

## Voice calls
- Live automated calls require a suitable provider, consent, lawful/service-call setup and calling compliance for India.
- A provider call request may be `queued`, `ringing`, `answered`, `no-answer`, `failed`, but **none** is authenticated guardian authorization.
- The prototype records a `GUARDIAN_CALL_REQUESTED` audit event; it does not place a call.
- A separate verified login or strong transaction-bound signed approval must authorize a payment. Short PIN from the phone call alone is weaker and vulnerable to SIM/call compromise.
- TRAI discusses auto-dialer/robot calls, service-call requirements and regulated communication. https://www.trai.gov.in/what-spam-or-ucc

## Location
- Phone number lookup is not live geolocation. For the logged-in user, HTML geolocation needs HTTPS and permission. https://developer.mozilla.org/en-US/docs/Web/API/Geolocation_API
- IP geolocation is approximate and cannot verify identity, coercion or intent.

## Solana and Phantom
- Solana is a blockchain for cryptographic token transactions, not a route for upgrading UPI processing speed. Its network latency/finality isn't the same as the time needed to obtain bank approval, verify fraud, reach a guardian or settle a UPI transfer.
- Phantom is a **crypto wallet**, not a UPI payment gateway or a security system for bank accounts. https://help.phantom.com/articles/41372840389651
- Use a chain only as an **optional external audit checkpoint** of hash values, with no PII. Compare cost, added integration complexity, availability and trust assumptions with cheaper append-only cloud storage.
- Solana docs: https://solana.com/docs/core/transactions

## Gateway option
Merchant UPI collection via an approved gateway can be a separate adapter after policy permits checkout. It cannot hold/cancel third-party UPI P2P transfers. Its success/failure webhooks, late reconciliation, retries and bank status require a separate asynchronous `gateway_payments` model. Never treat mock `EXECUTED` as real settlement.

## Critical business correction
A ₹500 transfer can indeed be a scam, but it is **not automatically fraudulent** because the account holder's alert preference is ₹500. Similarly ₹50,000 is not automatically safe for a business. User choice contributes to friction preferences but cannot replace calibrated, independently verified risk assessment.
