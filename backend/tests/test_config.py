import traceback
from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from app.config import ConfigurationError, Settings, load_settings


def test_defaults_and_injected_environment():
    assert load_settings({}) == Settings(environment="local", mode="mock", allow_demo_auth=False)
    assert load_settings({"PAUSEGUARD_ENVIRONMENT": "test"}).environment == "test"
    assert load_settings({}).allow_demo_auth is False


def test_only_allowlisted_environment_keys_are_read():
    class AllowlistedEnvironment(Mapping):
        def __getitem__(self, key):
            assert key in {
                "PAUSEGUARD_ENVIRONMENT",
                "PAUSEGUARD_MODE",
                "PAUSEGUARD_ALLOW_DEMO_AUTH",
                "PAUSEGUARD_ENABLE_DEMO_AUTH",
            }
            raise KeyError(key)

        def __iter__(self):
            pytest.fail("The environment must not be enumerated.")

        def __len__(self):
            pytest.fail("The environment must not be enumerated.")

    assert load_settings(AllowlistedEnvironment()) == Settings()


def test_demo_auth_opt_in_from_environment():
    assert load_settings({"PAUSEGUARD_ALLOW_DEMO_AUTH": "true"}).allow_demo_auth is True
    assert load_settings({"PAUSEGUARD_ENABLE_DEMO_AUTH": "1"}).allow_demo_auth is True
    assert load_settings({"PAUSEGUARD_ALLOW_DEMO_AUTH": "false"}).allow_demo_auth is False
    assert load_settings({"PAUSEGUARD_ALLOW_DEMO_AUTH": "0"}).allow_demo_auth is False


def test_settings_demo_auth_aliases_and_properties():
    s1 = Settings(allow_demo_auth=True)
    assert s1.allow_demo_auth is True
    assert s1.enable_demo_auth is True

    s2 = Settings(enable_demo_auth=True)
    assert s2.allow_demo_auth is True
    assert s2.enable_demo_auth is True


def test_process_environment_is_validated(monkeypatch):
    monkeypatch.setenv("PAUSEGUARD_ENVIRONMENT", "test")
    monkeypatch.setenv("PAUSEGUARD_MODE", "mock")
    assert load_settings() == Settings(environment="test")


@pytest.mark.parametrize(
    "values",
    [
        {"PAUSEGUARD_ENVIRONMENT": "production"},
        {"PAUSEGUARD_MODE": "real"},
        {"PAUSEGUARD_ENVIRONMENT": ""},
        {"PAUSEGUARD_ENVIRONMENT": "TEST"},
    ],
)
def test_unsupported_environment_or_mode_fails_closed(values):
    with pytest.raises(ConfigurationError):
        load_settings(values)


def test_invalid_configuration_does_not_expose_input():
    marker = "synthetic-sensitive-marker"
    with pytest.raises(ConfigurationError) as captured:
        load_settings({"PAUSEGUARD_ENVIRONMENT": marker})
    assert marker not in "".join(traceback.format_exception(captured.value))


def test_typed_settings_reject_extra_fields_and_are_frozen():
    with pytest.raises(ValidationError):
        Settings(unknown=True)
    with pytest.raises(ValidationError):
        Settings().environment = "test"


def test_direct_validation_message_hides_input():
    with pytest.raises(ValidationError) as captured:
        Settings(environment="synthetic-sensitive-marker")
    assert "synthetic-sensitive-marker" not in str(captured.value)
