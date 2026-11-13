# PauseGuard V5.0 — Team Ownership & Gate Execution Handoff

| Gate | Scope | Lead Owner(s) | Branch | Exit Criteria |
| :--- | :--- | :--- | :--- | :--- |
| **GATE 0** | Frozen V4.1 Baseline + Gate 0 UX Fixes | All | `fix/v4-1-gate0-closure` | **DONE** (`10a365f`, `1035` offline + `76` PG CI + `4/4` live Playwright E2E) |
| **GATE 1** | Repository Audit, Gap Matrix & V5 Docs | All | `feature/v5-backend-identity-payments` | **DONE** (6 shared V5 specs verified against codebase) |
| **GATE 2** | Real Auth (Signup/Login/OTP), Synthetic KYC, Durable Guardian Invites + Anti-Smurfing Fix | Komal + Jeevan | `feature/v5-backend-identity-payments` | Alembic `0005` + offline & PG CI pass (`Tests 1–5, 11, 19`) |
| **GATE 3** | Frontend Signup/OTP/KYC UI, Guardian Invite/Consent Flow, Clean Admin/Razorpay Framing | Adish | `feat/v5-frontend-experience` | `npm run build/lint/test` + live Playwright E2E green |
| **GATE 4** | Immutable Approval Snapshot, Safe Retry, False-Alert Appeals, Backup/Compromised Guardian, Step-Up | Komal + Adish | `feature/v5-backend-identity-payments` / `feat/v5-frontend-experience` | Concurrency, timeout, appeal & snapshot tests pass |
| **GATE 5** | WS Ticket Auth (`/api/v2/ws/ticket`), Durable Outbox Notifications, Extended Risk & Policy Lab | Jeevan + Gowtham | `feat/v5-fraud-intelligence` / `feature/v5-security-reliability` | Outbox + WS ticket + Policy Lab + calibration tests pass |
| **GATE 6** | Bank Pre-Execution Adapter + Mock Rail Webhook + Razorpay Test Mode Parity | Komal | `feature/v5-backend-identity-payments` | Signed settlement simulation + strict Test Mode isolation |
| **GATE 7** | 20+ Acceptance Suite, Latency/Load Benchmarks, Observability & Privacy Review | Jeevan | `feature/v5-security-reliability` | All 20 acceptance scenarios + benchmark measurements verified |
| **GATE 8** | B2B2C Commercialization Calculator, Pilot Docs & Final Integrated CI Pass | All | Integrated PRs | Complete test & documentation verification |

