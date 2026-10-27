"""Stream an object once to hash it, detect its type, and reject unsafe packages."""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass

from graph_rag.domain.storage.limits import assert_safe_zip_archive
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.intake.mime_detection import detect_mime_type
from graph_rag.shared.exceptions import ValidationError


@dataclass(frozen=True)
class VerifiedObject:
    content_hash: str
    byte_size: int
    mime_type: str


async def verify_object_stream(
    store: object,
    tenant: TenantContext,
    *,
    object_key: str,
    declared_byte_size: int,
    filename: str,
    max_bytes: int,
) -> VerifiedObject:
    """Hash and classify without keeping the object as one ``bytes`` value."""
    if declared_byte_size < 1 or declared_byte_size > max_bytes:
        raise ValidationError(
            "Declared size is outside the published limit",
            details={"declared_byte_size": declared_byte_size, "max_bytes": max_bytes},
        )
    digest = hashlib.sha256()
    total = 0
    prefix = bytearray()
    spooled: tempfile.SpooledTemporaryFile[bytes] | None = None
    iterator = store.iter_bytes(tenant, object_key=object_key)  # type: ignore[attr-defined]
    async for chunk in iterator:
        if not chunk:
            continue
        total += len(chunk)
        if total > declared_byte_size or total > max_bytes:
            raise ValidationError(
                "Object is larger than the declared size",
                details={"byte_size": total, "declared_byte_size": declared_byte_size},
            )
        digest.update(chunk)
        if len(prefix) < 64:
            prefix.extend(chunk[: 64 - len(prefix)])
        if chunk.startswith(b"PK") or prefix.startswith(b"PK"):
            if spooled is None:
                spooled = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)  # noqa: SIM115
                if prefix and not chunk.startswith(b"PK"):
                    spooled.write(bytes(prefix))
            spooled.write(chunk)
    if total < 1:
        raise ValidationError("Object is empty", details={"byte_size": total})
    content_hash = digest.hexdigest()
    if spooled is not None:
        spooled.seek(0)
        archive = spooled.read()
        spooled.close()
        assert_safe_zip_archive(archive)
        sample = archive
    else:
        # MIME sniff needs a small prefix for binary types and the text sample
        # for plain text. Re-read only when the prefix is not enough for text.
        sample = bytes(prefix)
        binary_prefixes = (b"%PDF", b"\x89PNG", b"\xff\xd8\xff", b"PK", b"RIFF", b"II*", b"MM")
        if not sample.startswith(binary_prefixes):
            sample = await _reread_text_sample(store, tenant, object_key)
    mime_type = detect_mime_type(sample, filename=filename)
    return VerifiedObject(content_hash=content_hash, byte_size=total, mime_type=mime_type)


async def _reread_text_sample(store: object, tenant: TenantContext, object_key: str) -> bytes:
    collected = bytearray()
    iterator = store.iter_bytes(tenant, object_key=object_key, chunk_size=8192)  # type: ignore[attr-defined]
    async for chunk in iterator:
        collected.extend(chunk)
        if len(collected) >= 8192:
            break
    return bytes(collected)
