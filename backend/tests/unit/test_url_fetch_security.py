"""Safe URL fetch SSRF protection tests."""

from __future__ import annotations

import pytest

from graph_rag.infrastructure.intake.url_fetch import SafeUrlFetcher
from graph_rag.shared.exceptions import ValidationError


@pytest.fixture
def fetcher() -> SafeUrlFetcher:
    return SafeUrlFetcher(max_upload_bytes=1024, allowed_schemes=("https",))


@pytest.mark.asyncio
async def test_rejects_http_and_credentials(fetcher: SafeUrlFetcher) -> None:
    with pytest.raises(ValidationError, match="scheme"):
        await fetcher.fetch("http://example.com/a.pdf")
    with pytest.raises(ValidationError, match="Credential"):
        await fetcher.fetch("https://user:pass@example.com/a.pdf")


@pytest.mark.asyncio
async def test_rejects_localhost(fetcher: SafeUrlFetcher) -> None:
    with pytest.raises(ValidationError):
        await fetcher.fetch("https://localhost/secret.pdf")
    with pytest.raises(ValidationError):
        await fetcher.fetch("https://127.0.0.1/secret.pdf")


@pytest.mark.asyncio
async def test_rejects_metadata_ip(fetcher: SafeUrlFetcher) -> None:
    with pytest.raises(ValidationError):
        await fetcher.fetch("https://169.254.169.254/latest/meta-data")
