"""Test-only Alembic environment for integration tests.

This module is ONLY used by the integration test runner.
It allows online migration execution with an injected connection.
The production env.py at backend/migrations/env.py remains offline-only.
"""

from alembic import context

from app.models.metadata import metadata


def run_migrations_online(connection) -> None:
    """Run migrations in online mode with the provided connection."""
    context.configure(
        connection=connection,
        target_metadata=metadata,
        transactional_ddl=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Run migrations in offline mode (for reference/testing)."""
    context.configure(
        dialect_name="postgresql",
        target_metadata=metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transactional_ddl=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    # Online mode: connection must be provided via config.attributes["connection"]
    connection = context.config.attributes.get("connection")
    if connection is None:
        raise RuntimeError("Online migrations require config.attributes['connection'] to be set.")
    run_migrations_online(connection)