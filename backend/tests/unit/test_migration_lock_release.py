"""The migration lock release only targets stale idle holders."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def _load_connect_args():
    path = _ROOT / "backend" / "alembic" / "connect_args.py"
    spec = importlib.util.spec_from_file_location("alembic_migration_connect_args", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_connect_args_stay_empty_without_workflow_env() -> None:
    module = _load_connect_args()
    assert module.migration_connect_args({}) == {}


def test_migration_connect_args_set_lock_timeout_and_keepalives() -> None:
    module = _load_connect_args()
    args = module.migration_connect_args(
        {
            "ALEMBIC_LOCK_TIMEOUT": "30s",
            "ALEMBIC_TCP_KEEPALIVES_IDLE": "30",
            "ALEMBIC_TCP_KEEPALIVES_INTERVAL": "10",
            "ALEMBIC_TCP_KEEPALIVES_COUNT": "5",
        }
    )
    assert args == {
        "server_settings": {
            "lock_timeout": "30s",
            "tcp_keepalives_idle": "30",
            "tcp_keepalives_interval": "10",
            "tcp_keepalives_count": "5",
        }
    }


def test_lock_release_does_not_touch_security_or_active_queries() -> None:
    script = (_ROOT / "infra" / "dev" / "release-migration-locks.py").read_text()
    workflow = (_ROOT / ".github" / "workflows" / "run-database-migrations.yml").read_text()
    assert "idle in transaction" in script
    assert "interval '60 seconds'" in script
    assert "a.usename = current_user" in script
    assert "document_versions" in script
    assert "pg_terminate_backend" in script
    assert "BYPASSRLS" not in script
    assert "DISABLE ROW LEVEL SECURITY" not in script
    assert "NO FORCE ROW LEVEL SECURITY" not in script
    assert "release-migration-locks.py" in workflow
    assert "ALEMBIC_LOCK_TIMEOUT: 30s" in workflow
    assert "ALEMBIC_TCP_KEEPALIVES_IDLE" in workflow
