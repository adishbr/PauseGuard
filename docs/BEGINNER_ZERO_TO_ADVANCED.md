# Beginner-to-advanced learning path — PauseGuard V2

**Audience:** all four teammates, including people who have never used Git, APIs, VS Code-like IDEs, or tests. **Teaching style:** one actionable step at a time, wait for evidence before proceeding. Never assume installation completed.

## Level 0 — The project in plain language
A person can approve a UPI payment while being manipulated. PauseGuard simulates an extra security check **before** a mock transfer executes. It uses profile-aware signals, a deterministic policy, optional guardian/business reviewer assistance, and optional AI advice. A guardian timeout is not approval. It also supports incident reporting after fraud; it cannot magically reverse already completed real UPI transactions.

## Level 1 — Know the building blocks
- **Frontend:** what customers/guardians see. React + TypeScript + Tailwind.
- **Backend:** handles permissions and payment decisions. FastAPI/Python.
- **API:** the documented message format between frontend and backend.
- **Database:** stores transaction state; SQLAlchemy, SQLite locally, PostgreSQL if deployed and tested.
- **Risk signals:** advisory observations from rules or ML; never their own authorization.
- **Test:** repeatable check that verifies a condition actually holds.
- **Git:** records changes; **GitHub:** hosts the team's single shared repository.

## Level 2 — First computer check
1. Open Antigravity and the real PauseGuard repo folder. Verify the terminal uses PowerShell, not failing WSL.
2. Run `git --version`; report output. Do not continue if Git is missing.
3. Run `node --version` and `npm --version`; report outputs. Do not blindly reinstall.
4. Run `python --version`; report output. Do not choose another Python version without discussion.
5. Run `opencode --version`; if command missing, follow `INSTALL_OPENCODE_WINDOWS.md`.
6. Open repo and read `AGENTS.md`/contracts; do not code merely because tools are available.

**Important:** An AI coach should present *only one step per response*. This file is a reference checklist, not an instruction to execute all steps at once.

## Level 3 — Learn the shared transaction flow
1. User creates request in payer UI.
2. Backend validates identity, amount in integer paise, beneficiary and Safe-Lock.
3. Advisory engines return structured signals.
4. Deterministic policy chooses allow/warn/step-up/restrict.
5. If appropriate, guardian gets limited request with configurable 30/45/60-second response window; AI review runs in parallel without payment authority.
6. Backend verifies final action, state, idempotency and risks, then executes mock transfer at most once.
7. Audit and Recovery Assist record outcome.
Explain one legitimate personal, one legitimate business and one fraudulent scenario without looking at a diagram.

## Level 4 — Your owned module
Read `docs/TEAM_ROLES.md`, then `prompts/MEMBER_<n>_*.md`. Describe inputs, outputs, files to touch, three tests. Make a small plan, implement in an isolated branch after permission, run tests, record actual results.

## Level 5 — Independent integration
Pull latest `main`, resolve approved contracts, exercise payer/guardian E2E, observe backend state, check error cases and review diff. Never merge without human review.

## Level 6 — Advanced/product readiness
Threat-model guardian compromise, AI prompt injection, race conditions, privacy leakage, spoofed webhook, attacker's repeated small payments. Distinguish simulation from actual bank integration. Understand hosting, monitoring, DPA/consent, partner arrangements and live-money risks before claiming real-world readiness.

## Evidence gate for AI guide
At each step, request a screenshot or pasted output with credentials redacted; say **passed / not yet verified / blocked**, then give only the next step. Explain every command before execution and do not edit code in an environment-setup step.
