"""Typer CLI for enterprise-rag."""

from __future__ import annotations

import asyncio
import json
import sys
from enum import IntEnum
from typing import Any
from uuid import UUID

import typer

from enterprise_rag.application.ingestion import (
    IngestionOrchestrator,
    RegisterSourceRequest,
    default_noop_handlers,
)
from enterprise_rag.application.runtime import ServiceContainer, build_local_container
from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.ingestion.handlers import StageHandler
from enterprise_rag.domain.ingestion.stages import IngestionStageName
from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.retrieval.enums import RetrievalMode
from enterprise_rag.domain.retrieval.models import QueryRequest, RetrievalFilters
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import (
    AuthorizationError,
    EnterpriseRagError,
    GraphError,
    ModelError,
    ParserError,
    StorageError,
    TenantError,
    UnsupportedDocumentError,
    ValidationError,
)
from enterprise_rag.shared.logging import configure_logging, get_logger

app = typer.Typer(
    name="enterprise-rag",
    help="Enterprise RAG-Anything CLI",
    no_args_is_help=True,
    add_completion=False,
)
logger = get_logger(__name__)

_CONTAINER: ServiceContainer | None = None


class ExitCode(IntEnum):
    SUCCESS = 0
    UNEXPECTED = 1
    INVALID_ARGS = 2
    UNSUPPORTED_DOCUMENT = 3
    PARSING = 4
    STORAGE = 5
    MODEL = 6
    GRAPH = 7
    PARTIAL = 8
    AUTHORIZATION = 9


def get_container() -> ServiceContainer:
    global _CONTAINER
    if _CONTAINER is None:
        _CONTAINER = build_local_container()
    return _CONTAINER


def set_container(container: ServiceContainer) -> None:
    global _CONTAINER
    _CONTAINER = container


def _exit_for_error(exc: BaseException) -> int:
    if isinstance(exc, ValidationError):
        return ExitCode.INVALID_ARGS
    if isinstance(exc, UnsupportedDocumentError):
        return ExitCode.UNSUPPORTED_DOCUMENT
    if isinstance(exc, ParserError):
        return ExitCode.PARSING
    if isinstance(exc, StorageError):
        return ExitCode.STORAGE
    if isinstance(exc, ModelError):
        return ExitCode.MODEL
    if isinstance(exc, GraphError):
        return ExitCode.GRAPH
    if isinstance(exc, (AuthorizationError, TenantError)):
        return ExitCode.AUTHORIZATION
    if isinstance(exc, EnterpriseRagError):
        return ExitCode.UNEXPECTED
    return ExitCode.UNEXPECTED


def _emit(payload: dict[str, Any], *, output: str) -> None:
    if output == "json":
        typer.echo(json.dumps(payload, default=str, indent=2))
        return
    for key, value in payload.items():
        typer.echo(f"{key}: {value}")


async def _resolve_tenant(tenant_id: str) -> TenantContext:
    container = get_container()
    try:
        return await container.resolve_tenant(tenant_id=UUID(tenant_id))
    except ValueError:
        return await container.resolve_tenant(tenant_key=tenant_id)


@app.callback()
def main_callback(
    log_level: str = typer.Option("WARNING", "--log-level"),
) -> None:
    configure_logging(level=log_level, stream=sys.stderr)


