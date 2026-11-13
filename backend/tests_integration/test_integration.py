"""Phase 2D PostgreSQL integration tests.

These tests require an authorized disposable PostgreSQL instance.
Run with:
    $env:PAUSEGUARD_POSTGRES_TEST_AUTHORIZED = "true"
    $env:PAUSEGUARD_POSTGRES_TEST_URL = "postgresql+psycopg2://pauseguard_test_runner@127.0.0.1:5432/pauseguard_test_phase2"
    $env:PAUSEGUARD_POSTGRES_TEST_PASSWORD = ...
    python -m pytest -c backend/pytest_integration.ini
"""

import threading
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.models.account import MockAccount
from app.models.database import Base
from app.models.safe_lock import SafeLockState
from app.models.user import RoleBinding, SyntheticUser, UserRole
from app.services.foundation_queries import (
    owned_account_for_update,
    role_bindings_for_update,
    safe_lock_for_update,
)
from app.services.payment_guards import TrustedActorContext
from app.services.transactions import TransactionScopeError, transaction_scope


TEST_ALEMBIC_INI = Path(__file__).parent / "alembic.ini"
TEST_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _fk_ondelete(fk: dict) -> str | None:
    """Extract ondelete action from reflected foreign key dictionary.

    SQLAlchemy's PostgreSQL dialect stores constraint options in fk["options"]["ondelete"].
    Generic/other dialects may store it at the top-level fk.get("ondelete").
    Never use direct key index fk["ondelete"] or fk["options"]["ondelete"] without guard.
    """
    options = fk.get("options") or {}
    return options.get("ondelete") or fk.get("ondelete")


class TestSchemaCreationTeardown:
    """Test real schema creation and teardown via Alembic."""

    def test_tables_created_after_upgrade(self, pg_session: Session):
        """Verify all four tables exist after Alembic upgrade."""
        inspector = inspect(pg_session.bind)
        tables = inspector.get_table_names()
        assert set(tables) >= {"users", "role_bindings", "accounts", "safe_lock_states", "alembic_version"}

    def test_columns_match_orm_definitions(self, pg_session: Session):
        """Verify column definitions match ORM models."""
        inspector = inspect(pg_session.bind)

        # users table
        users_cols = {c["name"]: c for c in inspector.get_columns("users")}
        assert "id" in users_cols
        assert "created_at" in users_cols

        # role_bindings table
        rb_cols = {c["name"]: c for c in inspector.get_columns("role_bindings")}
        assert "user_id" in rb_cols
        assert "role" in rb_cols
        assert "created_at" in rb_cols

        # accounts table
        acc_cols = {c["name"]: c for c in inspector.get_columns("accounts")}
        assert "id" in acc_cols
        assert "owner_id" in acc_cols
        assert "balance_paise" in acc_cols
        assert "version" in acc_cols
        assert "created_at" in acc_cols
        assert "updated_at" in acc_cols

        # safe_lock_states table
        sl_cols = {c["name"]: c for c in inspector.get_columns("safe_lock_states")}
        assert "payer_id" in sl_cols
        assert "is_locked" in sl_cols
        assert "version" in sl_cols
        assert "created_at" in sl_cols
        assert "updated_at" in sl_cols

    def test_indexes_exist(self, pg_session: Session):
        """Verify indexes are created."""
        inspector = inspect(pg_session.bind)
        indexes = inspector.get_indexes("accounts")
        index_names = {idx["name"] for idx in indexes}
        assert "ix_accounts_owner_id" in index_names

    def test_foreign_keys_exist(self, pg_session: Session):
        """Verify foreign key constraints exist with RESTRICT delete behavior."""
        inspector = inspect(pg_session.bind)

        # role_bindings -> users
        rb_fks = inspector.get_foreign_keys("role_bindings")
        assert any(fk["referred_table"] == "users" and _fk_ondelete(fk) == "RESTRICT" for fk in rb_fks)

        # accounts -> users
        acc_fks = inspector.get_foreign_keys("accounts")
        assert any(fk["referred_table"] == "users" and _fk_ondelete(fk) == "RESTRICT" for fk in acc_fks)

        # safe_lock_states -> users
        sl_fks = inspector.get_foreign_keys("safe_lock_states")
        assert any(fk["referred_table"] == "users" and _fk_ondelete(fk) == "RESTRICT" for fk in sl_fks)

    def test_check_constraints_exist(self, pg_session: Session):
        """Verify CHECK constraints exist with correct names and vocabulary."""
        inspector = inspect(pg_session.bind)

        # role_bindings role check
        rb_checks = inspector.get_check_constraints("role_bindings")
        assert rb_checks, "role_bindings should have CHECK constraints"
        rb_names = {ck.get("name") for ck in rb_checks}
        assert "ck_role_bindings_role" in rb_names
        # Verify the constraint SQL contains the role vocabulary
        rb_sql = " ".join(ck.get("sqltext", "") for ck in rb_checks).lower()
        for role in ("payer", "guardian", "analyst", "admin"):
            assert f"'{role}'" in rb_sql, f"role '{role}' not found in CHECK constraint"

        # accounts balance_paise >= 0 and version > 0
        acc_checks = inspector.get_check_constraints("accounts")
        acc_names = {ck.get("name") for ck in acc_checks}
        assert "ck_accounts_nonnegative_balance" in acc_names
        assert "ck_accounts_positive_version" in acc_names
        assert any("balance_paise >= 0" in ck.get("sqltext", "") for ck in acc_checks)
        assert any("version > 0" in ck.get("sqltext", "") for ck in acc_checks)

        # safe_lock_states version > 0
        sl_checks = inspector.get_check_constraints("safe_lock_states")
        sl_names = {ck.get("name") for ck in sl_checks}
        assert "ck_safe_lock_states_positive_version" in sl_names
        assert any("version > 0" in ck.get("sqltext", "") for ck in sl_checks)


