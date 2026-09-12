"""Durable parser boundary: CanonicalDocument is persisted before downstream work.

Milestone 1: PARSE uses the existing parser, NORMALIZE writes CanonicalDocument
JSON, later stages resume from that artifact, and a downstream retry must not
execute the parser again.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph_rag.application.ingestion import stage_pipeline as stage_pipeline_module
from graph_rag.application.ingestion.register_source import RegisterSourceRequest
from graph_rag.application.ingestion.stage_pipeline import (
    DocumentPipeline,
    PipelineWorkspace,
    artifact_key,
    canonical_document_key,
    run_document_pipeline,
)
from graph_rag.application.runtime import build_local_container
from graph_rag.domain.documents import CanonicalDocument, NormalizedDocument
from graph_rag.domain.ingestion.handlers import StageContext
from graph_rag.domain.ingestion.retry import RetryPolicy
from graph_rag.domain.ingestion.stages import (
    IngestionRunStatus,
    IngestionStageName,
    StageStatus,
)
from graph_rag.domain.storage.object_keys import normalized_document_object_key
from graph_rag.infrastructure.models import FakeEmbeddingModel
from graph_rag.shared.exceptions import TransientError


def test_canonical_document_is_normalized_document_alias() -> None:
    assert CanonicalDocument is NormalizedDocument


@pytest.fixture
def container(monkeypatch: pytest.MonkeyPatch):
    from graph_rag.config.settings import clear_settings_cache

    monkeypatch.setenv("AUTH_ENABLED", "false")
    clear_settings_cache()
    try:
        yield build_local_container(
            auto_process_ingest=False,
            enable_semantic_graph=False,
        )
    finally:
        clear_settings_cache()


def _counting_parse(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    original = stage_pipeline_module._parse_document_raw
    calls = {"n": 0}

    async def counting(*args, **kwargs):
        calls["n"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(stage_pipeline_module, "_parse_document_raw", counting)
    return calls


async def _register_text(container, tmp_path: Path, name: str = "sample.txt"):
    path = tmp_path / name
    path.write_text("Hello canonical world.\n\nSecond paragraph for chunking.\n")
    tenant = await container.resolve_tenant(tenant_key="canonical-demo")
    result = await container.require_register_source().execute(
        tenant,
        RegisterSourceRequest(
            local_path=str(path),
            title="Canonical Sample",
            parser_requested="text",
        ),
    )
    return tenant, result


def _stage_context(tenant, result) -> StageContext:
    return StageContext(
        tenant=tenant,
        ingestion_run_id=result.ingestion_run_id,
        document_id=result.document_id,
        version_id=result.version_id,
        content_hash=result.content_hash,
        config_fingerprint="intake-v1",
    )


@pytest.mark.asyncio
async def test_parse_normalize_persists_canonical_and_skips_parser_on_reload(
    container, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _counting_parse(monkeypatch)
    tenant, result = await _register_text(container, tmp_path)
    service = container.require_process_ingestion()
    context = _stage_context(tenant, result)

    workspace = PipelineWorkspace(service)
    pipeline = DocumentPipeline(workspace)
    await pipeline.stage_parse(context)
    assert calls["n"] == 1
    parse_raw = await workspace.load_json("parse_raw")
    assert parse_raw is not None
    assert parse_raw.get("vision_done") is not True
    assert parse_raw["raw"]["parser_name"]

    await pipeline.stage_normalize(context)
    spec_key = canonical_document_key(tenant.tenant_id, result.document_id, result.version_id)
    assert spec_key == normalized_document_object_key(
        tenant_id=tenant.tenant_id,
        document_id=result.document_id,
        version_id=result.version_id,
    )
    raw_canonical = await container.require_object_store().get_bytes(tenant, object_key=spec_key)
    canonical = CanonicalDocument.model_validate(json.loads(raw_canonical.decode("utf-8")))
    assert canonical.elements
    assert canonical.parser_info.parser_name
    working = await workspace.load_json("normalized")
    assert working is not None
    assert CanonicalDocument.model_validate(working).document_id == canonical.document_id

    resumed = PipelineWorkspace(service)
    resumed_pipeline = DocumentPipeline(resumed)
    await resumed_pipeline.stage_parse(context)
    assert calls["n"] == 1
    assert resumed.raw is not None
    assert resumed.normalized is not None
    await resumed_pipeline.stage_normalize(context)
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_downstream_embed_failure_retry_does_not_reparse(
    container, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _counting_parse(monkeypatch)
    tenant, result = await _register_text(container, tmp_path, name="retry.txt")
    service = container.require_process_ingestion()

    class _FailingEmbedding(FakeEmbeddingModel):
        async def embed(self, request):  # type: ignore[no-untyped-def]
            raise TransientError("embedding backend unavailable")

    service.embedding_model = _FailingEmbedding()
    policy = RetryPolicy(max_attempts=1, jitter=False, base_delay_seconds=0)

    first = await run_document_pipeline(
        service,
        tenant,
        result.ingestion_run_id,
        retry_policy=policy,
    )
    assert first.failed_stage is IngestionStageName.EMBED
    assert first.run_status is IngestionRunStatus.FAILED
    assert calls["n"] == 1

    stages = await container.require_ingestion_repo().list_stages(tenant, result.ingestion_run_id)
    by_name = {row.stage: row for row in stages}
    assert by_name[IngestionStageName.PARSE].status in {
        StageStatus.COMPLETED,
        StageStatus.COMPLETED_WITH_WARNINGS,
    }
    assert by_name[IngestionStageName.NORMALIZE].status in {
        StageStatus.COMPLETED,
        StageStatus.COMPLETED_WITH_WARNINGS,
    }
    assert by_name[IngestionStageName.EMBED].status is StageStatus.FAILED

    spec_key = canonical_document_key(tenant.tenant_id, result.document_id, result.version_id)
    raw_canonical = await container.require_object_store().get_bytes(tenant, object_key=spec_key)
    canonical = CanonicalDocument.model_validate(json.loads(raw_canonical.decode("utf-8")))
    assert canonical.elements
    working_key = artifact_key(
        tenant.tenant_id, result.document_id, result.version_id, "normalized"
    )
    await container.require_object_store().get_bytes(tenant, object_key=working_key)

    service.embedding_model = FakeEmbeddingModel()
    second = await run_document_pipeline(
        service,
        tenant,
        result.ingestion_run_id,
        retry_policy=policy,
    )
    assert calls["n"] == 1
    assert second.failed_stage is None
    assert second.run_status in {
        IngestionRunStatus.COMPLETED,
        IngestionRunStatus.COMPLETED_WITH_WARNINGS,
        IngestionRunStatus.PARTIAL,
    }
    assert IngestionStageName.PARSE in second.skipped_in_session
    assert IngestionStageName.NORMALIZE in second.skipped_in_session
