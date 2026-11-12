"""Inspect declarations and compile SQL; never invoke migration entry points."""

import ast
from pathlib import Path
import runpy
from unittest.mock import Mock

from alembic import context
from alembic.config import Config
from alembic.script import ScriptDirectory
from mako.template import Template
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable, DropIndex, DropTable

from app.models.metadata import metadata

BACKEND = Path(__file__).resolve().parents[1]
REVISION_0001 = BACKEND / "migrations/versions/0001_offline_foundation.py"
REVISION_0002 = BACKEND / "migrations/versions/0002_durable_payment_ledger.py"
REVISION_0003 = BACKEND / "migrations/versions/0003_razorpay_merchant_sandbox.py"

ALL_MIGRATION_TABLES = [
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


def operations(name, revision_path=REVISION_0001):
    tree = ast.parse(revision_path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    calls = []
    for statement in function.body:
        assert isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
        call = statement.value
        assert isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
        assert call.func.value.id == "op"
        calls.append(call)
    return calls


def declaration(expression, revision_path=REVISION_0001):
    # Only evaluate SQLAlchemy declaration expressions, never an op.* call or
    # the revision functions. Unknown names have no builtins to fall back to.
    for node in ast.walk(expression):
        if isinstance(node, ast.Name):
            assert node.id == "sa"
        if isinstance(node, ast.Attribute):
            assert not node.attr.startswith("_")
    return eval(compile(ast.Expression(expression), str(revision_path), "eval"), {"__builtins__": {}, "sa": sa})


@pytest.fixture
def declared_schema():
    schema = sa.MetaData()
    for rev in (REVISION_0001, REVISION_0002, REVISION_0003):
        for call in operations("upgrade", rev):
            args = [declaration(arg, rev) for arg in call.args]
            kwargs = {kw.arg: declaration(kw.value, rev) for kw in call.keywords}
            if call.func.attr == "create_table":
                sa.Table(args[0], schema, *args[1:], **kwargs)
            else:
                assert call.func.attr == "create_index"
                name, table, columns = args
                sa.Index(name, *(schema.tables[table].c[column] for column in columns), **kwargs)
    return schema


def test_single_initial_revision_and_no_configured_target():
    config = Config(str(BACKEND / "alembic.ini"))
    assert config.get_main_option("sqlalchemy.url") is None
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["0003_razorpay_merchant_sandbox"]
    head = scripts.get_revision("head")
    assert head.revision == "0003_razorpay_merchant_sandbox"
    assert head.down_revision == "0002_durable_payment_ledger"
    rev2 = scripts.get_revision("0002_durable_payment_ledger")
    assert rev2.down_revision == "0001_offline_foundation"
    base = scripts.get_revision("0001_offline_foundation")
    assert base.down_revision is None
    assert base.dependencies is None
    assert base.branch_labels == set()
    assert len(list(scripts.walk_revisions())) == 3


def test_upgrade_and_downgrade_have_only_approved_ordered_operations():
    upgrade_1 = operations("upgrade", REVISION_0001)
    assert [(call.func.attr, ast.literal_eval(call.args[0])) for call in upgrade_1] == [
        ("create_table", "users"), ("create_table", "role_bindings"),
        ("create_table", "accounts"), ("create_index", "ix_accounts_owner_id"),
        ("create_table", "safe_lock_states"),
    ]
    downgrade_1 = operations("downgrade", REVISION_0001)
    assert [(call.func.attr, ast.literal_eval(call.args[0])) for call in downgrade_1] == [
        ("drop_table", "safe_lock_states"), ("drop_index", "ix_accounts_owner_id"),
        ("drop_table", "accounts"), ("drop_table", "role_bindings"), ("drop_table", "users"),
    ]

    upgrade_2 = operations("upgrade", REVISION_0002)
    assert [(call.func.attr, ast.literal_eval(call.args[0])) for call in upgrade_2] == [
        ("create_table", "payments"), ("create_index", "ix_payments_payer_id"),
        ("create_index", "ix_payments_status"), ("create_index", "ix_payments_idempotency_key"),
        ("create_table", "guardian_decisions"), ("create_index", "ix_guardian_decisions_guardian_id"),
        ("create_table", "ledger_entries"), ("create_index", "ix_ledger_entries_payment_id"),
        ("create_index", "ix_ledger_entries_account_id"),
        ("create_table", "audit_events"), ("create_index", "ix_audit_events_payment_id"),
        ("create_index", "ix_audit_events_actor_id"), ("create_index", "ix_audit_events_event_type"),
        ("create_table", "idempotency_records"), ("create_index", "ix_idempotency_records_caller_endpoint"),
    ]
    downgrade_2 = operations("downgrade", REVISION_0002)
    assert [(call.func.attr, ast.literal_eval(call.args[0])) for call in downgrade_2] == [
        ("drop_index", "ix_idempotency_records_caller_endpoint"), ("drop_table", "idempotency_records"),
        ("drop_index", "ix_audit_events_event_type"), ("drop_index", "ix_audit_events_actor_id"),
        ("drop_index", "ix_audit_events_payment_id"), ("drop_table", "audit_events"),
        ("drop_index", "ix_ledger_entries_account_id"), ("drop_index", "ix_ledger_entries_payment_id"),
        ("drop_table", "ledger_entries"),
        ("drop_index", "ix_guardian_decisions_guardian_id"), ("drop_table", "guardian_decisions"),
        ("drop_index", "ix_payments_idempotency_key"), ("drop_index", "ix_payments_status"),
        ("drop_index", "ix_payments_payer_id"), ("drop_table", "payments"),
    ]

    upgrade_3 = operations("upgrade", REVISION_0003)
    assert [(call.func.attr, ast.literal_eval(call.args[0])) for call in upgrade_3] == [
        ("create_table", "razorpay_orders"),
        ("create_index", "ix_razorpay_orders_razorpay_order_id"),
        ("create_index", "ix_razorpay_orders_admin_id"),
        ("create_index", "ix_razorpay_orders_status"),
        ("create_index", "ix_razorpay_orders_receipt"),
        ("create_table", "razorpay_payments"),
        ("create_index", "ix_razorpay_payments_order_id"),
        ("create_index", "ix_razorpay_payments_razorpay_order_id"),
        ("create_index", "ix_razorpay_payments_status"),
        ("create_table", "razorpay_webhook_events"),
        ("create_index", "ix_razorpay_webhook_events_event_type"),
        ("create_index", "ix_razorpay_webhook_events_entity_id"),
    ]
    downgrade_3 = operations("downgrade", REVISION_0003)
    assert [(call.func.attr, ast.literal_eval(call.args[0])) for call in downgrade_3] == [
        ("drop_index", "ix_razorpay_webhook_events_entity_id"),
        ("drop_index", "ix_razorpay_webhook_events_event_type"),
        ("drop_table", "razorpay_webhook_events"),
        ("drop_index", "ix_razorpay_payments_status"),
        ("drop_index", "ix_razorpay_payments_razorpay_order_id"),
        ("drop_index", "ix_razorpay_payments_order_id"),
        ("drop_table", "razorpay_payments"),
        ("drop_index", "ix_razorpay_orders_receipt"),
        ("drop_index", "ix_razorpay_orders_status"),
        ("drop_index", "ix_razorpay_orders_admin_id"),
        ("drop_index", "ix_razorpay_orders_razorpay_order_id"),
        ("drop_table", "razorpay_orders"),
    ]


def canonical_ddl(table):
    # Constraint ordering is insignificant. Exact emitted clauses must match,
    # including names, defaults, nullability, FK actions and role vocabulary.
    sql = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    return sorted(line.strip().rstrip(",") for line in sql.splitlines() if line.strip())


@pytest.mark.parametrize("table_name", ALL_MIGRATION_TABLES)
def test_frozen_revision_postgresql_ddl_matches_orm(declared_schema, table_name):
    assert set(declared_schema.tables) == set(metadata.tables)
    table = declared_schema.tables[table_name]
    assert canonical_ddl(table) == canonical_ddl(metadata.tables[table_name])
    dialect = postgresql.dialect()
    actual = sorted(str(CreateIndex(index).compile(dialect=dialect)) for index in table.indexes)
    expected = sorted(str(CreateIndex(index).compile(dialect=dialect)) for index in metadata.tables[table_name].indexes)
    assert actual == expected
    assert str(DropTable(table).compile(dialect=dialect)).strip() == f"DROP TABLE {table_name}"
    for index in table.indexes:
        assert str(DropIndex(index).compile(dialect=dialect)).strip() == f"DROP INDEX {index.name}"


def test_foreign_keys_resolve_without_cycles(declared_schema):
    first_tables = [table.name for table in declared_schema.sorted_tables[:3]]
    assert "users" in first_tables
    for table in declared_schema.tables.values():
        for foreign_key in table.foreign_keys:
            assert foreign_key.ondelete == "RESTRICT"


def test_online_environment_rejects_even_injected_connection(monkeypatch):
    config = Config(str(BACKEND / "alembic.ini"))
    config.attributes["connection"] = Mock()
    config.set_main_option("sqlalchemy.url", sa.engine.URL.create(
        "postgresql+psycopg2", host="database.invalid", database="mock_fixture"
    ).render_as_string())
    monkeypatch.setattr(context, "config", config, raising=False)
    monkeypatch.setattr(context, "is_offline_mode", lambda: False)
    configure = Mock()
    monkeypatch.setattr(context, "configure", configure)
    with pytest.raises(RuntimeError, match="Online migrations are disabled"):
        runpy.run_path(str(BACKEND / "migrations/env.py"))
    configure.assert_not_called()


def test_offline_environment_configures_only_dialect_and_existing_metadata(monkeypatch):
    class StopBeforeMigration(Exception):
        pass

    configure = Mock()
    run = Mock()
    monkeypatch.setattr(context, "is_offline_mode", lambda: True)
    monkeypatch.setattr(context, "configure", configure)
    monkeypatch.setattr(context, "run_migrations", run)
    monkeypatch.setattr(context, "begin_transaction", Mock(side_effect=StopBeforeMigration))
    with pytest.raises(StopBeforeMigration):
        runpy.run_path(str(BACKEND / "migrations/env.py"))
    assert configure.call_args.kwargs == {
        "dialect_name": "postgresql", "target_metadata": metadata, "literal_binds": True,
        "dialect_opts": {"paramstyle": "named"}, "transactional_ddl": True,
    }
    run.assert_not_called()


def test_revision_template_renders_valid_python_without_execution():
    template = Template(filename=str(BACKEND / "migrations/script.py.mako"))
    source = template.render(
        message="Future reviewed revision", up_revision="example", down_revision="0001_offline_foundation",
        branch_labels=None, depends_on=None, imports="", upgrades="", downgrades="",
        comma=lambda value: value or "",
    )
    compile(source, "rendered-template", "exec")