class TestCheckConstraints:
    """Test database CHECK constraint enforcement."""

    def test_negative_balance_rejected(self, pg_session: Session):
        """Inserting negative balance_paise should fail CHECK constraint."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        account = MockAccount(id=uuid4(), owner_id=user.id, balance_paise=-100)
        pg_session.add(account)
        with pytest.raises(IntegrityError, match="ck_accounts_nonnegative_balance"):
            pg_session.commit()
        pg_session.rollback()

    def test_zero_balance_accepted(self, pg_session: Session):
        """Zero balance should be accepted."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        account = MockAccount(id=uuid4(), owner_id=user.id, balance_paise=0)
        pg_session.add(account)
        pg_session.commit()
        assert account.balance_paise == 0

    def test_positive_balance_accepted(self, pg_session: Session):
        """Positive balance should be accepted."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        account = MockAccount(id=uuid4(), owner_id=user.id, balance_paise=10000)
        pg_session.add(account)
        pg_session.commit()
        assert account.balance_paise == 10000

    def test_invalid_role_rejected(self, pg_session: Session):
        """Invalid role value within column length should fail CHECK constraint."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        # Use raw SQL with role <= 8 chars ('auditor') to test CHECK constraint specifically,
        # avoiding VARCHAR(8) length truncation error.
        # Raw SQL execute() emits immediately to PostgreSQL, so IntegrityError is raised
        # at execute() time rather than commit() time.
        with pytest.raises(IntegrityError, match="ck_role_bindings_role"):
            pg_session.execute(
                text("INSERT INTO role_bindings (user_id, role, created_at) VALUES (:uid, 'auditor', now())"),
                {"uid": user.id},
            )
        pg_session.rollback()

    def test_valid_roles_accepted(self, pg_session: Session):
        """All four valid roles should be accepted."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        for role in UserRole:
            rb = RoleBinding(user_id=user.id, role=role)
            pg_session.add(rb)
        pg_session.commit()

        count = pg_session.execute(select(RoleBinding).where(RoleBinding.user_id == user.id)).scalars().all()
        assert len(count) == 4

    def test_version_positive_check(self, pg_session: Session):
        """Version must be positive."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        # Test via raw SQL to bypass ORM default; raw SQL execute() emits immediately
        with pytest.raises(IntegrityError, match="ck_accounts_positive_version"):
            pg_session.execute(
                text("INSERT INTO accounts (id, owner_id, balance_paise, version, created_at, updated_at) "
                     "VALUES (:aid, :uid, 100, 0, now(), now())"),
                {"aid": uuid4(), "uid": user.id},
            )
        pg_session.rollback()

    def test_safe_lock_version_positive_check(self, pg_session: Session):
        """Safe-Lock version must be positive."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        # Raw SQL execute() emits immediately to PostgreSQL
        with pytest.raises(IntegrityError, match="ck_safe_lock_states_positive_version"):
            pg_session.execute(
                text("INSERT INTO safe_lock_states (payer_id, is_locked, version, created_at, updated_at) "
                     "VALUES (:uid, false, 0, now(), now())"),
                {"uid": user.id},
            )
        pg_session.rollback()


class TestForeignKeyConstraints:
    """Test foreign key constraint enforcement."""

    def test_role_binding_requires_existing_user(self, pg_session: Session):
        """role_bindings.user_id must reference existing users.id."""
        fake_user_id = uuid4()
        rb = RoleBinding(user_id=fake_user_id, role=UserRole.PAYER)
        pg_session.add(rb)
        with pytest.raises(IntegrityError, match="fk_role_bindings_user"):
            pg_session.commit()
        pg_session.rollback()

    def test_account_requires_existing_owner(self, pg_session: Session):
        """accounts.owner_id must reference existing users.id."""
        fake_user_id = uuid4()
        account = MockAccount(id=uuid4(), owner_id=fake_user_id, balance_paise=1000)
        pg_session.add(account)
        with pytest.raises(IntegrityError, match="fk_accounts_owner"):
            pg_session.commit()
        pg_session.rollback()

    def test_safe_lock_requires_existing_payer(self, pg_session: Session):
        """safe_lock_states.payer_id must reference existing users.id."""
        fake_user_id = uuid4()
        sl = SafeLockState(payer_id=fake_user_id, is_locked=False)
        pg_session.add(sl)
        with pytest.raises(IntegrityError, match="fk_safe_lock_states_payer"):
            pg_session.commit()
        pg_session.rollback()

    def test_delete_user_with_role_binding_restricted(self, pg_session: Session):
        """Deleting user with role_binding should be restricted."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()
        rb = RoleBinding(user_id=user.id, role=UserRole.PAYER)
        pg_session.add(rb)
        pg_session.commit()

        pg_session.delete(user)
        with pytest.raises(IntegrityError, match="fk_role_bindings_user"):
            pg_session.commit()
        pg_session.rollback()

    def test_delete_user_with_account_restricted(self, pg_session: Session):
        """Deleting user with account should be restricted."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()
        account = MockAccount(id=uuid4(), owner_id=user.id, balance_paise=1000)
        pg_session.add(account)
        pg_session.commit()

        pg_session.delete(user)
        with pytest.raises(IntegrityError, match="fk_accounts_owner"):
            pg_session.commit()
        pg_session.rollback()

    def test_delete_user_with_safe_lock_restricted(self, pg_session: Session):
        """Deleting user with safe_lock_state should be restricted."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()
        sl = SafeLockState(payer_id=user.id, is_locked=False)
        pg_session.add(sl)
        pg_session.commit()

        pg_session.delete(user)
        with pytest.raises(IntegrityError, match="fk_safe_lock_states_payer"):
            pg_session.commit()
        pg_session.rollback()


