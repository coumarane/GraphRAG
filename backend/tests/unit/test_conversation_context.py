"""Conversation sticky context matching."""

from __future__ import annotations

from uuid import uuid4

from graph_rag.domain.conversation.conversation_context import (
    infer_context_entities,
    match_document_ids_for_entities,
    normalize_title,
)
from graph_rag.domain.conversation.context_resolver import QueryContextResolver


def test_match_sy_knp_entity_to_presentation_title() -> None:
    doc_id = uuid4()
    titles = {doc_id: "【Presentation】 SY-KNP.pdf", uuid4(): "Astaxanthin-LS1.pdf"}
    matched = match_document_ids_for_entities(["SY-KNP"], titles)
    assert matched == [doc_id]


def test_infer_entities_from_first_user_turn() -> None:
    resolver = QueryContextResolver()
    entities = infer_context_entities(
        "Over which pH range was the tinting test performed?",
        [{"role": "user", "content": "Who manufactures SY-KNP?"}],
        resolver,
    )
    assert any("SY-KNP" in item for item in entities)


def test_normalize_title() -> None:
    assert normalize_title("【Presentation】 SY-KNP.pdf") == "SY-KNP"
