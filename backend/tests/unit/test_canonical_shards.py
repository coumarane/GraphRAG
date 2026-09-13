"""CanonicalDocument page shards are independently readable."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from graph_rag.application.ingestion.canonical_markdown import canonical_document_markdown
from graph_rag.application.ingestion.canonical_store import CanonicalStore
from graph_rag.application.ingestion.extract_assets import extract_canonical_assets
from graph_rag.domain.documents import NormalizedDocument, NormalizedPage, ParserInfo
from graph_rag.domain.elements import (
    HeadingElement,
    ImageElement,
    TableCell,
    TableData,
    TableElement,
    TextElement,
)
from graph_rag.domain.elements.geometry import BoundingBox
from graph_rag.domain.ids import content_sha256_hex, new_id
from graph_rag.domain.storage.object_keys import (
    parse_page_json_key,
    parse_page_render_key,
)
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.memory import InMemoryObjectStore


class _RecordingObjectStore:
    def __init__(self, inner: InMemoryObjectStore) -> None:
        self.inner = inner
        self.gets: list[str] = []

    async def ensure_bucket(self) -> None:
        await self.inner.ensure_bucket()

    async def put_bytes(self, tenant: TenantContext, **kwargs: Any):
        return await self.inner.put_bytes(tenant, **kwargs)

    async def get_bytes(self, tenant: TenantContext, *, object_key: str) -> bytes:
        self.gets.append(object_key)
        return await self.inner.get_bytes(tenant, object_key=object_key)

    async def delete_prefix(self, tenant: TenantContext, *, prefix: str) -> int:
        return await self.inner.delete_prefix(tenant, prefix=prefix)

    async def presign_get(self, tenant: TenantContext, **kwargs: Any) -> str:
        return await self.inner.presign_get(tenant, **kwargs)


def _hash(text: str) -> str:
    return content_sha256_hex(text)


def _ids() -> dict[str, UUID]:
    return {
        "tenant_id": new_id(),
        "document_id": new_id(),
        "version_id": new_id(),
    }


def _three_page_document() -> tuple[TenantContext, NormalizedDocument]:
    ids = _ids()
    tenant = TenantContext(tenant_id=ids["tenant_id"], tenant_key="shards")
    pages = [
        NormalizedPage(page_id=new_id(), page_number=1),
        NormalizedPage(page_id=new_id(), page_number=2),
        NormalizedPage(page_id=new_id(), page_number=3),
    ]
    elements = [
        HeadingElement(
            element_id=new_id(),
            **ids,
            page_start=1,
            page_end=1,
            reading_order=0,
            content_hash=_hash("Intro"),
            level=1,
            normalized_content="Intro",
        ),
        TextElement(
            element_id=new_id(),
            **ids,
            page_start=2,
            page_end=2,
            reading_order=0,
            content_hash=_hash("page-two"),
            normalized_content="Only on page two.",
        ),
        TableElement(
            element_id=new_id(),
            **ids,
            page_start=3,
            page_end=3,
            reading_order=0,
            content_hash=_hash("table"),
            table=TableData(
                caption="Viscosity",
                cells=[
                    TableCell(row_index=0, column_index=0, text="a"),
                    TableCell(row_index=0, column_index=1, text="b"),
                ],
            ),
        ),
    ]
    document = NormalizedDocument(
        **ids,
        source_filename="report.pdf",
        mime_type="application/pdf",
        title="Report",
        page_count=3,
        pages=pages,
        elements=elements,
        parser_info=ParserInfo(parser_name="docling", parser_version="1"),
    )
    return tenant, document


@pytest.mark.asyncio
async def test_load_page_does_not_read_other_page_json() -> None:
    inner = InMemoryObjectStore()
    store = CanonicalStore(inner)
    tenant, document = _three_page_document()
    attempt_id = new_id()
    await store.write_from_document(tenant, document, attempt_id=attempt_id)

    recorder = _RecordingObjectStore(inner)
    isolated = CanonicalStore(recorder)
    page = await isolated.load_page(
        tenant,
        document_id=document.document_id,
        version_id=document.version_id,
        page_number=2,
    )
    assert page.page_number == 2
    assert len(page.elements) == 1
    assert page.elements[0].normalized_content == "Only on page two."

    page_keys = [key for key in recorder.gets if "/pages/" in key]
    own_key = parse_page_json_key(
        tenant_id=tenant.tenant_id,
        document_id=document.document_id,
        version_id=document.version_id,
        attempt_id=attempt_id,
        page_number=2,
    )
    assert page_keys == [own_key]
    assert not any(key.endswith("pages/0001.json") for key in recorder.gets)
    assert not any(key.endswith("pages/0003.json") for key in recorder.gets)


@pytest.mark.asyncio
async def test_load_document_metadata_does_not_read_page_json() -> None:
    inner = InMemoryObjectStore()
    store = CanonicalStore(inner)
    tenant, document = _three_page_document()
    await store.write_from_document(tenant, document, attempt_id=new_id())

    recorder = _RecordingObjectStore(inner)
    isolated = CanonicalStore(recorder)
    metadata = await isolated.load_document_metadata(
        tenant, document_id=document.document_id, version_id=document.version_id
    )
    assert metadata.page_count == 3
    assert metadata.title == "Report"
    assert "elements" not in metadata.model_dump()
    assert not any("/pages/" in key for key in recorder.gets)


@pytest.mark.asyncio
async def test_load_complete_reconstructs_all_pages() -> None:
    store = CanonicalStore(InMemoryObjectStore())
    tenant, document = _three_page_document()
    await store.write_from_document(tenant, document, attempt_id=new_id())
    rebuilt = await store.load_complete_canonical_document(
        tenant, document_id=document.document_id, version_id=document.version_id
    )
    assert len(rebuilt.elements) == 3
    contents = {
        element.normalized_content for element in rebuilt.elements if element.normalized_content
    }
    assert contents == {"Intro", "Only on page two."}
    assert rebuilt.page_count == 3
    markdown = canonical_document_markdown(document)
    assert "# Report" in markdown
    assert "# Intro" in markdown


@pytest.mark.asyncio
async def test_extract_assets_writes_page_png_and_table_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    png = b"\x89PNG\r\n\x1a\nfake-png-bytes"
    monkeypatch.setattr(
        "graph_rag.application.ingestion.extract_assets.render_visual_png",
        lambda *args, **kwargs: png,
    )
    inner = InMemoryObjectStore()
    tenant, document = _three_page_document()
    ids = {
        "tenant_id": document.tenant_id,
        "document_id": document.document_id,
        "version_id": document.version_id,
    }
    figure = ImageElement(
        element_id=new_id(),
        **ids,
        page_start=2,
        page_end=2,
        reading_order=1,
        content_hash=_hash("figure"),
        bounding_boxes=[BoundingBox(page_number=2, x0=0.1, y0=0.1, x1=0.4, y1=0.4)],
    )
    document = document.model_copy(update={"elements": [*document.elements, figure]})
    attempt_id = new_id()
    updated, warnings = await extract_canonical_assets(
        object_store=inner,
        tenant=tenant,
        document=document,
        original_bytes=b"%PDF-1.4 fake",
        mime_type="application/pdf",
        filename="report.pdf",
        attempt_id=attempt_id,
    )
    assert warnings == []
    table = next(item for item in updated.elements if item.element_type.value == "table")
    image = next(item for item in updated.elements if item.element_type.value == "image")
    assert table.source_asset_id is not None
    assert image.source_asset_id is not None
    assert any(asset.asset_type == "page_render" for asset in updated.assets)
    assert any(asset.asset_type == "table" for asset in updated.assets)
    assert any(asset.asset_type == "figure" for asset in updated.assets)

    recorder = _RecordingObjectStore(inner)
    store = CanonicalStore(recorder)
    render = await store.load_page_render(
        tenant,
        document_id=document.document_id,
        version_id=document.version_id,
        page_number=2,
    )
    assert render == png
    render_key = parse_page_render_key(
        tenant_id=tenant.tenant_id,
        document_id=document.document_id,
        version_id=document.version_id,
        attempt_id=attempt_id,
        page_number=2,
    )
    assert render_key in recorder.gets
    assert not any(key.endswith("/original/") or "/original/" in key for key in recorder.gets)

    table_asset = next(asset for asset in updated.assets if asset.asset_type == "table")
    table_bytes = await store.load_asset(tenant, table_asset)
    assert b"Viscosity" in table_bytes or b'"a"' in table_bytes


@pytest.mark.asyncio
async def test_extract_assets_skips_rasterization_for_text() -> None:
    inner = InMemoryObjectStore()
    tenant, document = _three_page_document()
    document = document.model_copy(
        update={"mime_type": "text/plain", "source_filename": "notes.txt"}
    )
    updated, warnings = await extract_canonical_assets(
        object_store=inner,
        tenant=tenant,
        document=document,
        original_bytes=b"hello",
        mime_type="text/plain",
        filename="notes.txt",
        attempt_id=new_id(),
    )
    assert "page_renders_skipped:not_pdf" in warnings
    table = next(item for item in updated.elements if item.element_type.value == "table")
    assert table.source_asset_id is not None
    assert (
        await CanonicalStore(inner).load_page_render(
            tenant,
            document_id=document.document_id,
            version_id=document.version_id,
            page_number=1,
        )
        is None
    )
