"""Bounded concurrency helpers backed by asyncio semaphores."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from enterprise_rag.config.settings import ConcurrencySettings


@dataclass
class ConcurrencyLimiter:
    """Named semaphore pool for parser/model/storage work."""

    settings: ConcurrencySettings = field(default_factory=ConcurrencySettings)
    _semaphores: dict[str, asyncio.Semaphore] = field(default_factory=dict, init=False)

    def _semaphore(self, name: str, limit: int) -> asyncio.Semaphore:
        if name not in self._semaphores:
            self._semaphores[name] = asyncio.Semaphore(max(1, limit))
        return self._semaphores[name]

    @asynccontextmanager
    async def global_jobs(self) -> AsyncIterator[None]:
        async with self._semaphore("global_jobs", self.settings.global_jobs):
            yield

    @asynccontextmanager
    async def parser_jobs(self) -> AsyncIterator[None]:
        async with self._semaphore("parser_jobs", self.settings.parser_jobs):
            yield

    @asynccontextmanager
    async def ocr_pages(self) -> AsyncIterator[None]:
        async with self._semaphore("ocr_pages", self.settings.ocr_pages):
            yield

    @asynccontextmanager
    async def vision_calls(self) -> AsyncIterator[None]:
        async with self._semaphore("vision_calls", self.settings.vision_calls):
            yield

    @asynccontextmanager
    async def text_llm_calls(self) -> AsyncIterator[None]:
        async with self._semaphore("text_llm_calls", self.settings.text_llm_calls):
            yield

    @asynccontextmanager
    async def embeddings(self) -> AsyncIterator[None]:
        async with self._semaphore("embeddings", self.settings.embeddings):
            yield

    @asynccontextmanager
    async def storage_writes(self) -> AsyncIterator[None]:
        async with self._semaphore("storage_writes", self.settings.storage_writes):
            yield


__all__ = ["ConcurrencyLimiter"]
