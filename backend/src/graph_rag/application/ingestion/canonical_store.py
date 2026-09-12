"""Read/write sharded CanonicalDocument artifacts without loading the whole tree."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from graph_rag.application.ingestion.canonical_markdown import canonical_document_markdown
from graph_rag.domain.documents.canonical_shards import (
    AssetArtifactRef,
    CanonicalCurrentPointer,
    CanonicalDocumentMetadata,
    CanonicalManifest,
    CanonicalPageArtifact,
    PageArtifactRef,
)
from graph_rag.domain.documents.components import DocumentAsset, NormalizedPage
from graph_rag.domain.documents.document import CanonicalDocument, NormalizedDocument
from graph_rag.domain.ids import content_sha256_hex, deterministic_id
from graph_rag.domain.storage.object_keys import (
    assert_tenant_object_prefix,
    parse_current_pointer_key,
    parse_document_key,
    parse_manifest_key,
    parse_markdown_key,
    parse_page_json_key,
    parse_page_render_key,
)
from graph_rag.domain.storage.protocols import ObjectStore
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import NotFoundError


class CanonicalStore:
    """Page-isolated CanonicalDocument persistence over the object store."""

    def __init__(self, object_store: ObjectStore) -> None:
        self.object_store = object_store

    async def write_from_document(
        self,
        tenant: TenantContext,
        document: NormalizedDocument,
        *,
        attempt_id: UUID,
    ) -> CanonicalManifest:
        """Persist metadata, per-page JSON, derived Markdown, and the current pointer."""
        ids = _ids(tenant, document)
        page_numbers = _page_numbers(document)
        assets_by_page = _assets_by_page(document.assets)
        page_refs: list[PageArtifactRef] = []
        written_pages: list[CanonicalPageArtifact] = []

        for page_number in page_numbers:
            page_meta = _page_meta(document, page_number)
            elements = [
                element
                for element in document.elements
                if element.page_start <= page_number <= element.page_end
            ]
            page_assets = assets_by_page.get(page_number, [])
            render_key = next(
                (asset.object_key for asset in page_assets if asset.asset_type == "page_render"),
                None,
            )
            if render_key is None:
                candidate = parse_page_render_key(
                    **ids, attempt_id=attempt_id, page_number=page_number
                )
                if any(asset.object_key == candidate for asset in document.assets):
                    render_key = candidate
            object_key = parse_page_json_key(**ids, attempt_id=attempt_id, page_number=page_number)
            artifact = CanonicalPageArtifact(
                page_number=page_number,
                page=page_meta,
                elements=elements,
                asset_refs=page_assets,
            )
            await self._put_json(tenant, object_key, artifact.model_dump(mode="json"))
            page_refs.append(
                PageArtifactRef(
                    page_number=page_number,
                    object_key=object_key,
                    element_count=len(elements),
                    render_object_key=render_key,
                )
            )
            written_pages.append(artifact)

        document_key = parse_document_key(**ids, attempt_id=attempt_id)
        markdown_key = parse_markdown_key(**ids, attempt_id=attempt_id)
        manifest_key = parse_manifest_key(**ids, attempt_id=attempt_id)
        metadata = CanonicalDocumentMetadata(
            attempt_id=attempt_id,
            tenant_id=document.tenant_id,
            document_id=document.document_id,
            version_id=document.version_id,
            title=document.title,
            source_filename=document.source_filename,
            mime_type=document.mime_type,
            language=document.language,
            page_count=document.page_count,
            metadata=document.metadata,
            pages=[item.page for item in written_pages] or list(document.pages),
            sections=document.sections,
            assets=document.assets,
            references=document.references,
            parser_info=document.parser_info,
            page_refs=page_refs,
        )
        await self._put_json(tenant, document_key, metadata.model_dump(mode="json"))
        markdown = canonical_document_markdown(document)
        await self._put_bytes(
            tenant,
            object_key=markdown_key,
            data=_nonempty_bytes(markdown.encode("utf-8")),
            content_type="text/markdown; charset=utf-8",
        )
        manifest = CanonicalManifest(
            attempt_id=attempt_id,
            tenant_id=document.tenant_id,
            document_id=document.document_id,
            version_id=document.version_id,
            created_at=datetime.now(UTC),
            parser_name=document.parser_info.parser_name,
            page_count=document.page_count,
            document_key=document_key,
            markdown_key=markdown_key,
            pages=page_refs,
            assets=[_asset_ref(asset) for asset in document.assets],
        )
        await self._put_json(tenant, manifest_key, manifest.model_dump(mode="json"))
        pointer = CanonicalCurrentPointer(
            attempt_id=attempt_id,
            manifest_key=manifest_key,
            document_key=document_key,
        )
        await self._put_json(
            tenant,
            parse_current_pointer_key(**ids),
            pointer.model_dump(mode="json"),
        )
        return manifest

    async def load_current_pointer(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
    ) -> CanonicalCurrentPointer | None:
        key = parse_current_pointer_key(
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_id=version_id,
        )
        payload = await self._get_json(tenant, key)
        if payload is None:
            return None
        return CanonicalCurrentPointer.model_validate(payload)

    async def load_manifest(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
        attempt_id: UUID | None = None,
    ) -> CanonicalManifest:
        resolved = attempt_id or await self._require_attempt(
            tenant, document_id=document_id, version_id=version_id
        )
        key = parse_manifest_key(
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_id=version_id,
            attempt_id=resolved,
        )
        payload = await self._require_json(tenant, key)
        return CanonicalManifest.model_validate(payload)

    async def load_document_metadata(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
        attempt_id: UUID | None = None,
    ) -> CanonicalDocumentMetadata:
        """Load document.json only. Does not read ``pages/*.json``."""
        resolved = attempt_id or await self._require_attempt(
            tenant, document_id=document_id, version_id=version_id
        )
        key = parse_document_key(
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_id=version_id,
            attempt_id=resolved,
        )
        payload = await self._require_json(tenant, key)
        return CanonicalDocumentMetadata.model_validate(payload)

    async def load_page(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
        page_number: int,
        attempt_id: UUID | None = None,
    ) -> CanonicalPageArtifact:
        """Load one page JSON shard. Does not read other pages."""
        if page_number < 1:
            raise NotFoundError(
                "Page out of range",
                details={"document_id": str(document_id), "page": page_number},
            )
        resolved = attempt_id or await self._require_attempt(
            tenant, document_id=document_id, version_id=version_id
        )
        key = parse_page_json_key(
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_id=version_id,
            attempt_id=resolved,
            page_number=page_number,
        )
        payload = await self._require_json(tenant, key)
        return CanonicalPageArtifact.model_validate(payload)

    async def load_pages(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
        page_numbers: list[int],
        attempt_id: UUID | None = None,
    ) -> list[CanonicalPageArtifact]:
        resolved = attempt_id or await self._require_attempt(
            tenant, document_id=document_id, version_id=version_id
        )
        pages: list[CanonicalPageArtifact] = []
        for page_number in page_numbers:
            pages.append(
                await self.load_page(
                    tenant,
                    document_id=document_id,
                    version_id=version_id,
                    page_number=page_number,
                    attempt_id=resolved,
                )
            )
        return pages

    async def load_asset(
        self,
        tenant: TenantContext,
        asset_reference: AssetArtifactRef | DocumentAsset | str,
    ) -> bytes:
        object_key = (
            asset_reference if isinstance(asset_reference, str) else asset_reference.object_key
        )
        assert_tenant_object_prefix(object_key, tenant.tenant_id)
        return await self.object_store.get_bytes(tenant, object_key=object_key)

    async def load_page_render(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
        page_number: int,
        attempt_id: UUID | None = None,
    ) -> bytes | None:
        """Return stored page PNG bytes, or None when the render shard is absent."""
        try:
            resolved = attempt_id or await self._require_attempt(
                tenant, document_id=document_id, version_id=version_id
            )
        except NotFoundError:
            return None
        key = parse_page_render_key(
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_id=version_id,
            attempt_id=resolved,
            page_number=page_number,
        )
        try:
            return await self.object_store.get_bytes(tenant, object_key=key)
        except NotFoundError:
            return None

    async def load_complete_canonical_document(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
        attempt_id: UUID | None = None,
    ) -> CanonicalDocument:
        """Compat reconstruction for chunking/graph. Reads every page shard."""
        metadata = await self.load_document_metadata(
            tenant,
            document_id=document_id,
            version_id=version_id,
            attempt_id=attempt_id,
        )
        page_numbers = [ref.page_number for ref in metadata.page_refs]
        if not page_numbers and metadata.page_count:
            page_numbers = list(range(1, metadata.page_count + 1))
        pages = await self.load_pages(
            tenant,
            document_id=document_id,
            version_id=version_id,
            page_numbers=page_numbers,
            attempt_id=metadata.attempt_id,
        )
        seen: set[UUID] = set()
        elements = []
        for page in pages:
            for element in page.elements:
                if element.element_id in seen:
                    continue
                seen.add(element.element_id)
                elements.append(element)
        return CanonicalDocument(
            tenant_id=metadata.tenant_id,
            document_id=metadata.document_id,
            version_id=metadata.version_id,
            title=metadata.title,
            source_filename=metadata.source_filename,
            mime_type=metadata.mime_type,
            language=metadata.language,
            page_count=metadata.page_count,
            metadata=metadata.metadata,
            pages=metadata.pages or [page.page for page in pages],
            elements=elements,
            sections=metadata.sections,
            assets=metadata.assets,
            references=metadata.references,
            parser_info=metadata.parser_info,
        )

    async def _require_attempt(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
    ) -> UUID:
        pointer = await self.load_current_pointer(
            tenant, document_id=document_id, version_id=version_id
        )
        if pointer is None:
            raise NotFoundError(
                "Canonical parse shards not found",
                details={
                    "document_id": str(document_id),
                    "version_id": str(version_id),
                },
            )
        return pointer.attempt_id

    async def _put_json(
        self,
        tenant: TenantContext,
        object_key: str,
        payload: dict[str, Any],
    ) -> None:
        raw = json.dumps(payload, default=str).encode("utf-8")
        await self._put_bytes(
            tenant,
            object_key=object_key,
            data=raw,
            content_type="application/json",
        )

    async def _put_bytes(
        self,
        tenant: TenantContext,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
    ) -> None:
        payload = _nonempty_bytes(data)
        await self.object_store.put_bytes(
            tenant,
            object_key=object_key,
            data=payload,
            content_type=content_type,
            content_hash=content_sha256_hex(payload),
        )

    async def _get_json(self, tenant: TenantContext, object_key: str) -> dict[str, Any] | None:
        try:
            data = await self.object_store.get_bytes(tenant, object_key=object_key)
        except NotFoundError:
            return None
        parsed = json.loads(data.decode("utf-8"))
        if not isinstance(parsed, dict):
            return None
        return parsed

    async def _require_json(self, tenant: TenantContext, object_key: str) -> dict[str, Any]:
        payload = await self._get_json(tenant, object_key)
        if payload is None:
            raise NotFoundError("Object not found", details={"object_key": object_key})
        return payload


def _ids(tenant: TenantContext, document: NormalizedDocument) -> dict[str, UUID]:
    return {
        "tenant_id": tenant.tenant_id,
        "document_id": document.document_id,
        "version_id": document.version_id,
    }


def _page_numbers(document: NormalizedDocument) -> list[int]:
    numbers = {page.page_number for page in document.pages}
    if document.page_count:
        numbers.update(range(1, document.page_count + 1))
    for element in document.elements:
        numbers.update(range(element.page_start, element.page_end + 1))
    return sorted(numbers)


def _page_meta(document: NormalizedDocument, page_number: int) -> NormalizedPage:
    for page in document.pages:
        if page.page_number == page_number:
            return page
    return NormalizedPage(
        page_id=deterministic_id(
            str(document.tenant_id),
            str(document.document_id),
            str(document.version_id),
            f"page:{page_number}",
        ),
        page_number=page_number,
    )


def _assets_by_page(assets: list[DocumentAsset]) -> dict[int, list[AssetArtifactRef]]:
    grouped: dict[int, list[AssetArtifactRef]] = {}
    for asset in assets:
        if asset.page_number is None:
            continue
        grouped.setdefault(asset.page_number, []).append(_asset_ref(asset))
    return grouped


def _asset_ref(asset: DocumentAsset) -> AssetArtifactRef:
    return AssetArtifactRef(
        asset_id=asset.asset_id,
        asset_type=asset.asset_type,
        object_key=asset.object_key,
        mime_type=asset.mime_type,
        page_number=asset.page_number,
        element_id=asset.element_id,
        content_hash=asset.content_hash,
        byte_size=asset.byte_size,
    )


def _nonempty_bytes(data: bytes) -> bytes:
    return data if data else b"\n"
