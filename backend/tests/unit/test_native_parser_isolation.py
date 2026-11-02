"""A native SIGILL must not kill the worker process.

Exit code 132 (128 + SIGILL) was observed on the DEV ingestion worker after
Marker logged a normal Python failure. The next in-process native library
(PaddleOCR or PDFium) aborted the whole container, Redis redelivered the
message, and the worker crash-looped. The child process now absorbs that
signal and the parent records a parser error.
"""

from __future__ import annotations

import os
import signal

import pytest

from graph_rag.application.ingestion.local_pipeline import _parse_parser_name
from graph_rag.infrastructure.parsers.base import run_callable_isolated
from graph_rag.shared.exceptions import ParserError


def _sigill() -> None:
    os.kill(os.getpid(), signal.SIGILL)


def _marker_style_failure() -> dict[str, str]:
    raise ParserError("Marker conversion failed")


def _ok(value: str) -> str:
    return value


@pytest.mark.asyncio
async def test_sigill_in_parser_child_becomes_exit_132() -> None:
    parent = os.getpid()
    with pytest.raises(ParserError, match="Native parser process aborted") as caught:
        await run_callable_isolated(_sigill, timeout_seconds=30)
    assert os.getpid() == parent
    assert caught.value.details["exit_code"] == 132
    assert caught.value.details["signal"] == "SIGILL"


@pytest.mark.asyncio
async def test_parser_error_in_child_stays_a_parser_error() -> None:
    with pytest.raises(ParserError, match="Marker conversion failed"):
        await run_callable_isolated(_marker_style_failure, timeout_seconds=30)


@pytest.mark.asyncio
async def test_isolated_parser_returns_its_result() -> None:
    assert await run_callable_isolated(_ok, "parsed", timeout_seconds=30) == "parsed"


def test_reindex_is_not_a_parser_name() -> None:
    assert _parse_parser_name("reindex") is None
    assert _parse_parser_name("auto") is None
    assert _parse_parser_name("pdfium") == "pdfium"
