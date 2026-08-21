"""SHA-256 hashing helper."""

from __future__ import annotations

from enterprise_rag.domain.ids import content_sha256_hex


class Sha256HashingService:
    """Application hashing adapter."""

    def sha256_hex(self, data: bytes) -> str:
        return content_sha256_hex(data)
