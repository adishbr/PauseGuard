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
REVISION = BACKEND / "migrations/versions/0001_offline_foundation.py"


def operations(name):
    tree = ast.parse(REVISION.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    calls = []
    for statement in function.body:
        assert isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
        call = statement.value
        assert isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
        assert call.func.value.id == "op"
        calls.append(call)
    return calls


def declaration(expression):
    # Only evaluate SQLAlchemy declaration expressions, never an op.* call or
    # the revision functions. Unknown names have no builtins to fall back to.
    for node in ast.walk(expression):
        if isinstance(node, ast.Name):
            assert node.id == "sa"
        if isinstance(node, ast.Attribute):
            assert not node.attr.startswith("_")
    return eval(compile(ast.Expression(expression), str(REVISION), "eval"), {"__builtins__": {}, "sa": sa})


@pytest.fixture
def declared_schema():
    schema = sa.MetaData()
    for call in operations("upgrade"):
        args = [declaration(arg) for arg in call.args]
        kwargs = {kw.arg: declaration(kw.value) for kw in call.keywords}
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
    assert scripts.get_heads() == ["0001_offline_foundation"]
    revision = scripts.get_revision("head")
    assert revision.down_revision is None
    assert revision.dependencies is None
    assert revision.branch_labels == set()
    assert len(list(scripts.walk_revisions())) == 1


def test_upgrade_and_downgrade_have_only_approved_ordered_operations():
    upgrade = operations("upgrade")
    assert [(call.func.attr, ast.literal_eval(call.args[0])) for call in upgrade] == [
        ("create_table", "users"), ("create_table", "role_bindings"),
        ("create_table", "accounts"), ("create_index", "ix_accounts_owner_id"),
        ("create_table", "safe_lock_states"),
    ]
    downgrade = operations("downgrade")
    assert [(call.func.attr, ast.literal_eval(call.args[0])) for call in downgrade] == [
        ("drop_table", "safe_lock_states"), ("drop_index", "ix_accounts_owner_id"),
        ("drop_table", "accounts"), ("drop_table", "role_bindings"), ("drop_table", "users"),
    ]
    assert {kw.arg: ast.literal_eval(kw.value) for kw in downgrade[1].keywords} == {"table_name": "accounts"}


def canonical_ddl(table):
    # Constraint ordering is insignificant. Exact emitted clauses must match,
    # including names, defaults, nullability, FK actions and role vocabulary.
    sql = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    return sorted(line.strip().rstrip(",") for line in sql.splitlines() if line.strip())


@pytest.mark.parametrize("table_name", ["users", "role_bindings", "accounts", "safe_lock_states"])
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
    assert declared_schema.sorted_tables[0].name == "users"
    for table in declared_schema.tables.values():
        for foreign_key in table.foreign_keys:
            assert foreign_key.column is declared_schema.tables["users"].c.id
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
