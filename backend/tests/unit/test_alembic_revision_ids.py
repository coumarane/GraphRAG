"""Alembic revision id length guard.

Alembic's own bookkeeping table (``alembic_version.version_num``) is
``VARCHAR(32)`` by default. A revision id longer than that fails at
``UPDATE alembic_version`` time in real Postgres -- SQLite-based migration
tests don't enforce column width, so this only ever showed up once a
migration actually ran in CI against Postgres. This static check catches it
locally instead, across every migration file, not just one.
"""

from __future__ import annotations

import re
from pathlib import Path

_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_ALEMBIC_VERSION_NUM_MAX_LENGTH = 32
_REVISION_RE = re.compile(r'^revision:\s*str\s*=\s*"([^"]+)"', re.MULTILINE)


def test_every_migration_revision_id_fits_alembic_version_column() -> None:
    migration_files = sorted(_VERSIONS_DIR.glob("*.py"))
    assert migration_files, "expected at least one migration file"

    too_long: list[tuple[str, int]] = []
    for path in migration_files:
        match = _REVISION_RE.search(path.read_text())
        assert match is not None, f'{path.name}: no `revision: str = "..."` found'
        revision = match.group(1)
        if len(revision) > _ALEMBIC_VERSION_NUM_MAX_LENGTH:
            too_long.append((path.name, len(revision)))

    assert not too_long, (
        f"revision ids exceeding alembic_version.version_num's "
        f"{_ALEMBIC_VERSION_NUM_MAX_LENGTH}-char limit: {too_long}"
    )
