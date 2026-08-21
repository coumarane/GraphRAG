"""Regression tests for header/footer boilerplate detection."""

from __future__ import annotations

from enterprise_rag.application.chunking.hierarchical import HierarchicalMultimodalChunker
from enterprise_rag.domain.elements.enums import ElementType
from enterprise_rag.domain.elements.models import TextElement
from enterprise_rag.domain.ids import content_sha256_hex, new_id
from enterprise_rag.domain.parsing.boilerplate import (
    detect_boilerplate,
    reclassify_boilerplate_elements,
)
from enterprise_rag.domain.parsing.normalize import normalize_parser_result
from enterprise_rag.domain.parsing.types import ParseSource, RawElement, RawPage, RawParserResult
from enterprise_rag.domain.tenant import TenantContext


def test_detect_repeated_footer_across_pages() -> None:
    pages = [
        (page, [f"Product overview {page}", "Confidential — ACME Corp", f"{page}"])
        for page in range(1, 6)
    ]
    matches = detect_boilerplate(pages, min_pages=3, frequency_threshold=0.5)
    texts = {match.normalized_text for match in matches}
    assert any("confidential" in text for text in texts)


def test_reclassify_promotes_footer_elements() -> None:
    tenant_id = new_id()
    document_id = new_id()
    version_id = new_id()
    elements: list[TextElement] = []
    order = 0
    for page in range(1, 6):
        for text in (f"Useful content on page {page}", "ACME Confidential"):
            elements.append(
                TextElement(
                    element_id=new_id(),
                    tenant_id=tenant_id,
                    document_id=document_id,
                    version_id=version_id,
                    page_start=page,
                    page_end=page,
                    reading_order=order,
                    raw_content=text,
                    normalized_content=text,
                    content_hash=content_sha256_hex(text),
                )
            )
            order += 1
    rewritten = reclassify_boilerplate_elements(elements)
    footers = [item for item in rewritten if item.element_type is ElementType.PAGE_FOOTER]
    assert footers
    assert all("confidential" in (item.normalized_content or "").casefold() for item in footers)


def test_normalize_attaches_boilerplate_metadata() -> None:
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    elements = []
    pages = []
    order = 0
    for page in range(1, 5):
        pages.append(RawPage(page_number=page, text_density=100.0))
        for text in (f"Section body {page}", "Company Footer Banner"):
            elements.append(
                RawElement(
                    element_type=ElementType.TEXT,
                    page_start=page,
                    page_end=page,
                    reading_order=order,
                    raw_content=text,
                    normalized_content=text,
                )
            )
            order += 1
    raw = RawParserResult(
        parser_name="test",
        page_count=4,
        pages=pages,
        elements=elements,
    )
    source = ParseSource(
        tenant_id=tenant.tenant_id,
        document_id=new_id(),
        version_id=new_id(),
        filename="brochure.pdf",
        mime_type="application/pdf",
        content=b"%PDF",
    )
    doc = normalize_parser_result(raw, source)
    assert "boilerplate" in doc.metadata
    assert any(
        element.element_type in {ElementType.PAGE_HEADER, ElementType.PAGE_FOOTER}
        for element in doc.elements
    )


def test_header_only_fact_survives_into_a_retrievable_chunk() -> None:
    """Regression: a fact that ONLY appears in a repeated letterhead/header
    (e.g. a manufacturer's name on a title-slide logo, present on every page
    but never mentioned in the body text) must still end up in some chunk's
    text — previously the chunker unconditionally dropped every PAGE_HEADER
    element, making such facts permanently unretrievable by any query.
    """
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    elements = []
    pages = []
    order = 0
    for page in range(1, 6):
        pages.append(RawPage(page_number=page, text_density=100.0))
        for text in ("Acme Chemicals Co., Ltd.", f"Product body text on slide {page}"):
            elements.append(
                RawElement(
                    element_type=ElementType.TEXT,
                    page_start=page,
                    page_end=page,
                    reading_order=order,
                    raw_content=text,
                    normalized_content=text,
                )
            )
            order += 1
    raw = RawParserResult(
        parser_name="test",
        page_count=5,
        pages=pages,
        elements=elements,
    )
    source = ParseSource(
        tenant_id=tenant.tenant_id,
        document_id=new_id(),
        version_id=new_id(),
        filename="brochure.pdf",
        mime_type="application/pdf",
        content=b"%PDF",
    )
    document = normalize_parser_result(raw, source)
    # Sanity check: the repeated letterhead line really was classified as a
    # header and excluded from ordinary section text, same as production.
    assert any(
        element.element_type is ElementType.PAGE_HEADER
        and "Acme Chemicals" in (element.normalized_content or "")
        for element in document.elements
    )

    result = HierarchicalMultimodalChunker().chunk(document)
    all_text = "\n".join(chunk.text for chunk in result.all_chunks)
    assert "Acme Chemicals Co., Ltd." in all_text
