"""Package metadata smoke tests."""

from __future__ import annotations

from enterprise_rag import __version__


def test_version_is_semver_like() -> None:
    parts = __version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