@app.command("ingest")
def ingest_command(
    source: str = typer.Argument(..., help="Local file path or https URL"),
    tenant_id: str = typer.Option(..., "--tenant-id"),
    document_id: str | None = typer.Option(None, "--document-id"),
    title: str | None = typer.Option(None, "--title"),
    document_type: str | None = typer.Option(None, "--document-type"),
    parser: str = typer.Option("auto", "--parser"),
    parser_profile: str = typer.Option("balanced", "--parser-profile"),
    llm_implementation: str = typer.Option("langchain", "--llm-implementation"),
    text_model: str | None = typer.Option(None, "--text-model"),
    vision_model: str | None = typer.Option(None, "--vision-model"),
    embedding_model: str | None = typer.Option(None, "--embedding-model"),
    ocr: str = typer.Option("auto", "--ocr"),
    multimodal: str = typer.Option("enabled", "--multimodal"),
    graph: str = typer.Option("enabled", "--graph"),
    force: bool = typer.Option(False, "--force"),
    resume: bool = typer.Option(False, "--resume"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    wait: bool = typer.Option(False, "--wait"),
    output: str = typer.Option("json", "--output", help="json|text"),
    correlation_id: str | None = typer.Option(None, "--correlation-id"),
) -> None:
    """Register a source document and optionally run ingestion stages."""
    _ = (
        parser_profile,
        llm_implementation,
        text_model,
        vision_model,
        embedding_model,
        ocr,
        multimodal,
        graph,
        resume,
    )
    try:
        payload = asyncio.run(
            _ingest_async(
                source=source,
                tenant_id=tenant_id,
                document_id=document_id,
                title=title,
                document_type=document_type,
                parser=parser,
                force=force,
                dry_run=dry_run,
                wait=wait,
                correlation_id=correlation_id,
            )
        )
        _emit(payload, output=output)
        if payload.get("partial"):
            raise typer.Exit(code=ExitCode.PARTIAL)
    except EnterpriseRagError as exc:
        typer.secho(exc.message, fg=typer.colors.RED, err=True)
        raise typer.Exit(code=_exit_for_error(exc)) from exc
    except Exception as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=ExitCode.UNEXPECTED) from exc


async def _ingest_async(
    *,
    source: str,
    tenant_id: str,
    document_id: str | None,
    title: str | None,
    document_type: str | None,
    parser: str,
    force: bool,
    dry_run: bool,
    wait: bool,
    correlation_id: str | None,
) -> dict[str, Any]:
    tenant = await _resolve_tenant(tenant_id)
    container = get_container()
    is_url = source.startswith(("http://", "https://"))
    request = RegisterSourceRequest(
        local_path=None if is_url else source,
        source_url=source if is_url else None,
        document_id=UUID(document_id) if document_id else None,
        title=title,
        document_type=document_type,
        parser_requested=parser,
        force_new_version=force,
        correlation_id=correlation_id or str(new_id()),
    )
    if dry_run:
        return {
            "dry_run": True,
            "tenant_id": str(tenant.tenant_id),
            "source": source,
            "parser": parser,
        }
    result = await container.require_register_source().execute(tenant, request)
    payload: dict[str, Any] = {
        "status": "accepted",
        "tenant_id": str(result.tenant_id),
        "document_id": str(result.document_id),
        "version_id": str(result.version_id),
        "ingestion_run_id": str(result.ingestion_run_id),
        "parser_requested": parser,
        "duplicate_version": result.duplicate_version,
        "byte_size": result.byte_size,
        "warnings": [],
    }
    if wait:
        repo = container.require_ingestion_repo()
        run = await repo.get_run(tenant, result.ingestion_run_id)
        stages = await repo.list_stages(tenant, result.ingestion_run_id)
        if run is None:
            raise ValidationError("Ingestion run missing after registration")
        handlers: dict[IngestionStageName, StageHandler] = {
            key: value for key, value in default_noop_handlers().items()
        }
        orchestrator = IngestionOrchestrator(handlers)
        orch = await orchestrator.run(tenant=tenant, run=run, stage_records=stages)
        await repo.update_run(tenant, run)
        for stage in stages:
            await repo.update_stage(tenant, stage)
        payload["status"] = orch.run_status.value
        payload["duration_note"] = "local noop orchestration"
        payload["partial"] = orch.run_status.value == "partial"
    return payload


@app.command("query")
def query_command(
    question: str = typer.Argument(...),
    tenant_id: str = typer.Option(..., "--tenant-id"),
    mode: RetrievalMode = typer.Option(RetrievalMode.AUTO, "--mode"),
    include_images: bool = typer.Option(False, "--include-images"),
    include_graph_paths: bool = typer.Option(False, "--include-graph-paths"),
    top_k: int = typer.Option(12, "--top-k"),
    output: str = typer.Option("json", "--output"),
) -> None:
    """Run grounded retrieval + answer generation."""
    try:
        payload = asyncio.run(
            _query_async(
                question=question,
                tenant_id=tenant_id,
                mode=mode,
                include_images=include_images,
                include_graph_paths=include_graph_paths,
                top_k=top_k,
            )
        )
        _emit(payload, output=output)
    except EnterpriseRagError as exc:
        typer.secho(exc.message, fg=typer.colors.RED, err=True)
        raise typer.Exit(code=_exit_for_error(exc)) from exc


