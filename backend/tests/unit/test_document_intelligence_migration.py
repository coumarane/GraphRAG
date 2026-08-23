"""Up/down test for alembic/versions/0008_document_intelligence.py.

No alembic migration test infrastructure exists yet in this repo (migrations
are otherwise unverified pre-deploy). This binds the migration module's
``op`` to a real ``Operations`` instance over an in-memory SQLite connection
so ``upgrade()``/``downgrade()`` run for real, without needing Postgres.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0008_document_intelligence.py"
)

_NEW_TABLES = (
    "plugins",
    "plugin_configuration",
    "document_intelligence_models",
    "document_intelligence_model_fields",
    "document_extraction_runs",
    "document_extracted_fields",
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "test_migration_0008_document_intelligence", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_upgrade_creates_all_tables_then_downgrade_drops_them() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        migration.op = Operations(context)

        migration.upgrade()
        tables = set(sa.inspect(connection).get_table_names())
        for name in _NEW_TABLES:
            assert name in tables

        migration.downgrade()
        tables = set(sa.inspect(connection).get_table_names())
        for name in _NEW_TABLES:
            assert name not in tables
