"""Own one explicit transaction on a borrowed session; never own its cleanup."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol


logger = logging.getLogger(__name__)


class TransactionSession(Protocol):
    def in_transaction(self) -> bool: ...
    def begin(self) -> object: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class TransactionScopeError(RuntimeError):
    """Sanitized infrastructure failure; a commit error can have unknown outcome."""


def _rollback(session: TransactionSession) -> None:
    try:
        session.rollback()
    except BaseException:
        # Preserve the primary failure/cancellation, without driver details.
        logger.warning("Transaction rollback failed.", exc_info=False)


@contextmanager
def transaction_scope(session: TransactionSession) -> Iterator[None]:
    """Borrow get_db's session; get_db alone closes it.

    Refuse autobegun/nested transactions rather than commit another owner's work.
    No payment operations exist here. Callers must not commit/rollback inside this
    scope. A failed commit is never retried automatically.
    """
    try:
        active = session.in_transaction()
    except Exception:
        raise TransactionScopeError("Transaction state is unavailable.") from None
    if active:
        raise TransactionScopeError("An existing transaction cannot be reused.")
    try:
        session.begin()
    except BaseException as error:
        _rollback(session)
        if isinstance(error, Exception):
            raise TransactionScopeError("Transaction could not begin.") from None
        raise
    try:
        yield
    except BaseException:
        _rollback(session)
        raise
    else:
        try:
            session.commit()
        except BaseException as error:
            _rollback(session)
            if isinstance(error, Exception):
                raise TransactionScopeError("Transaction commit failed; outcome is unknown.") from None
            raise
