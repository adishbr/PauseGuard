import asyncio
import traceback
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from app.services.transactions import TransactionScopeError, transaction_scope


def session_stub(**failures):
    session = Mock(spec=Session)
    session.in_transaction.return_value = False
    for name, error in failures.items():
        getattr(session, name).side_effect = error
    return session


def test_one_explicit_transaction_borrows_session_without_closing():
    session = session_stub()
    with transaction_scope(session):
        session.commit.assert_not_called()
    assert [call[0] for call in session.method_calls] == ["in_transaction", "begin", "commit"]
    session.close.assert_not_called()


def test_real_unused_session_transaction_lifecycle_without_connection():
    # No bind and no statements: SQLAlchemy's logical transaction only.
    with Session() as session:
        with transaction_scope(session):
            assert session.in_transaction()
        assert not session.in_transaction()
        with pytest.raises(ValueError):
            with transaction_scope(session):
                raise ValueError("fixture failure")
        assert not session.in_transaction()


def test_preexisting_autobegun_or_nested_scope_is_never_owned():
    session = session_stub()
    session.in_transaction.return_value = True
    with pytest.raises(TransactionScopeError):
        with transaction_scope(session):
            pytest.fail("Existing transaction was reused.")
    session.begin.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.close.assert_not_called()


@pytest.mark.parametrize("primary_type", [ValueError, GeneratorExit, asyncio.CancelledError, KeyboardInterrupt])
@pytest.mark.parametrize("cleanup_type", [None, RuntimeError, asyncio.CancelledError])
def test_primary_failure_survives_rollback_failure(primary_type, cleanup_type, caplog):
    primary = primary_type("fixture primary")
    session = session_stub(**({"rollback": cleanup_type("synthetic-private")} if cleanup_type else {}))
    with pytest.raises(primary_type) as captured:
        with transaction_scope(session):
            raise primary
    assert captured.value is primary
    assert "synthetic-private" not in "".join(traceback.format_exception(captured.value)) + caplog.text
    assert all(not record.exc_info for record in caplog.records)
    session.rollback.assert_called_once_with()
    session.commit.assert_not_called()
    session.close.assert_not_called()


@pytest.mark.parametrize("operation", ["in_transaction", "begin", "commit"])
@pytest.mark.parametrize("rollback_fails", [False, True])
def test_storage_failures_are_sanitized_and_never_retried(operation, rollback_fails, caplog):
    failures = {operation: RuntimeError("synthetic-private-driver")}
    if rollback_fails:
        failures["rollback"] = RuntimeError("synthetic-private-cleanup")
    session = session_stub(**failures)
    with pytest.raises(TransactionScopeError) as captured:
        with transaction_scope(session):
            pass
    assert "synthetic-private" not in "".join(traceback.format_exception(captured.value)) + caplog.text
    if operation != "in_transaction":
        session.rollback.assert_called_once_with()
    else:
        session.rollback.assert_not_called()
    assert session.commit.call_count == (1 if operation == "commit" else 0)
    session.close.assert_not_called()


@pytest.mark.parametrize("operation", ["begin", "commit"])
def test_storage_cancellation_preserves_identity(operation):
    cancellation = asyncio.CancelledError()
    session = session_stub(**{operation: cancellation})
    with pytest.raises(asyncio.CancelledError) as captured:
        with transaction_scope(session):
            pass
    assert captured.value is cancellation
    session.rollback.assert_called_once_with()
