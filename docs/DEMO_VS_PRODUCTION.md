# Capabilities: demo vs production vs partner-required

| Feature | Mock prototype | Real-world dependency |
|---|---|---|
| User profile and rules | yes | authorized reliable customer data for personalized production |
| Guardian review in app | yes | security, identity, consent and operational reliability |
| Automated guardian calls | simulated or sandbox | telephony provider, verification, costs, consent |
| AI conversation analysis | synthetic transcript demo | consented audio ingestion, evaluation, privacy |
| Cancellable pending transfer | yes before mock execution | bank/PSP if applied to real UPI P2P |
| Revoke already settled UPI P2P | no | bank/regulatory dispute process; no blanket reversibility |
| Real merchant checkout | optional Razorpay sandbox | verified merchant onboarding, fees, provider API |
| Safe-Lock | mock rail only | payment operator/bank cooperation to affect bank account |
| Mule graph | fictional network | bank/network-level data access and validation |
| Hash-chained audit | yes | stronger admin separation, external snapshots/anchoring if needed |
| Recovery Assist | evidence + official guidance | actual bank/cybercrime action beyond our app |

## Public-facing claims
State 'synthetic, simulated payment', 'advisory AI', 'conditional guardian', 'refund not guaranteed', 'no bank integration'. Avoid 'production-ready bank security', 'unhackable blockchain', '98% fraud prevention' without evidence. Product deployment requires regulatory and partner review. Hackathon onsite code provenance must be transparent.
