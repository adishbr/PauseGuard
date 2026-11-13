"""Guard regressions, including collection and a fresh application import."""

import os
import socket
import subprocess
import sys
from pathlib import Path

import psycopg2
import pytest

from tests.offline import OfflineViolation

# Runs during collection, before any function-scoped fixtures.
assert getattr(socket.socket.connect, "pauseguard_guard", False)


@pytest.mark.parametrize("host", ["127.0.0.1", "192.0.2.1"])
def test_ordinary_connections_are_blocked(host):
    with socket.socket() as connection:
        with pytest.raises(OfflineViolation):
            connection.connect((host, 5432))


def test_database_and_dns_are_blocked():
    with pytest.raises(OfflineViolation):
        psycopg2.connect()
    with pytest.raises(OfflineViolation):
        socket.getaddrinfo("database.invalid", 5432)


@pytest.mark.parametrize("kind", ["builtin", "path", "os"])
def test_dotenv_read_is_blocked_before_file_access(kind):
    # Fictional path; the guard rejects it before consulting the filesystem.
    with pytest.raises(OfflineViolation):
        if kind == "path":
            Path("fictional-fixture/.env").open()
        elif kind == "os":
            os.open("fictional-fixture/.env", os.O_RDONLY)
        else:
            open("fictional-fixture/.env")


def test_fresh_process_import_is_offline():
    backend = Path(__file__).resolve().parents[1]
    script = """
import sys
sys.path.insert(0, sys.argv[1])
import pytest
from tests.offline import install_guards
cleanup = install_guards(pytest.MonkeyPatch())
try:
    assert 'app.config' not in sys.modules
    assert 'app.models.database' not in sys.modules
    from app.main import app
    from app.models.database import Base
    assert app.state.session_factory is None
    assert not Base.metadata.tables
    from app.models.metadata import metadata
    assert set(metadata.tables) == {
        'users', 'role_bindings', 'accounts', 'safe_lock_states',
        'payments', 'payment_appeals', 'guardian_decisions', 'ledger_entries', 'audit_events', 'idempotency_records',
        'razorpay_orders', 'razorpay_payments', 'razorpay_webhook_events',
        'user_accounts', 'identity_assurances', 'otp_challenges', 'user_sessions', 'guardian_invitations',
        'notification_outbox',
    }
    expected_routes = {
        '/api/v2/health', '/api/v2/metrics', '/api/v2/profile', '/api/v2/demo/session',
        '/api/v2/auth/signup', '/api/v2/auth/otp/challenge', '/api/v2/auth/otp/verify',
        '/api/v2/auth/login', '/api/v2/auth/logout',
        '/api/v2/identity/verify', '/api/v2/identity/status',
        '/api/v2/guardian/enroll', '/api/v2/guardian/status', '/api/v2/guardian/dashboard', '/api/v2/guardian/revoke',
        '/api/v2/guardian/invitations', '/api/v2/guardian/invitations/{invitation_id}/accept',
        '/api/v2/guardian/invitations/{invitation_id}/decline', '/api/v2/guardian/invitations/{invitation_id}/revoke',
        '/api/v2/guardian/invitations/{invitation_id}/suspend',
        '/api/v2/guardian/calls/{call_id}/status', '/api/v2/guardian/calls/provider-callback',
        '/api/v2/payments', '/api/v2/payments/{payment_id}',
        '/api/v2/payments/{payment_id}/events',
        '/api/v2/payments/{payment_id}/risk',
        '/api/v2/payments/{payment_id}/evidence',
        '/api/v2/payments/{payment_id}/warning/acknowledge',
        '/api/v2/payments/{payment_id}/step-up/verify',
        '/api/v2/payments/{payment_id}/guardian/decision',
        '/api/v2/payments/{payment_id}/fallback/activate',
        '/api/v2/payments/{payment_id}/fallback/backup',
        '/api/v2/payments/{payment_id}/appeals',
        '/api/v2/payments/{payment_id}/appeals/{appeal_id}/resolve',
        '/api/v2/payments/{payment_id}/retry',
        '/api/v2/payments/{payment_id}/cancel',
        '/api/v2/payments/{payment_id}/confirm',
        '/api/v2/account/balance',
        '/api/v2/safe-lock',
        '/api/v2/safety/purpose-challenge',
        '/api/v2/safety/anti-smurfing/check',
        '/api/v2/audit/verify',
        '/api/v2/audit/anchors',
        '/api/v2/anchors',
        '/api/v2/recovery/guide',
        '/api/v2/risk/advice',
        '/api/v2/policy-lab/simulate',
        '/api/v2/sandbox/razorpay/config',
        '/api/v2/sandbox/razorpay/orders',
        '/api/v2/sandbox/razorpay/verify',
        '/api/v2/sandbox/razorpay/webhook',
        '/api/v2/sandbox/razorpay/orders/{order_id}',
        '/api/v2/ws/ticket',
        '/api/v2/notifications/outbox',
        '/api/v2/bank/intents',
        '/api/v2/bank/webhooks/settlement',
    }
    assert set(app.openapi()['paths']) == expected_routes
    print('guarded cold import passed')
finally:
    cleanup()
"""
    # Forward only OS essentials, never database credentials or other settings.
    # Do not use -I (isolated mode) as it hides site-packages where pytest resides.
    # The subprocess installs offline guards explicitly via install_guards().
    # Pass a minimal but functional environment including USERPROFILE for user site-packages.
    allowed_env = {"SYSTEMROOT", "WINDIR", "USERPROFILE", "HOMEPATH", "HOMEDRIVE", "APPDATA", "LOCALAPPDATA"}
    environment = {key: os.environ[key] for key in allowed_env if key in os.environ}
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(backend)],
        env=environment, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, "Guarded cold import failed."
    assert result.stdout.strip() == "guarded cold import passed"
