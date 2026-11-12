"""Offline-only Alembic environment. No environment variables or dotenv access."""

from alembic import context

from app.models.metadata import metadata


def run_migrations_offline() -> None:
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
    # Do not accept injected connections or URLs until a later reviewed phase.
    raise RuntimeError("Online migrations are disabled pending separate authorization.")
