"""ConfidenceBand and extraction Pydantic type tests (Phase 4)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from graph_rag.application.document_intelligence.models import (
    ConfidenceBand,
    DocumentIntelligenceExtractionRequest,
    confidence_band,
)
from graph_rag.domain.documents.components import ParserInfo
from graph_rag.domain.documents.document import NormalizedDocument
from graph_rag.domain.ids import new_id


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, ConfidenceBand.LOW),
        (0.6999, ConfidenceBand.LOW),
        (0.70, ConfidenceBand.MEDIUM),
        (0.8999, ConfidenceBand.MEDIUM),
        (0.90, ConfidenceBand.HIGH),
        (1.0, ConfidenceBand.HIGH),
    ],
)
def test_confidence_band_boundaries(value: float, expected: ConfidenceBand) -> None:
    assert confidence_band(value) is expected


def _empty_document() -> NormalizedDocument:
    return NormalizedDocument(
        tenant_id=new_id(),
        document_id=new_id(),
        version_id=new_id(),
        source_filename="doc.pdf",
        mime_type="application/pdf",
        page_count=1,
        parser_info=ParserInfo(parser_name="docling", parser_version="1.0"),
    )


def test_extraction_request_rejects_empty_field_list() -> None:
    with pytest.raises(ValidationError):
        DocumentIntelligenceExtractionRequest(document=_empty_document(), fields=[])