class TestOptimisticConcurrency:
    """Test optimistic locking via version column."""

    def test_concurrent_account_update_conflict(self, pg_session: Session, pg_session_factory: sessionmaker[Session]):
        """Two concurrent updates to same account should raise StaleDataError."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        account = MockAccount(id=uuid4(), owner_id=user.id, balance_paise=10000)
        pg_session.add(account)
        pg_session.commit()

        # Session 1: read account
        account1 = pg_session.get(MockAccount, account.id)
        assert account1.version == 1

        # Session 2: read same account and update
        session2 = pg_session_factory()
        try:
            account2 = session2.get(MockAccount, account.id)
            account2.balance_paise = 20000
            session2.commit()
        finally:
            session2.close()

        # Session 1: try to update with stale version
        account1.balance_paise = 15000
        with pytest.raises(StaleDataError):
            pg_session.commit()
        pg_session.rollback()

    def test_concurrent_safe_lock_update_conflict(self, pg_session: Session, pg_session_factory: sessionmaker[Session]):
        """Two concurrent updates to same safe_lock_state should raise StaleDataError."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        sl = SafeLockState(payer_id=user.id, is_locked=False)
        pg_session.add(sl)
        pg_session.commit()

        # Session 1: read
        sl1 = pg_session.get(SafeLockState, user.id)
        assert sl1.version == 1

        # Session 2: update
        session2 = pg_session_factory()
        try:
            sl2 = session2.get(SafeLockState, user.id)
            sl2.is_locked = True
            session2.commit()
        finally:
            session2.close()

        # Session 1: try to update with stale version
        sl1.is_locked = True
        with pytest.raises(StaleDataError):
            pg_session.commit()
        pg_session.rollback()

    def test_version_increments_on_update(self, pg_session: Session):
        """Version should increment on successful update."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        account = MockAccount(id=uuid4(), owner_id=user.id, balance_paise=10000)
        pg_session.add(account)
        pg_session.commit()
        assert account.version == 1

        account.balance_paise = 20000
        pg_session.commit()
        assert account.version == 2

    def test_version_increments_on_safe_lock_update(self, pg_session: Session):
        """Safe-Lock version should increment on successful update."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        sl = SafeLockState(payer_id=user.id, is_locked=False)
        pg_session.add(sl)
        pg_session.commit()
        assert sl.version == 1

        sl.is_locked = True
        pg_session.commit()
        assert sl.version == 2


