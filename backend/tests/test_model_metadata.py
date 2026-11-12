"""Offline declarations/SQL compilation, not PostgreSQL enforcement tests."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Uuid, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateIndex, CreateTable, UniqueConstraint

from app.models.database import Base
from app.models.metadata import (
    AuditEvent,
    GuardianDecision,
    IdempotencyRecord,
    LedgerEntry,
    MockAccount,
    Payment,
    RazorpayOrder,
    RazorpayPayment,
    RazorpayWebhookEvent,
    RoleBinding,
    SafeLockState,
    SyntheticUser,
    UserRole,
    metadata,
)

ALL_TABLES = [
    "users",
    "role_bindings",
    "accounts",
    "safe_lock_states",
    "payments",
    "guardian_decisions",
    "ledger_entries",
    "audit_events",
    "idempotency_records",
    "razorpay_orders",
    "razorpay_payments",
    "razorpay_webhook_events",
]

ALL_MODELS = (
    SyntheticUser,
    RoleBinding,
    MockAccount,
    SafeLockState,
    Payment,
    GuardianDecision,
    LedgerEntry,
    AuditEvent,
    IdempotencyRecord,
    RazorpayOrder,
    RazorpayPayment,
    RazorpayWebhookEvent,
)


def test_only_approved_tables_reuse_foundation_base():
    assert metadata is Base.metadata
    assert set(metadata.tables) == set(ALL_TABLES)
    assert all(issubclass(model, Base) for model in ALL_MODELS)
    configure_mappers()


@pytest.mark.parametrize("table_name", ALL_TABLES)
def test_postgresql_ddl_compiles_without_connections(table_name):
    table = metadata.tables[table_name]
    sql = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert f"CREATE TABLE {table_name}" in sql
    if any(isinstance(c.type, DateTime) for c in table.c):
        assert "TIMESTAMP WITH TIME ZONE" in sql
    if any(isinstance(c.type, Uuid) for c in table.c):
        assert "UUID NOT NULL" in sql
    for index in table.indexes:
        assert "INDEX" in str(CreateIndex(index).compile(dialect=postgresql.dialect()))


def test_role_binding_vocabulary_and_duplicate_grant_constraint():
    table = RoleBinding.__table__
    assert tuple(table.primary_key.columns.keys()) == ("user_id", "role")
    assert table.primary_key.name == "pk_role_bindings"
    assert set(table.c.role.type.enums) == {"payer", "guardian", "analyst", "admin"}
    sql = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "CHECK (role IN ('payer', 'guardian', 'analyst', 'admin'))" in sql
    processor = table.c.role.type.bind_processor(postgresql.dialect())
    assert processor(UserRole.ANALYST) == "analyst"
    with pytest.raises(LookupError):
        processor("client-claimed-superuser")


@pytest.mark.parametrize("table_name,column", [
    ("role_bindings", "user_id"), ("accounts", "owner_id"), ("safe_lock_states", "payer_id"),
    ("payments", "payer_id"), ("guardian_decisions", "guardian_id"),
])
def test_ownership_foreign_keys_are_required_uuid_and_restrict_delete(table_name, column):
    field = metadata.tables[table_name].c[column]
    assert field.nullable is False
    assert isinstance(field.type, Uuid) and field.type.as_uuid
    fk, = field.foreign_keys
    assert fk.target_fullname == "users.id"
    assert fk.ondelete == "RESTRICT"


def test_account_money_constraints_and_no_funding_default():
    table = MockAccount.__table__
    assert isinstance(table.c.balance_paise.type, BigInteger)
    assert table.c.balance_paise.nullable is False
    assert table.c.balance_paise.default is None
    assert table.c.balance_paise.server_default is None
    checks = {str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)}
    assert checks == {"balance_paise >= 0", "version > 0"}
    assert not any(isinstance(c, UniqueConstraint) for c in table.constraints)
    index, = table.indexes
    assert tuple(index.columns.keys()) == ("owner_id",)
    assert index.unique is False
    sql = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "balance_paise BIGINT NOT NULL" in sql
    assert "CHECK (balance_paise >= 0)" in sql


def test_safe_lock_has_no_implicit_unlock_or_additional_modes():
    table = SafeLockState.__table__
    assert tuple(table.primary_key.columns.keys()) == ("payer_id",)
    assert isinstance(table.c.is_locked.type, Boolean)
    assert table.c.is_locked.nullable is False
    assert table.c.is_locked.default is None and table.c.is_locked.server_default is None
    assert set(table.c.keys()) == {"payer_id", "is_locked", "version", "created_at", "updated_at"}


@pytest.mark.parametrize("model", [MockAccount, SafeLockState, Payment])
def test_positive_version_and_orm_optimistic_lock_declaration(model):
    table = model.__table__
    assert table.c.version.nullable is False
    assert inspect(model).version_id_col is table.c.version
    assert any(str(c.sqltext) == "version > 0" for c in table.constraints if isinstance(c, CheckConstraint))


def test_timestamps_are_timezone_aware_and_required():
    for table in metadata.tables.values():
        for field in table.c:
            if isinstance(field.type, DateTime):
                assert field.type.timezone is True
                if field.name in ("guardian_deadline", "verified_at"):
                    assert field.nullable is True
                else:
                    assert field.nullable is False
                    assert field.server_default is not None
    assert MockAccount.__table__.c.updated_at.onupdate is not None
    assert SafeLockState.__table__.c.updated_at.onupdate is not None
    assert Payment.__table__.c.updated_at.onupdate is not None


def test_in_memory_relationships_have_no_delete_cascade_or_account_limit():
    user = SyntheticUser(id=uuid4())
    grant = RoleBinding(user=user, role=UserRole.PAYER)
    first = MockAccount(id=uuid4(), owner=user, balance_paise=0)
    second = MockAccount(id=uuid4(), owner=user, balance_paise=100)
    lock = SafeLockState(payer=user, is_locked=True)
    assert user.role_bindings == [grant]
    assert user.accounts == [first, second]
    assert user.safe_lock_state is lock
    assert isinstance(user.id, UUID)
    assert first.owner is second.owner is lock.payer is grant.user is user
    for name in ("role_bindings", "accounts", "safe_lock_state"):
        relationship = inspect(SyntheticUser).relationships[name]
        assert "delete" not in relationship.cascade
        assert "delete-orphan" not in relationship.cascade
        assert relationship.passive_deletes == "all"
