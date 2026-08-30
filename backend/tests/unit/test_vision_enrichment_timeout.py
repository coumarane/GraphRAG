"""A stalled vision LLM call must not wedge the PARSE stage forever.

Regression test for an incident where a document's PARSE stage stayed at
the same low progress percentage for over a day. Root cause: per-element
vision enrichment (``_vision_enrich_pages``) retries on exception, but
``ChatModel.generate()`` had no timeout anywhere in the call chain -- a
stalled socket (proxy holding the connection open, provider outage) never
raises, so the retry/backoff loop never even runs and the whole PARSE
stage blocks indefinitely with no way to self-recover.
"""

from __future__ import annotations

import asyncio

import pytest

from graph_rag.application.ingestion import local_pipeline
from graph_rag.application.ingestion.local_pipeline import _vision_enrich_pages
from graph_rag.domain.elements.enums import ElementType
from graph_rag.domain.parsing.types import RawElement, RawPage, RawParserResult


class _HangingChatModel:
    """Simulates a stalled network call that never raises on its own."""

    async def generate(self, request: object) -> object:
        del request
        await asyncio.sleep(999)
        raise AssertionError("must be cancelled by the timeout before completing")


def _raw_with_one_image_on_page(page: int) -> RawParserResult:
    return RawParserResult(
        parser_name="docling",
        page_count=page,
        pages=[RawPage(page_number=n) for n in range(1, page + 1)],
        elements=[
            RawElement(
                element_type=ElementType.IMAGE,
                page_start=page,
                page_end=page,
                reading_order=0,
                raw_content=None,
                normalized_content=None,
            )
        ],
    )


@pytest.mark.asyncio
async def test_hung_vision_call_times_out_and_target_is_marked_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_pipeline, "_VISION_CALL_TIMEOUT_SECONDS", 0.05)

    async def _no_op_sleep(_seconds: float) -> None:
        return None

    # The 3-attempt retry loop's own backoff (1.5s, 3s) would otherwise add
    # real wall-clock delay to this test for no benefit.
    monkeypatch.setattr(local_pipeline.asyncio, "sleep", _no_op_sleep)
    monkeypatch.setattr(
        local_pipeline, "render_visual_png", lambda *args, **kwargs: b"\x89PNG\r\n\x1a\nfake"
    )

    raw = _raw_with_one_image_on_page(2)

    extras, enriched_pages, target_count, failed = await asyncio.wait_for(
        _vision_enrich_pages(_HangingChatModel(), b"%PDF-1.4\nplaceholder\n%%EOF\n", raw),
        timeout=5.0,
    )

    assert target_count == 1
    assert failed == 1
    assert extras == []
    assert enriched_pages == []
    assert raw.warnings == ["vision_failed_photo_page_2"]
