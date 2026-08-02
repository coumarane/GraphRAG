"""Normalized document and element unit/contract tests."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from enterprise_rag.domain.documents import NormalizedDocument, ParserInfo
from enterprise_rag.domain.elements import (
    DocumentElement,
    ElementType,
    HeadingElement,
    TableData,
    TableElement,
    TextElement,
)
from enterprise_rag.domain.ids import content_sha256_hex, new_id
from tests.unit.contract_support import assert_matches_contract

_ELEMENT_ADAPTER = TypeAdapter(DocumentElement)


def _ids() -> dict[str, Any]:
    return {
        "tenant_id": new_id(),
        "document_id": new_id(),
        "version_id": new_id(),
    }


def _hash(text: str) -> str:
    return content_sha256_hex(text)


def test_text_element_discriminator() -> None:
    ids = _ids()
    element = TextElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=0,
        section_path=["Intro"],
        raw_content="Hello",
        normalized_content="Hello",
        content_hash=_hash("Hello"),
    )
    assert element.element_type is ElementType.TEXT
    parsed = _ELEMENT_ADAPTER.validate_python(element.model_dump(mode="json"))
    assert isinstance(parsed, TextElement)


def test_heading_and_table_union_roundtrip() -> None:
    ids = _ids()
    heading = HeadingElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=0,
        section_path=["Methods"],
        content_hash=_hash("Methods"),
        level=2,
        normalized_content="Methods",
    )
    table = TableElement(
        element_id=new_id(),
        **ids,
        page_start=2,
        page_end=2,
        reading_order=1,
        section_path=["Methods", "Results"],
        content_hash=_hash("table"),
        table=TableData(caption="Viscosity", markdown="| a | b |", column_headers=["a", "b"]),
    )
    for item in (heading, table):
        restored = _ELEMENT_ADAPTER.validate_python(item.model_dump(mode="json"))
        assert restored.element_type == item.element_type


def test_invalid_content_hash_rejected() -> None:
    ids = _ids()
    with pytest.raises(ValidationError):
        TextElement(
            element_id=new_id(),
            **ids,
            page_start=1,
            page_end=1,
            reading_order=0,
            content_hash="not-a-hash",
        )


def test_normalized_document_matches_contract() -> None:
    tenant_id = new_id()
    document_id = new_id()
    version_id = new_id()
    element = TextElement(
        element_id=new_id(),
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        page_start=1,
        page_end=1,
        reading_order=0,
        section_path=[],
        content_hash=_hash("body"),
        normalized_content="body",
    )
    document = NormalizedDocument(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        title="Sample",
        source_filename="sample.pdf",
        mime_type="application/pdf",
        language="en",
        page_count=0,
        elements=[element],
        parser_info=ParserInfo(parser_name="docling", parser_version="1.0.0"),
    )
    payload = document.model_dump(mode="json")
    assert_matches_contract("normalized-document", payload)


def test_document_rejects_tenant_mismatch() -> None:
    tenant_id = new_id()
    document_id = new_id()
    version_id = new_id()
    element = TextElement(
        element_id=new_id(),
        tenant_id=uuid4(),
        document_id=document_id,
        version_id=version_id,
        page_start=1,
        page_end=1,
        reading_order=0,
        content_hash=_hash("x"),
    )
    with pytest.raises(ValidationError, match="tenant_id"):
        NormalizedDocument(
            tenant_id=tenant_id,
            document_id=document_id,
            version_id=version_id,
            source_filename="a.pdf",
            mime_type="application/pdf",
            page_count=0,
            elements=[element],
            parser_info=ParserInfo(parser_name="docling"),
        )
