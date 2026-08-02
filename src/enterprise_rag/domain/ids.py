"""Deterministic and runtime identifier helpers.

Runtime entities use UUIDv7. Stable element/chunk identities use UUIDv5 when
source identity is stable enough to derive.

Python 3.13 does not ship ``uuid.uuid7`` (added in 3.14). This module provides
an RFC 9562-compatible implementation and prefers the stdlib when present.
"""

from __future__ import annotations

import os
import time
import uuid

# Application-owned namespace for deterministic UUIDv5 identifiers.
ENTERPRISE_RAG_NAMESPACE = uuid.UUID("a8f3c2e1-4b5d-6a7c-8d9e-0f1a2b3c4d5e")


def _uuid7_rfc9562() -> uuid.UUID:
    """Generate a UUIDv7 per RFC 9562."""
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_bytes = os.urandom(10)
    rand_a = int.from_bytes(rand_bytes[:2], "big") & 0x0FFF
    rand_b = int.from_bytes(rand_bytes[2:], "big") & ((1 << 62) - 1)
    uuid_int = (timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=uuid_int)


def new_id() -> uuid.UUID:
    """Allocate a time-ordered UUIDv7 for runtime entities."""
    stdlib_uuid7 = getattr(uuid, "uuid7", None)
    if callable(stdlib_uuid7):
        value = stdlib_uuid7()
        if isinstance(value, uuid.UUID):
            return value
    return _uuid7_rfc9562()


def deterministic_id(*parts: str, namespace: uuid.UUID = ENTERPRISE_RAG_NAMESPACE) -> uuid.UUID:
    """Derive a stable UUIDv5 from ordered identity parts."""
    if not parts:
        msg = "deterministic_id requires at least one part"
        raise ValueError(msg)
    return uuid.uuid5(namespace, "|".join(parts))


def content_sha256_hex(data: bytes | str) -> str:
    """Return a 64-character lowercase SHA-256 hex digest."""
    import hashlib

    payload = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(payload).hexdigest()