class TestSelectForUpdateLocking:
    """Test SELECT FOR UPDATE row locking behavior."""

    def test_role_bindings_for_update_locks_row(self, pg_session: Session):
        """role_bindings_for_update should lock the row."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        rb = RoleBinding(user_id=user.id, role=UserRole.PAYER)
        pg_session.add(rb)
        pg_session.commit()

        actor = TrustedActorContext(user_id=user.id, roles=frozenset({UserRole.PAYER}))
        stmt = role_bindings_for_update(actor)
        results = pg_session.execute(stmt).scalars().all()
        assert len(results) == 1
        assert results[0].user_id == user.id
        assert results[0].role == UserRole.PAYER

    def test_owned_account_for_update_locks_row(self, pg_session: Session):
        """owned_account_for_update should lock the row when owner matches."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        account = MockAccount(id=uuid4(), owner_id=user.id, balance_paise=10000)
        pg_session.add(account)
        pg_session.commit()

        actor = TrustedActorContext(user_id=user.id, roles=frozenset({UserRole.PAYER}))
        stmt = owned_account_for_update(actor, account.id)
        result = pg_session.execute(stmt).scalar_one()
        assert result.id == account.id
        assert result.owner_id == user.id

    def test_owned_account_for_update_rejects_wrong_owner(self, pg_session: Session):
        """owned_account_for_update should return no row for wrong owner."""
        user1 = SyntheticUser(id=uuid4())
        user2 = SyntheticUser(id=uuid4())
        pg_session.add_all([user1, user2])
        pg_session.flush()

        account = MockAccount(id=uuid4(), owner_id=user1.id, balance_paise=10000)
        pg_session.add(account)
        pg_session.commit()

        # Actor is user2, but account belongs to user1
        actor = TrustedActorContext(user_id=user2.id, roles=frozenset({UserRole.PAYER}))
        stmt = owned_account_for_update(actor, account.id)
        result = pg_session.execute(stmt).scalar_one_or_none()
        assert result is None

    def test_safe_lock_for_update_locks_row(self, pg_session: Session):
        """safe_lock_for_update should lock the row."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        sl = SafeLockState(payer_id=user.id, is_locked=False)
        pg_session.add(sl)
        pg_session.commit()

        actor = TrustedActorContext(user_id=user.id, roles=frozenset({UserRole.PAYER}))
        stmt = safe_lock_for_update(actor)
        result = pg_session.execute(stmt).scalar_one()
        assert result.payer_id == user.id
        assert result.is_locked is False

    def test_safe_lock_for_update_missing_row_returns_none(self, pg_session: Session):
        """safe_lock_for_update should return None for missing row (fail closed)."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()
        pg_session.commit()

        # No SafeLockState row exists for this user
        actor = TrustedActorContext(user_id=user.id, roles=frozenset({UserRole.PAYER}))
        stmt = safe_lock_for_update(actor)
        result = pg_session.execute(stmt).scalar_one_or_none()
        assert result is None

    def test_concurrent_for_update_blocks(self, pg_session: Session, pg_session_factory: sessionmaker[Session]):
        """Concurrent FOR UPDATE on same row should block until holding transaction commits."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        account = MockAccount(id=uuid4(), owner_id=user.id, balance_paise=10000)
        pg_session.add(account)
        pg_session.commit()

        lock_acquired = threading.Event()
        release_lock = threading.Event()
        thread2_finished = threading.Event()
        execution_order: list[str] = []

        def holder_thread():
            session1 = pg_session_factory()
            try:
                actor = TrustedActorContext(user_id=user.id, roles=frozenset({UserRole.PAYER}))
                stmt = owned_account_for_update(actor, account.id)
                session1.execute(stmt).scalar_one()
                execution_order.append("holder_locked")
                lock_acquired.set()
                release_lock.wait(timeout=5)
                time.sleep(0.05)
                execution_order.append("holder_committing")
                session1.commit()
            finally:
                session1.close()

        def waiting_thread():
            session2 = pg_session_factory()
            try:
                actor = TrustedActorContext(user_id=user.id, roles=frozenset({UserRole.PAYER}))
                stmt = owned_account_for_update(actor, account.id)
                # This must block in PostgreSQL until holder_thread commits
                session2.execute(stmt).scalar_one()
                execution_order.append("waiter_acquired")
                session2.commit()
                thread2_finished.set()
            finally:
                session2.close()

        t_holder = threading.Thread(target=holder_thread)
        t_holder.start()

        assert lock_acquired.wait(timeout=5), "Holder thread failed to acquire lock"

        t_waiter = threading.Thread(target=waiting_thread)
        t_waiter.start()

        # Verify waiter is blocked waiting on the row lock
        time.sleep(0.1)
        assert not thread2_finished.is_set(), "Waiter did not block on row lock"
        assert execution_order == ["holder_locked"]

        # Signal holder to commit and release lock
        release_lock.set()

        t_holder.join(timeout=5)
        t_waiter.join(timeout=5)

        assert thread2_finished.is_set(), "Waiter failed to finish after lock release"
        assert execution_order == ["holder_locked", "holder_committing", "waiter_acquired"]


class TestTransactionRollbackCleanup:
    """Test transaction rollback and session cleanup behavior."""

    def test_explicit_rollback_clears_changes(self, pg_session: Session):
        """Rollback should discard uncommitted changes."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        account = MockAccount(id=uuid4(), owner_id=user.id, balance_paise=10000)
        pg_session.add(account)
        pg_session.commit()

        # Modify, flush to DB, and rollback
        account.balance_paise = 99999
        pg_session.flush()
        pg_session.rollback()

        # Verify original value preserved in database
        pg_session.expire(account)
        refreshed = pg_session.get(MockAccount, account.id)
        assert refreshed.balance_paise == 10000

    def test_exception_triggers_rollback(self, pg_session: Session):
        """Exception in transaction scope should trigger rollback."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        account = MockAccount(id=uuid4(), owner_id=user.id, balance_paise=10000)
        pg_session.add(account)
        pg_session.commit()

        with pytest.raises(RuntimeError):
            with transaction_scope(pg_session):
                account.balance_paise = 88888
                pg_session.flush()
                raise RuntimeError("intentional failure")

        pg_session.expire(account)
        refreshed = pg_session.get(MockAccount, account.id)
        assert refreshed.balance_paise == 10000

    def test_nested_transaction_rejected(self, pg_session: Session):
        """Nested transaction_scope should be rejected."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()
        pg_session.commit()

        with transaction_scope(pg_session):
            with pytest.raises(TransactionScopeError):
                with transaction_scope(pg_session):
                    pass

    def test_commit_failure_preserves_primary_error(self, pg_session_factory: sessionmaker[Session]):
        """Failed commit should raise TransactionScopeError with sanitized message."""
        # 1. Real PostgreSQL database test: un-flushed row violating constraint causes commit failure
        real_session = pg_session_factory()
        try:
            user = SyntheticUser(id=uuid4())
            real_session.add(user)
            real_session.commit()

            with pytest.raises(TransactionScopeError, match="Transaction commit failed; outcome is unknown"):
                with transaction_scope(real_session):
                    # Negative balance violates check constraint during commit-triggered flush
                    real_session.add(MockAccount(id=uuid4(), owner_id=user.id, balance_paise=-999))
        finally:
            real_session.close()

        # 2. Mock session test: verify commit error wrapping and message sanitization
        from unittest.mock import Mock

        mock_session = Mock(spec=Session)
        mock_session.in_transaction.return_value = False
        mock_session.commit.side_effect = RuntimeError("synthetic-commit-failure")
        mock_session.rollback.return_value = None

        with pytest.raises(TransactionScopeError, match="Transaction commit failed"):
            with transaction_scope(mock_session):
                pass

    def test_session_cleanup_on_success(self, pg_session_factory: sessionmaker[Session]):
        """Session should close cleanly after successful operation."""
        session = pg_session_factory()
        user = SyntheticUser(id=uuid4())
        session.add(user)
        session.flush()

        account = MockAccount(id=uuid4(), owner_id=user.id, balance_paise=10000)
        session.add(account)
        session.commit()
        session.close()

        # Verify data persisted
        session2 = pg_session_factory()
        try:
            saved = session2.get(SyntheticUser, user.id)
            assert saved is not None
        finally:
            session2.close()

    def test_session_cleanup_on_failure(self, pg_session_factory: sessionmaker[Session]):
        """Session should rollback and close on failure."""
        session = pg_session_factory()
        user = SyntheticUser(id=uuid4())
        session.add(user)
        session.flush()
        session.commit()
        session.close()

        session2 = pg_session_factory()
        try:
            account = MockAccount(id=uuid4(), owner_id=user.id, balance_paise=10000)
            session2.add(account)
            session2.flush()
            raise RuntimeError("failure before commit")
        except RuntimeError:
            session2.rollback()
        finally:
            session2.close()

        # Verify nothing persisted from failed session
        session3 = pg_session_factory()
        try:
            from sqlalchemy import func
            count = session3.scalar(select(func.count(MockAccount.id)).where(MockAccount.owner_id == user.id))
            assert count == 0
        finally:
            session3.close()

    def test_autobegun_transaction_rejected(self, pg_session_factory: sessionmaker[Session]):
        """Transaction scope should reject pre-existing transaction."""
        session = pg_session_factory()
        try:
            session.begin()
            with pytest.raises(TransactionScopeError, match="existing transaction cannot be reused"):
                with transaction_scope(session):
                    pass
        finally:
            session.rollback()
            session.close()

    def test_rollback_failure_logged_but_primary_preserved(self, pg_session_factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture):
        """Rollback failure should not mask primary exception."""
        # When rollback fails, transaction_scope must preserve and re-raise the PRIMARY
        # exception rather than masking it with the rollback failure.
        from unittest.mock import Mock

        mock_session = Mock(spec=Session)
        mock_session.in_transaction.return_value = False
        mock_session.commit.return_value = None
        mock_session.rollback.side_effect = RuntimeError("rollback-failed")

        with pytest.raises(ValueError, match="primary error"):
            with transaction_scope(mock_session):
                raise ValueError("primary error")

        assert "Transaction rollback failed." in caplog.text

    def test_timezone_aware_timestamps(self, pg_session: Session):
        """Timestamps should be timezone-aware (UTC)."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()
        pg_session.commit()

        assert user.created_at is not None
        assert user.created_at.tzinfo is not None

    def test_updated_at_changes_on_update(self, pg_session: Session):
        """updated_at should change on row update."""
        user = SyntheticUser(id=uuid4())
        pg_session.add(user)
        pg_session.flush()

        account = MockAccount(id=uuid4(), owner_id=user.id, balance_paise=10000)
        pg_session.add(account)
        pg_session.commit()

        original_updated = account.updated_at
        time.sleep(0.05)  # Ensure clock advances past Windows timer resolution
        account.balance_paise = 20000
        pg_session.commit()

        assert account.updated_at > original_updated


class TestAlembicDowngrade:
    """Test Alembic downgrade removes schema correctly."""

    def test_downgrade_removes_all_tables(self, pg_engine: Engine):
        """Downgrade should drop all application tables."""
        from alembic import command
        from alembic.config import Config

        config = Config(str(TEST_ALEMBIC_INI))
        config.set_main_option("script_location", str(TEST_MIGRATIONS_DIR))
        config.set_main_option("sqlalchemy.url", pg_engine.url.render_as_string(hide_password=True))

        try:
            with pg_engine.connect() as conn:
                config.attributes["connection"] = conn
                command.downgrade(config, "base")
                conn.commit()

            # Verify tables dropped
            inspector = inspect(pg_engine)
            tables = inspector.get_table_names()
            assert "users" not in tables
            assert "role_bindings" not in tables
            assert "accounts" not in tables
            assert "safe_lock_states" not in tables
        finally:
            # Restore tables so following tests or fixtures have a consistent state
            with pg_engine.connect() as conn:
                config.attributes["connection"] = conn
                command.upgrade(config, "head")
                conn.commit()

    def test_upgrade_after_downgrade_works(self, pg_engine: Engine):
        """Upgrade should work after downgrade."""
        from alembic import command
        from alembic.config import Config

        config = Config(str(TEST_ALEMBIC_INI))
        config.set_main_option("script_location", str(TEST_MIGRATIONS_DIR))
        config.set_main_option("sqlalchemy.url", pg_engine.url.render_as_string(hide_password=True))

        with pg_engine.connect() as conn:
            config.attributes["connection"] = conn
            command.downgrade(config, "base")
            conn.commit()

        with pg_engine.connect() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
            conn.commit()

        # Verify tables exist
        inspector = inspect(pg_engine)
        tables = inspector.get_table_names()
        assert "users" in tables
        assert "role_bindings" in tables
        assert "accounts" in tables
        assert "safe_lock_states" in tables

