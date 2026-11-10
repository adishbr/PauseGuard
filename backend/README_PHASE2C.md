# Phase 2C offline interfaces and guards

This backend remains an offline mock foundation with a health route only. No
payment route, payment schema, balance mutation, idempotency store or execution
service has been added. No database, migration command, network or dotenv access
is required by these additions. Canonical V2 docs remain the contract.

`app/services/transactions.py` borrows an unused session and owns one explicit
transaction. `get_db` retains sole ownership of session close. Existing/autobegun
transactions are rejected without commit, rollback or close. Body exceptions and
cancellation roll back; rollback failure preserves the primary failure. Begin and
commit errors are sanitized. Commit failure has unknown outcome: never retry it
blindly. The caller must not commit/rollback within the scope. This is generic
transaction infrastructure, not an implemented atomic payment unit of work.

`payment_guards.py` reproduces canonical adjacency only (25 edges, terminal states
have none). An allowed edge is not authorization. Guardian approval checks assigned
server identity, guardian role, current review state, aware server timestamps,
strictly-before-deadline response, and explicit hard-policy permission; its only
result is READY_TO_EXECUTE. Payer confirmation is separate and requires the owning
payer, READY_TO_EXECUTE, fresh hard-policy permission and binary unlocked state.
Missing/nonboolean Safe-Lock state fails closed. These pure checks do not establish
enrollment, consent, anti-replay, proof freshness or serialization. A guardian cannot
execute. No automatic fallback release exists.
The paired timeout check permits only AWAITING_FALLBACK_REVIEW at/after the committed
deadline; a future service must serialize it against guardian decisions.

`TrustedActorContext` represents already authenticated server identity and persisted
grants. Constructing it is not authentication. Do not deserialize it from API input
or trust request roles/UUIDs. No auth dependency currently constructs one.

`foundation_queries.py` returns parameterized ORM statements with FOR UPDATE for
persisted role grants, an account constrained by account ID AND owner ID, and binary
Safe-Lock state. It does not execute queries or grant permissions. Use only within
an explicitly owned transaction after authenticating the actor. PostgreSQL behavior
has not been tested. FOR UPDATE cannot lock missing rows; missing Safe-Lock must
fail closed. Lock ordering, row provisioning and grant revocation concurrency still
need review. Persisted roles alone do not establish guardian assignment.
All three locking queries set `populate_existing=True` so ORM reads refresh
already-loaded attributes instead of retaining stale identity-map values (the
session factory uses `expire_on_commit=False`). Complete locking reads on a clean
session before changing any attributes; refresh can discard pending changes and
autoflush is disabled. Then validate and mutate within that same transaction.
This discipline still requires live PostgreSQL concurrency tests and reviewed lock
ordering; the offline assertions verify query options, not database behavior.

`safety_advice.py` accepts Member 4's purpose assessor through a Protocol; it emits
only advisory suspicion and availability, always with can_authorize_payment=false.
Unavailable/malformed results are cautious. Raw helper reasons are not canonical
reason codes. The actual purpose helper is exercised offline via injection.
Other Member 4 helpers were reviewed but intentionally not wired: the amount/category
Safe-Lock helper cannot weaken the binary hard lock; the access helper lacks analyst
support and guardian assignment; in-memory anti-smurfing/audit helpers are not durable
idempotency or audit persistence. Timeout advice is not authoritative state mutation.
Privacy/evidence helpers do not settle consent, retention or outbox semantics.

Before a payment service can execute, Komal + Adish must review payment identity,
versioning and timestamps; beneficiary/ledger and insufficient-funds semantics;
durable actor/operation/key scoping, request fingerprint, result replay and concurrent
claim rules; atomic payment + debit/credit + idempotency result + durable audit/outbox
commit and crash recovery; guardian enrollment/assignment, bound expiry and anti-replay;
trusted independent evidence and canonical reason mappings; lock order and Safe-Lock
provisioning. No Protocol invents these unresolved storage operations. Any eventual
atomic execution contract must make all listed durable writes succeed or roll back
together, with post-commit outbox delivery. Schema, routes and migrations need their
own reviewed plan. Live PostgreSQL concurrency/integration testing remains separate.

Acceptance: exhaustive topology pairs; guardian deadline/actor/hard-policy cases;
separate payer confirmation with binary-lock fail-closed cases; transaction failures,
cancellation and rollback failure; parameterized PostgreSQL query compilation; injected
Member 4 advice, malformed outputs and cancellation. All run under the existing
collection-time network/database/dotenv guards. Offline compilation is not database
constraint enforcement, durable replay safety or production authentication.

Validation run on 10 November 2026 using the existing backend virtual environment:

- `python -B -m pytest -p no:cacheprovider`: 351 passed, 1 pre-existing
  Starlette/httpx deprecation warning; 252 new Phase 2C cases. No test failures.
- In-memory `compile()` on 34 application/test/migration Python files: passed;
  migration source was compiled, never executed.
- `python -B -m pip check`: no broken requirements.
- `git diff --check` and a separate whitespace scan of all ten new Phase 2C
  files: passed. Phase 2B files already present were left unchanged.

No PostgreSQL constraints, locking, concurrent transitions, durable audit or replay
behavior were exercised. No API request/response contracts changed. Handoff is for
independent Phase 2C review before any Phase 2D work or execution implementation.
