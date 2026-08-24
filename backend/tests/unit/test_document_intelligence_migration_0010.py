"""Up/down test for alembic/versions/0010_di_promote_to_metadata.py.

Mirrors ``test_document_intelligence_migration.py``'s in-memory-SQLite
approach. ``document_intelligence_model_fields`` doesn't exist until 0008's
migration has run, so this loads and applies 0008 first to get a table to
add the new column onto.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_TABLE = "document_intelligence_model_fields"
_COLUMN = "promote_to_document_metadata"


def _load_migration(name: str, module_id: str) -> ModuleType:
    path = _VERSIONS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(module_id, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_upgrade_adds_column_then_downgrade_drops_it() -> None:
    base = _load_migration("0008_document_intelligence", "test_migration_0008_base")
    migration = _load_migration("0010_di_promote_to_metadata", "test_migration_0010")

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        base.op = Operations(context)
        migration.op = Operations(context)

        base.upgrade()
        migration.upgrade()
        columns = {col["name"] for col in sa.inspect(connection).get_columns(_TABLE)}
        assert _COLUMN in columns

        migration.downgrade()
        columns = {col["name"] for col in sa.inspect(connection).get_columns(_TABLE)}
        assert _COLUMN not in columns
