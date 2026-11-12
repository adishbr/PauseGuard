"""Integration test configuration for authorized PostgreSQL testing.

This module must be run with explicit environment variables:
- PAUSEGUARD_POSTGRES_TEST_AUTHORIZED=true
- PAUSEGUARD_POSTGRES_TEST_URL=postgresql+psycopg2://user@127.0.0.1:5432/pauseguard_test_*
- PAUSEGUARD_POSTGRES_TEST_PASSWORD (optional, for password-protected databases)

It does NOT install offline guards. Network and database access are permitted.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, make_url, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.database import create_database_engine, create_session_factory
from tests.postgres_config import PostgresTestConfiguration, load_postgres_test_configuration


TEST_ALEMBIC_INI = Path(__file__).parent / "alembic.ini"
TEST_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _load_test_config() -> PostgresTestConfiguration:
    """Load and validate the PostgreSQL test configuration from environment."""
    env = dict(os.environ)
    # Safely encode a separately supplied PostgreSQL password.
    password = env.get("PAUSEGUARD_POSTGRES_TEST_PASSWORD")
    if password is not None and "PAUSEGUARD_POSTGRES_TEST_URL" in env:
        url = make_url(env["PAUSEGUARD_POSTGRES_TEST_URL"])
        if url.password is None:
            env["PAUSEGUARD_POSTGRES_TEST_URL"] = (
                url.set(password=password)
                .render_as_string(hide_password=False)
            )
        # Clear the password from the environment mapping copy to prevent leakage
        env.pop("PAUSEGUARD_POSTGRES_TEST_PASSWORD", None)
    return load_postgres_test_configuration(env)


@pytest.fixture(scope="session")
def pg_test_config() -> PostgresTestConfiguration:
    """Load the authorized PostgreSQL test configuration."""
    return _load_test_config()


@pytest.fixture(scope="session")
def pg_engine(pg_test_config: PostgresTestConfiguration) -> Iterator[Engine]:
    """Create a database engine for the test database."""
    engine = create_database_engine(pg_test_config.database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def pg_session_factory(pg_engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to the test engine."""
    return create_session_factory(pg_engine)


@pytest.fixture
def pg_session(pg_session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Provide a clean session for each test with automatic rollback on failure."""
    session = pg_session_factory()
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture(scope="session", autouse=True)
def alembic_upgrade_downgrade(pg_engine: Engine) -> Iterator[None]:
    """Run Alembic upgrade before tests and downgrade after all tests complete."""
    from alembic import command
    from alembic.config import Config

    from app.models.metadata import metadata

    # Use test-only Alembic environment (separate from production)
    config = Config(str(TEST_ALEMBIC_INI))
    config.set_main_option("script_location", str(TEST_MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", pg_engine.url.render_as_string(hide_password=True))

    # Ensure clean state - drop all application tables first
    metadata.drop_all(pg_engine)

    # Also drop alembic_version table if left over from an interrupted previous run
    with pg_engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
        conn.commit()

    # Run upgrade with its own connection
    with pg_engine.connect() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
        conn.commit()

    try:
        yield
    finally:
        # Run downgrade to clean up with a fresh connection
        with pg_engine.connect() as conn:
            config.attributes["connection"] = conn
            command.downgrade(config, "base")
            conn.commit()


@pytest.fixture(autouse=True)
def reset_sequence(pg_session_factory: sessionmaker[Session], pg_engine: Engine) -> Iterator[None]:
    """Reset sequences and clear data between tests."""
    yield
    from app.models.metadata import metadata
    from sqlalchemy import delete, inspect

    inspector = inspect(pg_engine)
    existing_tables = set(inspector.get_table_names())

    session = pg_session_factory()
    try:
        for table in reversed(metadata.sorted_tables):
            if table.name in existing_tables:
                session.execute(delete(table))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
