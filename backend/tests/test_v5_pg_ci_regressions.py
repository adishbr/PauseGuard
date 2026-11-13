"""Offline regression tests for V5 PostgreSQL CI integration fixes & import hygiene."""

import inspect
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from app.config import Settings
from app.services.account_auth_service import AccountAuthService
from app.services.notification_service import NotificationOutboxService


def test_account_auth_service_imports_without_circular_error():
    backend_dir = str(Path(__file__).resolve().parents[1])
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; sys.path.insert(0, r'"
                + backend_dir
                + "'); from app.services.account_auth_service import AccountAuthService; "
                "assert AccountAuthService is not None"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_signup_flushes_synthetic_user_before_adding_child_records():
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    svc = AccountAuthService(
        settings=Settings(environment="test", mode="mock"),
        db_session=db,
        mock_store=None,
    )

    events: list[str] = []
    db.add.side_effect = lambda obj: events.append(f"add:{type(obj).__name__}")
    db.flush.side_effect = lambda: events.append("flush")

    svc.signup(
        email="fkcheck@example.com",
        password="Password!1234",
        full_name="FK Check User",
        role="payer",
    )

    assert events[0] == "add:SyntheticUser"
    assert events[1] == "flush"
    assert "add:UserAccount" in events[2:]


def test_notification_outbox_checks_users_via_orm_select_not_raw_text_uuid():
    source = inspect.getsource(NotificationOutboxService._enqueue_for_recipient)
    assert "SELECT 1 FROM users" not in source
    assert "select(SyntheticUser.id)" in source

    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    outbox = NotificationOutboxService(
        settings=Settings(environment="test", mode="mock"),
        db_session=db,
        mock_store=None,
    )
    outbox.record_payment_transition(
        payment_id="pay_orm_check",
        event_type="PAYMENT_CREATED",
        status="AWAITING_GUARDIAN",
        payer_id=uuid4(),
        assigned_guardian_id=uuid4(),
        tier=3,
    )
    # Missing users rows are skipped cleanly via ORM select without raising UUID adapter errors
    db.add.assert_not_called()
