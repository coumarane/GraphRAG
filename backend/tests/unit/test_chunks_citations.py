"""Chunk and citation domain tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from enterprise_rag.domain.chunks import ChunkBase, ChunkType
from enterprise_rag.domain.citations import Citation
from enterprise_rag.domain.ids import content_sha256_hex, new_id
from enterprise_rag.domain.modality import Modality


def test_chunk_base_validation() -> None:
    chunk = ChunkBase(
        chunk_id=new_id(),
        tenant_id=new_id(),
        document_id=new_id(),
        version_id=new_id(),
        modality=Modality.TABLE,
        chunk_type=ChunkType.TABLE,
        text="viscosity table",
        token_count=12,
        page_start=3,
        page_end=3,
        content_hash=content_sha256_hex("viscosity table"),
        source_object_keys=["tenants/t/docs/d/v/assets/a.png"],
    )
    assert chunk.parent_chunk_id is None


def test_citation_page_range() -> None:
    with pytest.raises(ValidationError):
        Citation(
            citation_id="C1",
            tenant_id=new_id(),
            document_id=new_id(),
            document_version_id=new_id(),
            document_name="Spec",
            page_start=5,
            page_end=4,
            chunk_id=new_id(),
            modality=Modality.TEXT,
            source_object_key="key",
            evidence="text",
        )