async def _query_async(
    *,
    question: str,
    tenant_id: str,
    mode: RetrievalMode,
    include_images: bool,
    include_graph_paths: bool,
    top_k: int,
) -> dict[str, Any]:
    tenant = await _resolve_tenant(tenant_id)
    modalities = [Modality.IMAGE, Modality.CHART, Modality.DIAGRAM] if include_images else []
    outcome = await get_container().require_query().query(
        tenant,
        QueryRequest(
            question=question,
            mode=mode,
            filters=RetrievalFilters(modalities=modalities),
            top_k=top_k,
            include_graph_paths=include_graph_paths,
            rerank=False,
        ),
    )
    return outcome.response.model_dump(mode="json")


@app.command("inspect-document")
def inspect_document(
    document_id: str = typer.Argument(...),
    tenant_id: str = typer.Option(..., "--tenant-id"),
    show_chunks: bool = typer.Option(False, "--show-chunks"),
    output: str = typer.Option("json", "--output"),
) -> None:
    try:
        payload = asyncio.run(
            _inspect_async(
                document_id=document_id,
                tenant_id=tenant_id,
                show_chunks=show_chunks,
            )
        )
        _emit(payload, output=output)
    except EnterpriseRagError as exc:
        raise typer.Exit(code=_exit_for_error(exc)) from exc


async def _inspect_async(
    *,
    document_id: str,
    tenant_id: str,
    show_chunks: bool = False,
) -> dict[str, Any]:
    tenant = await _resolve_tenant(tenant_id)
    document = await get_container().require_document_repo().get_document(
        tenant, UUID(document_id)
    )
    if document is None:
        from enterprise_rag.shared.exceptions import NotFoundError

        raise NotFoundError("Document not found")
    payload = document.model_dump(mode="json")
    if show_chunks:
        container = get_container()
        chunks, total = await container.list_chunks(
            tenant,
            UUID(document_id),
            offset=0,
            limit=200,
        )
        payload["chunks"] = [
            {
                "chunk_id": str(chunk.chunk_id),
                "parent_chunk_id": str(chunk.parent_chunk_id) if chunk.parent_chunk_id else None,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "section": list(chunk.section_path),
                "modality": chunk.modality.value,
                "chunk_type": chunk.chunk_type.value,
                "token_count": chunk.token_count,
                "content": chunk.text[:1200],
            }
            for chunk in chunks
        ]
        payload["chunk_total"] = total
    return payload


@app.command("show-run")
def show_run(
    run_id: str = typer.Argument(...),
    tenant_id: str = typer.Option(..., "--tenant-id"),
    output: str = typer.Option("json", "--output"),
) -> None:
    try:
        payload = asyncio.run(_show_run_async(run_id=run_id, tenant_id=tenant_id))
        _emit(payload, output=output)
    except EnterpriseRagError as exc:
        raise typer.Exit(code=_exit_for_error(exc)) from exc


async def _show_run_async(*, run_id: str, tenant_id: str) -> dict[str, Any]:
    tenant = await _resolve_tenant(tenant_id)
    repo = get_container().require_ingestion_repo()
    run = await repo.get_run(tenant, UUID(run_id))
    if run is None:
        from enterprise_rag.shared.exceptions import NotFoundError

        raise NotFoundError("Ingestion run not found")
    stages = await repo.list_stages(tenant, UUID(run_id))
    return {
        "run": run.model_dump(mode="json"),
        "stages": [stage.model_dump(mode="json") for stage in stages],
    }


@app.command("resume-run")
def resume_run(
    run_id: str = typer.Argument(...),
    tenant_id: str = typer.Option(..., "--tenant-id"),
    output: str = typer.Option("json", "--output"),
) -> None:
    try:
        payload = asyncio.run(_resume_async(run_id=run_id, tenant_id=tenant_id))
        _emit(payload, output=output)
    except EnterpriseRagError as exc:
        raise typer.Exit(code=_exit_for_error(exc)) from exc


