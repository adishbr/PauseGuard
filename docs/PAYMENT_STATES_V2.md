# Frozen payment state machine V2

`CREATED` is the initial state at API processing. Risk evaluation is an event, **not** a status.

Canonical statuses:
- `AWAITING_WARNING`: payer must acknowledge warning.
- `AWAITING_STEP_UP`: independent verification required; **not implemented** yet in starter.
- `AWAITING_GUARDIAN`: awaiting assigned, enrolled guardian until server-side deadline.
- `AWAITING_FALLBACK_REVIEW`: after timeout/no guardian; AI advice **does not** mean approval.
- `READY_TO_EXECUTE`: all required checks passed, await payer final confirmation.
- `EXECUTED`, `REJECTED`, `CANCELLED`, `EXPIRED`, `FAILED`: **terminal**.

Allowed transitions (implement all checks server-side):

| From | To | Preconditions |
|---|---|---|
| CREATED | AWAITING_WARNING / AWAITING_STEP_UP / AWAITING_GUARDIAN / AWAITING_FALLBACK_REVIEW / READY_TO_EXECUTE / REJECTED | deterministic policy and hard guards |
| AWAITING_WARNING | READY_TO_EXECUTE / CANCELLED | payer acknowledgment / cancel |
| AWAITING_STEP_UP | READY_TO_EXECUTE / CANCELLED / EXPIRED / REJECTED | trusted independent verification, no bypass |
| AWAITING_GUARDIAN | READY_TO_EXECUTE / REJECTED / CANCELLED / AWAITING_FALLBACK_REVIEW | time-bound authenticated guardian decision or timeout |
| AWAITING_FALLBACK_REVIEW | READY_TO_EXECUTE / REJECTED / CANCELLED / EXPIRED | ONLY if **separate verified evidence** satisfies deterministic policy; cannot be AI recommendation alone |
| READY_TO_EXECUTE | EXECUTED / CANCELLED / REJECTED / EXPIRED / FAILED | payer confirms, rechecked policy/lock, atomic mock ledger |
| Any terminal | no transitions | irreversible |

### 30-second timer invariants
- Start based on server UTC time when `AWAITING_GUARDIAN` commits.
- Timers originate on server; client countdown is merely display.
- At the deadline, reject a late guardian approval even if fallback job hasn't run yet.
- If guardian presses approve and timeout occurs concurrently, exactly one authoritative state transition wins.
- Call connected, phone key pressed, assistant chat 'approved', GPS matching expected zone => **none** is automatically sufficient.

### Interface versions
V2 differs from V1; **do not reuse V1 `PENDING_REVIEW` as if it meant `AWAITING_STEP_UP`.** Update shared schemas, tests and clients together in a versioned pull request.

### Implemented subset
The Python starter implements CREATE, WARN_ACK, guardian approve/reject, fallback activation, payer cancel, payer confirmation, terminal state protection and Safe-Lock. It does not yet implement a genuine step-up route, durable outbox, actual caller, production IAM or bank APIs.
