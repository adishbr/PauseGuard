"""Pure configuration validation for a future authorized local disposable DB.

No fixtures, connections, environment reads or migration execution live here.
An explicit mapping must be supplied by a separately reviewed test runner.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import SecretStr
from sqlalchemy.engine import make_url


class PostgresTestConfigurationError(ValueError):
    """Configuration error without target or credential details."""


@dataclass(frozen=True)
class PostgresTestConfiguration:
    database_url: SecretStr


def load_postgres_test_configuration(values: Mapping[str, str]) -> PostgresTestConfiguration:
    if values.get("PAUSEGUARD_POSTGRES_TEST_AUTHORIZED") != "true":
        raise PostgresTestConfigurationError("Disposable PostgreSQL testing is not enabled.")
    try:
        value = values["PAUSEGUARD_POSTGRES_TEST_URL"]
        url = make_url(value)
        if (
            url.drivername != "postgresql+psycopg2"
            or url.host not in {"127.0.0.1", "::1"}
            or not url.database
            or not url.database.startswith("pauseguard_test_")
            or url.database == "pauseguard_test_"
            or not url.username
            or url.query
            or (url.port is not None and not 1 <= url.port <= 65535)
        ):
            raise ValueError
    except Exception:
        raise PostgresTestConfigurationError("Invalid disposable PostgreSQL test configuration.") from None
    return PostgresTestConfiguration(database_url=SecretStr(value))
