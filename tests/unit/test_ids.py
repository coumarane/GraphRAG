"""Identifier helper tests."""

from __future__ import annotations

from uuid import UUID

from enterprise_rag.domain.ids import content_sha256_hex, deterministic_id, new_id


def test_new_id_is_uuid_version_7() -> None:
    value = new_id()
    assert isinstance(value, UUID)
    assert value.version == 7


def test_deterministic_id_is_stable() -> None:
    first = deterministic_id("tenant", "doc", "element-1")
    second = deterministic_id("tenant", "doc", "element-1")
    third = deterministic_id("tenant", "doc", "element-2")
    assert first == second
    assert first != third
    assert first.version == 5


def test_content_sha256_hex_length() -> None:
    digest = content_sha256_hex("hello")
    assert len(digest) == 64
    assert digest == content_sha256_hex(b"hello")
