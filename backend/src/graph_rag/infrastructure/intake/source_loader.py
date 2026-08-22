"""Local filesystem source loading."""

from __future__ import annotations

import asyncio
from pathlib import Path

from graph_rag.domain.security import MalwareScanner
from graph_rag.domain.storage.mime import assert_within_size_limit
from graph_rag.domain.storage.object_keys import sanitize_filename
from graph_rag.domain.storage.protocols import SourceBytes
from graph_rag.infrastructure.intake.hashing import Sha256HashingService
from graph_rag.infrastructure.intake.mime_detection import detect_mime_type
from graph_rag.infrastructure.intake.url_fetch import SafeUrlFetcher
from graph_rag.infrastructure.security.malware import NoOpMalwareScanner, ensure_clean
from graph_rag.shared.exceptions import ValidationError


class DefaultSourceLoader:
    """Load local paths and remote URLs into validated ``SourceBytes``."""

    def __init__(
        self,
        *,
        max_upload_bytes: int,
        url_fetcher: SafeUrlFetcher | None = None,
        allowed_schemes: tuple[str, ...] = ("https",),
        download_timeout_seconds: float = 30.0,
        max_redirects: int = 3,
        malware_scanner: MalwareScanner | None = None,
    ) -> None:
        self._max_upload_bytes = max_upload_bytes
        self._hasher = Sha256HashingService()
        self._malware_scanner = malware_scanner or NoOpMalwareScanner()
        self._url_fetcher = url_fetcher or SafeUrlFetcher(
            max_upload_bytes=max_upload_bytes,
            timeout_seconds=download_timeout_seconds,
            max_redirects=max_redirects,
            allowed_schemes=allowed_schemes,
        )

    async def load_local(self, path: str) -> SourceBytes:
        def _read() -> tuple[str, bytes, str]:
            file_path = Path(path).expanduser()
            if not file_path.exists():
                raise ValidationError("Local source path does not exist", details={"path": path})
            if not file_path.is_file():
                raise ValidationError("Local source path is not a file", details={"path": path})
            resolved = file_path.resolve()
            byte_size = resolved.stat().st_size
            assert_within_size_limit(byte_size, max_upload_bytes=self._max_upload_bytes)
            data = resolved.read_bytes()
            assert_within_size_limit(len(data), max_upload_bytes=self._max_upload_bytes)
            return sanitize_filename(resolved.name), data, str(resolved)

        filename, data, source_uri = await asyncio.to_thread(_read)
        await ensure_clean(self._malware_scanner, data, filename=filename)
        mime_type = detect_mime_type(data, filename=filename)
        return SourceBytes(
            filename=filename,
            mime_type=mime_type,
            content=data,
            source_uri=source_uri,
        )

    async def load_url(self, url: str) -> SourceBytes:
        source = await self._url_fetcher.fetch(url)
        await ensure_clean(self._malware_scanner, source.content, filename=source.filename)
        return source

    def hash_content(self, data: bytes) -> str:
        return self._hasher.sha256_hex(data)
