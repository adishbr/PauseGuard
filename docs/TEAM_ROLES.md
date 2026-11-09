# Confirmed team roles and boundaries

| Member | Role | Owns | Integrates with |
|---|---|---|---|
| **1 — Komal** | Core Backend & Integration Lead | FastAPI API, auth/roles, DB migrations, payment state machine, deterministic policy, guardian decision server, event/outbox, execution idempotency | Adish's UI, Gowtham/Jeevan services |
| **2 — Adish** (Atish) | Core Frontend & Integration Lead | React/TypeScript/Tailwind payer & guardian UI, consent/onboarding, risk explanations, real-time updates, timer, accessible UX | Komal's APIs, Gowtham charts, Jeevan language content |
| **3 — Gowtham** (Gautam) | Intelligence & Policy Lab | synthetic dataset, normal-business baselines, anomaly model, mule graph, structured AI review, policy simulation, metrics | Komal risk interface, Adish visuals |
| **4 — Jeevan** (Jivan) | Safety & QA | purpose challenge, anti-smurfing, Safe-Lock logic, audit verification, evidence packet, localization, security and E2E tests | Komal backend and Adish UI |

Komal and Adish are the **core pair**, jointly responsible for complete app integration. Other members develop critical supporting functions, not separate apps. Each member is a human owner even if an AI wrote code.

## First deliverable per person
1. Komal: `/api/v2/payments` and secure state transitions; runnable mock API + tests.
2. Adish: payer/guardian responsive shell wired to agreed mock responses; two-window demo.
3. Gowtham: deterministic, typed advisory object and representative synthetic personal/business test fixtures; no states modified.
4. Jeevan: anti-smurf and Safe-Lock test matrix, unauthorized access/timeout regression coverage.

## File boundaries
- Komal: `backend/app/api`, `backend/app/models`, `backend/app/policy`, migration files, backend auth.
- Adish: `frontend/src`, frontend styles/assets, documented UI tests.
- Gowtham: `backend/app/intelligence`, `synthetic_data`, `policy_lab`, advisory tests.
- Jeevan: `backend/app/safety`, `backend/app/audit`, `backend/app/recovery`, localization files, cross-cutting tests (coordinate with owners).

If a directory does not yet exist, create it only after the approved file plan. Everyone may propose changes to `docs/` but **core contract changes require Komal + Adish review**. Do not write directly to other member areas without explicit agreement.

## Teaching and handoff requirement (V3)
Every member starts at the beginner level that their own evidence supports; role prompt must explain how their module fits all the others. After each bounded task, save contract inputs/outputs, files changed, tests actually run and handoff to the next member. See `docs/TEAM_MEMBER_ONBOARDING.md`, `docs/PAYMENT_SECURITY_TESTS.md` and `docs/GITHUB_AND_REPO_SETUP.md`.
