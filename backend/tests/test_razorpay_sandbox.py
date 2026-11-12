
import pytest

from app.auth.identities import (
    SYNTHETIC_ADMIN,
    SYNTHETIC_ANALYST,
    SYNTHETIC_GUARDIAN,
    SYNTHETIC_PAYER,
)
from app.integrations.razorpay_sandbox import (
    RazorpaySandboxError,
    authorize_sandbox_access,
    load_sandbox_config,
    require_sandbox_admin,
)


def valid_environment():
    return {
        "PAUSEGUARD_RAZORPAY_TEST_ENABLED": "true",
        "RZP_TEST_KEY_ID": "rzp_test_example123",
        "RZP_TEST_KEY_SECRET": "synthetic-test-secret",
    }


def test_sandbox_is_disabled_by_default():
    with pytest.raises(RazorpaySandboxError, match="disabled"):
        load_sandbox_config({})


def test_missing_credentials_are_rejected():
    with pytest.raises(RazorpaySandboxError, match="missing"):
        load_sandbox_config({
            "PAUSEGUARD_RAZORPAY_TEST_ENABLED": "true",
        })


def test_empty_credentials_are_rejected():
    environment = valid_environment()
    environment["RZP_TEST_KEY_SECRET"] = "   "

    with pytest.raises(RazorpaySandboxError, match="missing"):
        load_sandbox_config(environment)


def test_live_key_is_rejected():
    environment = valid_environment()
    environment["RZP_TEST_KEY_ID"] = "rzp_live_example123"

    with pytest.raises(RazorpaySandboxError, match="Test Mode"):
        load_sandbox_config(environment)


def test_malformed_key_prefix_is_rejected():
    environment = valid_environment()
    environment["RZP_TEST_KEY_ID"] = "invalid_key"

    with pytest.raises(RazorpaySandboxError):
        load_sandbox_config(environment)


def test_valid_test_credentials_are_loaded():
    config = load_sandbox_config(valid_environment())

    assert config.key_id == "rzp_test_example123"
    assert config.key_secret == "synthetic-test-secret"


def test_credentials_are_not_exposed_in_repr():
    config = load_sandbox_config(valid_environment())

    assert "synthetic-test-secret" not in repr(config)
    assert "rzp_test_example123" not in repr(config)


@pytest.mark.parametrize(
    "actor",
    [
        SYNTHETIC_PAYER,
        SYNTHETIC_GUARDIAN,
        SYNTHETIC_ANALYST,
    ],
)
def test_non_admin_roles_are_rejected(actor):
    with pytest.raises(RazorpaySandboxError, match="Administrator"):
        require_sandbox_admin(actor)


def test_admin_role_is_accepted():
    require_sandbox_admin(SYNTHETIC_ADMIN)


def test_missing_trusted_actor_is_rejected():
    with pytest.raises(RazorpaySandboxError, match="Trusted"):
        require_sandbox_admin(None)


def test_authorized_admin_can_access_configured_sandbox():
    config = authorize_sandbox_access(
        SYNTHETIC_ADMIN,
        valid_environment(),
    )

    assert config.key_id == "rzp_test_example123"


def test_non_admin_cannot_access_sandbox_even_with_valid_credentials():
    with pytest.raises(RazorpaySandboxError, match="Administrator"):
        authorize_sandbox_access(
            SYNTHETIC_PAYER,
            valid_environment(),
        )


def test_non_string_enable_flag_is_rejected():
    environment = valid_environment()
    environment["PAUSEGUARD_RAZORPAY_TEST_ENABLED"] = None

    with pytest.raises(RazorpaySandboxError, match="configuration is invalid"):
        load_sandbox_config(environment)


@pytest.mark.parametrize(
    "field",
    ["RZP_TEST_KEY_ID", "RZP_TEST_KEY_SECRET"],
)
def test_non_string_credentials_are_rejected(field):
    environment = valid_environment()
    environment[field] = None

    with pytest.raises(RazorpaySandboxError, match="credentials are invalid"):
        load_sandbox_config(environment)


def test_enable_flag_is_case_insensitive():
    environment = valid_environment()
    environment["PAUSEGUARD_RAZORPAY_TEST_ENABLED"] = " TRUE "

    config = load_sandbox_config(environment)

    assert config.key_id == "rzp_test_example123"
