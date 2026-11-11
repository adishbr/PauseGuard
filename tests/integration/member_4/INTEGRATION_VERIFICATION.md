# Member 4 — Integrated Application Verification

## Purpose

Verify that PauseGuard backend, frontend and Member 4 safety modules
connect correctly and enforce the documented safety requirements.

## Current verification status

- [ ] Backend API integration
- [ ] Frontend-to-backend integration
- [x] Purpose challenge module readiness
- [x] Rolling anti-smurfing module readiness
- [x] Safe-Lock module readiness
- [x] Guardian timeout module readiness
- [x] Role and resource authorization module readiness
- [x] Audit verification module readiness
- [x] Redacted evidence export module readiness
- [x] Guardian alert privacy and localization module readiness

## Test results

- Member 4 readiness tests: 10 passed
- Combined unit, integration-readiness and backend suite: 137 passed
- Failures: 0
- Warning: Starlette/httpx TestClient deprecation warning

## Verification rules

1. Use synthetic test data only.
2. Never execute real bank or UPI transactions.
3. AI advice must never approve or execute payments.
4. Guardian timeout must never count as approval.
5. Unauthorized resource access must be rejected.
6. Safety restrictions must fail closed.
7. Record only tests that were actually executed as passed.

## Current limitation

The inspected backend currently exposes only GET /api/v2/health.
The readiness tests exercise standalone safety modules and a synthetic
test-harness composition. They do not prove connection to the backend
payment workflow or frontend.

Full application integration verification remains pending implementation
of payment, guardian and frontend workflows.