async def _resume_async(*, run_id: str, tenant_id: str) -> dict[str, Any]:
    tenant = await _resolve_tenant(tenant_id)
    run = await get_container().resume_run(tenant, UUID(run_id))
    return dict(run.model_dump(mode="json"))


@app.command("delete-document")
def delete_document(
    document_id: str = typer.Argument(...),
    tenant_id: str = typer.Option(..., "--tenant-id"),
    output: str = typer.Option("json", "--output"),
) -> None:
    try:
        payload = asyncio.run(_delete_async(document_id=document_id, tenant_id=tenant_id))
        _emit(payload, output=output)
    except EnterpriseRagError as exc:
        raise typer.Exit(code=_exit_for_error(exc)) from exc


async def _delete_async(*, document_id: str, tenant_id: str) -> dict[str, Any]:
    tenant = await _resolve_tenant(tenant_id)
    operation = await get_container().submit_deletion(tenant, UUID(document_id))
    payload: dict[str, Any] = {
        "operation_id": str(operation.operation_id),
        "document_id": str(operation.document_id),
        "status": operation.status,
    }
    if operation.result is not None:
        payload.update(
            {
                "vectors_deleted": operation.result.vectors_deleted,
                "graph_deleted": operation.result.graph_deleted,
                "objects_deleted": operation.result.objects_deleted,
                "warnings": list(operation.result.warnings),
            }
        )
    return payload


@app.command("reindex")
def reindex(
    document_id: str = typer.Argument(...),
    tenant_id: str = typer.Option(..., "--tenant-id"),
    output: str = typer.Option("json", "--output"),
) -> None:
    try:
        payload = asyncio.run(
            _reindex_async(document_id=document_id, tenant_id=tenant_id, scope="full")
        )
        _emit(payload, output=output)
    except EnterpriseRagError as exc:
        raise typer.Exit(code=_exit_for_error(exc)) from exc


@app.command("rebuild-vectors")
def rebuild_vectors(
    document_id: str = typer.Argument(...),
    tenant_id: str = typer.Option(..., "--tenant-id"),
    output: str = typer.Option("json", "--output"),
) -> None:
    try:
        payload = asyncio.run(
            _reindex_async(document_id=document_id, tenant_id=tenant_id, scope="vectors")
        )
        _emit(payload, output=output)
    except EnterpriseRagError as exc:
        raise typer.Exit(code=_exit_for_error(exc)) from exc


@app.command("rebuild-graph")
def rebuild_graph(
    document_id: str = typer.Argument(...),
    tenant_id: str = typer.Option(..., "--tenant-id"),
    output: str = typer.Option("json", "--output"),
) -> None:
    try:
        payload = asyncio.run(
            _reindex_async(document_id=document_id, tenant_id=tenant_id, scope="graph")
        )
        _emit(payload, output=output)
    except EnterpriseRagError as exc:
        raise typer.Exit(code=_exit_for_error(exc)) from exc


async def _reindex_async(*, document_id: str, tenant_id: str, scope: str) -> dict[str, Any]:
    from enterprise_rag.domain.deletion.stages import ReindexScope

    tenant = await _resolve_tenant(tenant_id)
    result = await get_container().submit_reindex(
        tenant,
        UUID(document_id),
        scope=ReindexScope(scope),
    )
    return result.model_dump(mode="json")


@app.command("worker")
def worker(
    poll_interval: float = typer.Option(1.0, "--poll-interval"),
) -> None:
    """Run the ingestion worker loop (Docker / local process)."""
    from enterprise_rag.infrastructure.workers.main import run_worker

    try:
        asyncio.run(run_worker(poll_interval_seconds=poll_interval))
    except KeyboardInterrupt:
        raise typer.Exit(code=ExitCode.SUCCESS) from None
    except EnterpriseRagError as exc:
        raise typer.Exit(code=_exit_for_error(exc)) from exc


def run() -> None:
    """Console script entrypoint."""
    try:
        app()
    except typer.Exit:
        raise
    except Exception as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        sys.exit(ExitCode.UNEXPECTED)


if __name__ == "__main__":
    run()
