# Phase 2B offline preparation

No migration has been applied. Online Alembic execution is deliberately disabled,
including configurations with an injected connection. Configuration contains no
database URL and reads no environment variables or dotenv files.

`env.py` registers the existing `Base.metadata` through `app.models.metadata`.
Revision `0001_offline_foundation` freezes its own explicit schema declarations;
it does not import mutable ORM definitions. The template supports later reviewed
revisions. Installed tooling is pinned in `requirements-migrations.txt`.

Upgrade assumes an empty application schema: users, role bindings, accounts,
account-owner index, then Safe-Lock state. Downgrade removes Safe-Lock state,
the account-owner index, accounts, role bindings, then users. Downgrade destroys
these tables and their data; it needs explicit authorization before execution.
There are no seeds, grants, triggers, extensions or server UUID defaults.
Alembic would manage its own version table when execution is authorized.

UUID defaults, optimistic version increments and `updated_at` updates are ORM
behavior, not database triggers. PostgreSQL timezone-capable columns use `now()`;
future connections must normalize application timestamps consistently.

Offline tests inspect revision syntax and reconstruct SQLAlchemy table declarations
to compile PostgreSQL DDL. They never call revision upgrade/downgrade functions or
Alembic migration commands. Compilation is not PostgreSQL constraint enforcement.

## Future isolated PostgreSQL tests

`tests/postgres_config.py` validates an explicitly supplied mapping only:

- `PAUSEGUARD_POSTGRES_TEST_AUTHORIZED` must equal `true`.
- `PAUSEGUARD_POSTGRES_TEST_URL` must use psycopg2, an exact loopback IP and a
  nonempty `pauseguard_test_` database name. URL query overrides are rejected.
- URLs are held as `SecretStr`; validation errors omit supplied values.

This is a configuration gate, not proof of human approval or database isolation.
It supplies no database runner, connection fixture or migration executor. Existing
offline guards remain enabled. Do not supply live credentials or use backend/.env.

Before a separately authorized integration phase, review the target and provision
a disposable PostgreSQL database with a dedicated role whose privileges are limited
to that database. Review a separate test runner before adding connections; never
disable the offline suite's guards globally. Then verify upgrade/downgrade on empty
disposable schemas, constraint violations, timezone round trips, rollback, restrictive
deletes and stale-version concurrency. No such tests have run in this phase.
