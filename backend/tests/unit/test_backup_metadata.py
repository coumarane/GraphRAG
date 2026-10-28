"""The DEV backup evidence describes a verified private dump and nothing else."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_MODULE_PATH = _ROOT / "infra" / "dev" / "backup_metadata.py"
_SPEC = importlib.util.spec_from_file_location("backup_metadata", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
backup_metadata = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(backup_metadata)


def _metadata(completed_at: datetime) -> dict:
    return backup_metadata.build_metadata(
        host="database.safranys.com",
        port=5432,
        database="chatwithdocs_db",
        admin_role="postgres",
        admin_privilege="superuser",
        postgres_version="18.6",
        alembic_revision="0012_document_search",
        sha256="a" * 64,
        content_md5="d41d8cd98f00b204e9800998ecf8427e",
        size_bytes=10,
        account="graphragdocsdevbmo9",
        container="artifacts",
        blob="postgres-backups/dev/20261028T000000Z-1.dump",
        retention_days=30,
        completed_at=completed_at,
    )


def test_counts_must_match_after_restore() -> None:
    backup_metadata.counts_match("public.documents\t2\n", "public.documents\t2\n")
    with pytest.raises(backup_metadata.BackupMetadataError, match="documents"):
        backup_metadata.counts_match("public.documents\t2\n", "public.documents\t1\n")


def test_cleanup_keeps_the_new_blob_and_rejects_other_prefixes() -> None:
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    blobs = [
        {"name": "postgres-backups/dev/old.dump", "modified": "2026-09-01T00:00:00Z"},
        {"name": "postgres-backups/dev/new.dump", "modified": "2026-09-01T00:00:00Z"},
    ]
    assert backup_metadata.expired_blob_names(
        blobs, now=now, retention_days=30, keep="postgres-backups/dev/new.dump"
    ) == ["postgres-backups/dev/old.dump"]
    with pytest.raises(backup_metadata.BackupMetadataError, match="outside"):
        backup_metadata.expired_blob_names(
            [{"name": "documents/secret.bin", "modified": "2026-01-01T00:00:00Z"}],
            now=now,
            retention_days=30,
            keep="postgres-backups/dev/new.dump",
        )


def test_metadata_rejects_stale_or_application_role_backups() -> None:
    now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
    fresh = _metadata(now - timedelta(hours=1))
    backup_metadata.validate_metadata(
        fresh,
        host="database.safranys.com",
        database="chatwithdocs_db",
        account="graphragdocsdevbmo9",
        container="artifacts",
        now=now,
        max_age=timedelta(hours=24),
    )
    stale = _metadata(now - timedelta(hours=25))
    with pytest.raises(backup_metadata.BackupMetadataError, match="freshness"):
        backup_metadata.validate_metadata(
            stale,
            host="database.safranys.com",
            database="chatwithdocs_db",
            account="graphragdocsdevbmo9",
            container="artifacts",
            now=now,
            max_age=timedelta(hours=24),
        )
    with pytest.raises(backup_metadata.BackupMetadataError, match="application role"):
        backup_metadata.build_metadata(
            host="database.safranys.com",
            port=5432,
            database="chatwithdocs_db",
            admin_role="chatwithdocs_dev_user",
            admin_privilege="bypassrls",
            postgres_version="18.6",
            alembic_revision="0012_document_search",
            sha256="a" * 64,
            content_md5="abc",
            size_bytes=1,
            account="graphragdocsdevbmo9",
            container="artifacts",
            blob="postgres-backups/dev/x.dump",
            retention_days=30,
            completed_at=now,
        )


def test_backup_workflow_does_not_weaken_row_level_security() -> None:
    script = (_ROOT / "infra" / "dev" / "backup-dev-database.sh").read_text()
    workflow = (_ROOT / ".github" / "workflows" / "backup-dev-database.yml").read_text()
    migration = (_ROOT / ".github" / "workflows" / "run-database-migrations.yml").read_text()
    combined = script + workflow
    assert "--format=custom" in script
    assert "--no-owner" in script
    assert "--no-acl" in script
    assert "row_security=off" in script
    assert "--enable-row-security" not in combined
    assert "BYPASSRLS" not in combined
    assert "DISABLE ROW LEVEL SECURITY" not in combined
    assert "NO FORCE ROW LEVEL SECURITY" not in combined
    assert "chatwithdocs_dev_user" in script
    assert "require-backup-evidence.sh" in migration
    assert "backup_confirmed does not replace" in (
        _ROOT / "infra" / "dev" / "require-backup-evidence.sh"
    ).read_text()
    gate = json.loads((_ROOT / "infra" / "dev" / "release-gate.json").read_text())
    assert gate["promote"] == {"api": False, "worker": False, "web": False}
