# Member 4 — Jeevan (Jivan) | Safety, privacy, recovery and QA
You own supporting security controls and cross-module test coverage.

**Scope:** purpose challenge, rolling anti-smurfing, Safe-Lock policy integration, audit/hash verification, redacted evidence export, privacy-safe guardian alerts, localization strings, reporting guidance and tests of the whole end-to-end flow.

**Do not:** make standalone money-moving code, directly alter canonical state enums, expose full financial data to guardians/admin, assert hash chain is tamper-proof, promise recovery of real UPI transactions, or make real 1930 submissions without human action.

**First task to propose:** inspect V2 tests and risk contracts; write acceptance tests for guardian unavailability, privacy, cancellation races, split payments and Safe-Lock before adding functions. Coordinate hooks with Komal.

**Required tests:** 30s timeout no execution; role/IDOR rejection; purpose challenge coercion strings; duplicated attempts not double-counted; Safe-Lock restrictions; audit tampering detected; encrypted transport plan; evidence minimization; locale fallback.

**Handoff:** test matrix, commands/output, changed modules, risk/failure cases, coverage gaps and privacy/security review notes.
