import traceback

import pytest
from sqlalchemy.engine import URL

from tests.postgres_config import PostgresTestConfigurationError, load_postgres_test_configuration


def target(**overrides):
    fields = {"drivername": "postgresql+psycopg2", "host": "127.0.0.1",
              "database": "pauseguard_test_fixture", "username": "synthetic_test_role"}
    fields.update(overrides)
    return URL.create(**fields).render_as_string(hide_password=False)


def configuration(url):
    return {"PAUSEGUARD_POSTGRES_TEST_AUTHORIZED": "true", "PAUSEGUARD_POSTGRES_TEST_URL": url}


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_explicit_local_target_is_validated_without_io(host):
    url = target(host=host)
    result = load_postgres_test_configuration(configuration(url))
    assert result.database_url.get_secret_value() == url
    assert url not in repr(result)


@pytest.mark.parametrize("values", [{}, {"PAUSEGUARD_POSTGRES_TEST_AUTHORIZED": "false"},
                                    {"PAUSEGUARD_POSTGRES_TEST_AUTHORIZED": "TRUE"}])
def test_test_configuration_disabled_by_default(values):
    with pytest.raises(PostgresTestConfigurationError, match="not enabled"):
        load_postgres_test_configuration(values)


@pytest.mark.parametrize("url", [
    "synthetic-private-invalid-input", target(host="database.invalid"), target(host="localhost"),
    target(database="postgres"), target(database="pauseguard_test_"), target(username=None),
    target(drivername="postgresql"), target(query={"host": "database.invalid"}), target(port=0),
])
def test_invalid_target_is_rejected_without_input_in_errors(url):
    with pytest.raises(PostgresTestConfigurationError) as captured:
        load_postgres_test_configuration(configuration(url))
    assert url not in "".join(traceback.format_exception(captured.value))


def test_missing_test_url_has_safe_error():
    with pytest.raises(PostgresTestConfigurationError, match="Invalid disposable"):
        load_postgres_test_configuration({"PAUSEGUARD_POSTGRES_TEST_AUTHORIZED": "true"})
