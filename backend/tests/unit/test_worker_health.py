"""Worker health answers live always and ready only when checks pass."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from graph_rag.infrastructure.workers.main import _health_connection


class _Writer:
    def __init__(self) -> None:
        self.buf = b""

    def write(self, data: bytes) -> None:
        self.buf += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


async def _call(path: str, checks: list[object]) -> bytes:
    reader = asyncio.StreamReader()
    reader.feed_data(f"GET {path} HTTP/1.1\r\n\r\n".encode())
    reader.feed_eof()
    writer = _Writer()
    await _health_connection(reader, writer, SimpleNamespace(ready_checks=checks))
    return writer.buf


def test_liveness_is_up_while_readiness_fails_closed() -> None:
    live = asyncio.run(_call("/health/live", [lambda: False]))
    ready = asyncio.run(_call("/health/ready", [lambda: False]))
    assert b"200" in live
    assert b"503" in ready
    assert b"200" not in ready.split(b"\r\n\r\n", 1)[0]
