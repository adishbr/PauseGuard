# Payment security and adversarial test matrix — V2

**No test is claimed passed merely because it is in this document.** Use synthetic fixtures. Actual implementation results go in PR and `docs/PROGRESS.md`.

| ID | Scenario | Expected invariant |
|---|---|---|
| PAY-01 | legitimate ₹100 familiar merchant payment | allow without guardian if policy low-risk |
| PAY-02 | normal ₹3 lakh business supplier payment | profile-aware, no automatic guardian just because amount/new recipient |
| PAY-03 | ₹55,000 coerced payment with critical risk | non-executable pending restriction |
| PAY-04 | guardian does not respond in 30s | no auto-execution; safe fallback |
| PAY-05 | guardian responds after expiry | reject late stale decision |
| PAY-06 | guardian approves while payer cancels | exactly one valid terminal transition; never double-transfer |
| PAY-07 | guardian rejects then malicious client replays approve | rejected remains final |
| PAY-08 | duplicate payment POST with same idempotency key | only one payment created/executed |
| PAY-09 | different payload same idempotency key | conflict returned; not reused |
| PAY-10 | Safe-Lock enabled during pending payment | final check blocks prohibited execution |
| PAY-11 | user lowers personal threshold while coerced | cooldown/step-up; cannot override hard fraud controls |
| PAY-12 | user selects business label without verification | no automatic exemptions |
| PAY-13 | scam recipient already trusted | confirmed fraud flag still overrides familiarity |
| PAY-14 | merchant checkout webhook spoofed | reject invalid signature |
| PAY-15 | WebSocket disconnect/reconnect | frontend reloads authoritative state |
| PAY-16 | backend restarts during review | deadline/status recovered from DB |
| PAY-17 | AI service times out | no AI-based auto-approval; deterministic safe behavior |
| PAY-18 | AI says 'approve' but registry hit | policy still restricts |
| PAY-19 | unauthorized guardian reads another customer's request | 403 or equivalent, no details leaked |
| PAY-20 | sensitive details present in socket payload | enforce redaction, fail test if leaked |
| PAY-21 | guardian phone stolen/revoked | cannot approve after revocation |
| PAY-22 | three smaller transactions evade per-payment threshold | rolling aggregate risk signal detected |
| PAY-23 | same transaction retried after network failure | no balance double-debit |
| PAY-24 | audit event locally edited | hash chain verification fails |
| PAY-25 | admin deletes local logs | independent checkpoint/backup reveals missing records if implemented |
| PAY-26 | scammer instructs user to claim emergency | emergency claim alone doesn't authorize |
| PAY-27 | geolocation permission denied | usable path; not automatically 'fraud' |
| PAY-28 | fabricated AI transcript | provenance validation / ignore untrusted data |
| PAY-29 | simulated payment rejected then Recovery Assist used | evidence packet labels payment never executed |
| PAY-30 | completed real UPI payment recovery button | only guidance and report status; no false reversal claim |

## Required minimum before merge
Every affected module has at least unit + contract test; core payments require race/idempotency/integration tests. UI tests assert backend-reconciled state after refresh. No fabricated '100% detection' claims. Record test command, date, passed/failed and failures honestly.
