"""Resumable ingestion stage orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from graph_rag.domain.ingestion.handlers import (
    StageContext,
    StageHandler,
    StageOutcome,
    StageOutcomeStatus,
)
from graph_rag.domain.ingestion.records import IngestionRunRecord, IngestionStageRecord
from graph_rag.domain.ingestion.retry import (
    DeadLetterRecord,
    RetryPolicy,
    is_retryable_exception,
)
from graph_rag.domain.ingestion.stages import (
    INGESTION_STAGE_ORDER,
    IngestionRunStatus,
    IngestionStageName,
    StageStatus,
)
from graph_rag.domain.ingestion.state_machine import (
    IngestionProgress,
    IngestionStateMachine,
    StageRecord,
)
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.observability.metrics import get_metrics
from graph_rag.shared.exceptions import IngestionError
from graph_rag.shared.logging import get_logger

logger = get_logger(__name__)

StagePersistFn = Callable[
    [IngestionRunRecord, list[IngestionStageRecord], IngestionStageName],
    Awaitable[None] | None,
]

# RetryPolicy.max_attempts only bounds retries *within* one _execute_with_retries
# call. Nothing stopped a stage that already exhausted those from being
# re-attempted by a brand new orchestrator.run() invocation (e.g. a duplicate
# outbox/stream redispatch) -- mark_running has no guard against restarting a
# FAILED stage, so attempt_count could climb indefinitely across dispatches. A
# real run was observed retrying the same stage 70+ times over 12+ hours this
# way. This is a hard, dispatch-count-independent ceiling on top of that.
MAX_TOTAL_STAGE_ATTEMPTS = 10


@dataclass
class OrchestrationResult:
    """Outcome of running one or more ingestion stages."""

    run_status: IngestionRunStatus
    progress: IngestionProgress
    completed_in_session: list[IngestionStageName] = field(default_factory=list)
    skipped_in_session: list[IngestionStageName] = field(default_factory=list)
    failed_stage: IngestionStageName | None = None
    dead_letter: DeadLetterRecord | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)


class IngestionOrchestrator:
    """Execute resumable stages with retries and dead-letter escalation."""

    def __init__(
        self,
        handlers: Mapping[IngestionStageName, StageHandler],
        *,
        retry_policy: RetryPolicy | None = None,
        sleep_fn: Any | None = None,
        on_stage: StagePersistFn | None = None,
        should_stop: Callable[[], bool] | None = None,
        worker_id: str | None = None,
    ) -> None:
        self._handlers = dict(handlers)
        self._retry_policy = retry_policy or RetryPolicy()
        self._sleep = sleep_fn or asyncio.sleep
        self._on_stage = on_stage
        self._should_stop = should_stop
        self._worker_id = worker_id

    async def run(
        self,
        *,
        tenant: TenantContext,
        run: IngestionRunRecord,
        stage_records: list[IngestionStageRecord],
        artifacts: dict[str, Any] | None = None,
        stop_after: IngestionStageName | None = None,
    ) -> OrchestrationResult:
        if not run.content_hash or not run.config_fingerprint:
            raise IngestionError(
                "Ingestion run requires content_hash and config_fingerprint",
                details={"ingestion_run_id": str(run.ingestion_run_id)},
            )
        machine = self._machine_from_records(stage_records, run_status=run.status)
        machine.reset_stale_running()
        context = StageContext(
            tenant=tenant,
            ingestion_run_id=run.ingestion_run_id,
            document_id=run.document_id,
            version_id=run.version_id,
            content_hash=run.content_hash,
            config_fingerprint=run.config_fingerprint,
            correlation_id=run.correlation_id,
            artifacts=dict(artifacts or {}),
        )
        completed: list[IngestionStageName] = []
        skipped: list[IngestionStageName] = []
        dead_letter: DeadLetterRecord | None = None
        failed_stage: IngestionStageName | None = None
        stopped_early = False

        for stage in INGESTION_STAGE_ORDER:
            if self._should_stop is not None and self._should_stop():
                stopped_early = True
                break
            idempotency_key = IngestionStateMachine.build_idempotency_key(
                tenant_id=tenant.tenant_id,
                version_id=run.version_id,
                stage=stage,
                config_fingerprint=run.config_fingerprint,
                content_hash=run.content_hash,
            )
            if machine.should_skip_on_resume(
                stage,
                idempotency_key=idempotency_key,
                config_fingerprint=run.config_fingerprint,
            ):
                skipped.append(stage)
                if stop_after is stage:
                    break
                continue

            handler = self._handlers.get(stage)
            if handler is None:
                if stage is IngestionStageName.SUMMARIZE_COMMUNITIES:
                    machine.mark_skipped(stage, reason="community summarization disabled")
                    skipped.append(stage)
                    if stop_after is stage:
                        break
                    continue
                raise IngestionError(
                    "No handler registered for stage",
                    details={"stage": stage.value},
                )

            outcome, dead_letter = await self._execute_with_retries(
                machine=machine,
                handler=handler,
                stage=stage,
                context=context,
                idempotency_key=idempotency_key,
                config_fingerprint=run.config_fingerprint,
                run=run,
                stage_records=stage_records,
            )
            if outcome.status is StageOutcomeStatus.SKIPPED:
                skipped.append(stage)
            elif outcome.status in {
                StageOutcomeStatus.COMPLETED,
                StageOutcomeStatus.COMPLETED_WITH_WARNINGS,
            }:
                completed.append(stage)
                if outcome.pages_processed is not None:
                    machine.pages_processed = outcome.pages_processed
                if outcome.elements_processed is not None:
                    machine.elements_processed = outcome.elements_processed
            else:
                failed_stage = stage
                break

            await self._persist_progress(run, stage_records, machine, stage)
            if stop_after is stage:
                break
            if self._should_stop is not None and self._should_stop():
                stopped_early = True
                break

        self._sync_records(stage_records, machine)
        if not stopped_early:
            run.status = machine.run_status
        else:
            run.status = IngestionRunStatus.RUNNING
        progress = machine.progress()
        run.pages_processed = progress.pages_processed
        run.elements_processed = progress.elements_processed
        run.retry_count = progress.retry_count
        run.latest_warning = progress.latest_warning
        run.worker_id = self._worker_id or run.worker_id
        if failed_stage is not None:
            record = machine.get_stage(failed_stage)
            run.error_code = record.error_code
            run.error_message = record.error_message
            run.completed_at = datetime.now(UTC)
        elif not stopped_early and machine.run_status in {
            IngestionRunStatus.COMPLETED,
            IngestionRunStatus.COMPLETED_WITH_WARNINGS,
        }:
            run.completed_at = datetime.now(UTC)
            run.error_code = None
            run.error_message = None

        return OrchestrationResult(
            run_status=machine.run_status,
            progress=progress,
            completed_in_session=completed,
            skipped_in_session=skipped,
            failed_stage=failed_stage,
            dead_letter=dead_letter,
            artifacts=context.artifacts,
        )

    async def _execute_with_retries(
        self,
        *,
        machine: IngestionStateMachine,
        handler: StageHandler,
        stage: IngestionStageName,
        context: StageContext,
        idempotency_key: str,
        config_fingerprint: str,
        run: IngestionRunRecord,
        stage_records: list[IngestionStageRecord],
    ) -> tuple[StageOutcome, DeadLetterRecord | None]:
        metrics = get_metrics()
        while True:
            current = machine.get_stage(stage)
            if current.attempt_count >= MAX_TOTAL_STAGE_ATTEMPTS:
                error_code = current.error_code or "max_attempts_exceeded"
                error_message = current.error_message or (
                    f"Stage exceeded {MAX_TOTAL_STAGE_ATTEMPTS} total attempts "
                    "across retries/redispatches"
                )
                if current.status is not StageStatus.FAILED:
                    machine.mark_failed(stage, error_code=error_code, error_message=error_message)
                    await self._persist_progress(run, stage_records, machine, stage)
                outcome = StageOutcome(
                    status=StageOutcomeStatus.FAILED,
                    error_code=error_code,
                    error_message=error_message,
                    retryable=False,
                )
                dead = DeadLetterRecord(
                    tenant_id=context.tenant.tenant_id,
                    ingestion_run_id=context.ingestion_run_id,
                    stage=stage,
                    attempt_count=current.attempt_count,
                    error_code=error_code,
                    error_message=error_message,
                    correlation_id=context.correlation_id,
                    payload={
                        "document_id": str(context.document_id),
                        "version_id": str(context.version_id),
                        "content_hash": context.content_hash,
                        "config_fingerprint": context.config_fingerprint,
                        "failed_stage": stage.value,
                        "attempt_count": current.attempt_count,
                    },
                )
                return outcome, dead
            machine.mark_running(
                stage,
                idempotency_key=idempotency_key,
                config_fingerprint=config_fingerprint,
            )
            await self._persist_progress(run, stage_records, machine, stage)
            attempt = machine.get_stage(stage).attempt_count
            started = datetime.now(UTC)
            try:
                outcome = await handler.execute(context)
            except Exception as exc:
                retryable = is_retryable_exception(exc)
                outcome = StageOutcome(
                    status=StageOutcomeStatus.FAILED,
                    error_code=getattr(exc, "code", type(exc).__name__),
                    error_message=str(exc),
                    retryable=retryable,
                )
            metrics.observe(
                "ingest_stage_duration_seconds",
                (datetime.now(UTC) - started).total_seconds(),
                labels={"stage": stage.value},
            )

            if outcome.status is StageOutcomeStatus.SKIPPED:
                machine.mark_skipped(stage, reason=outcome.warning)
                return outcome, None
            if outcome.status in {
                StageOutcomeStatus.COMPLETED,
                StageOutcomeStatus.COMPLETED_WITH_WARNINGS,
            }:
                warning = outcome.warning
                if outcome.status is StageOutcomeStatus.COMPLETED_WITH_WARNINGS and not warning:
                    warning = "completed with warnings"
                machine.mark_completed(stage, warning=warning)
                return outcome, None

            if self._retry_policy.should_retry(
                attempt_count=attempt,
                retryable=outcome.retryable,
            ):
                delay = self._retry_policy.delay_for(attempt)
                metrics.incr("ingest_retries_total", labels={"stage": stage.value})
                logger.warning(
                    "ingestion_stage_retry",
                    stage=stage.value,
                    attempt=attempt,
                    delay_seconds=delay,
                    error=outcome.error_message,
                )
                machine.mark_failed(
                    stage,
                    error_code=outcome.error_code or "stage_failed",
                    error_message=outcome.error_message or "stage failed",
                )
                await self._persist_progress(run, stage_records, machine, stage)
                maybe_awaitable = self._sleep(delay)
                if hasattr(maybe_awaitable, "__await__"):
                    await maybe_awaitable
                continue

            machine.mark_failed(
                stage,
                error_code=outcome.error_code or "stage_failed",
                error_message=outcome.error_message or "stage failed",
            )
            stream_id = context.artifacts.get("stream_message_id")
            dead = DeadLetterRecord(
                tenant_id=context.tenant.tenant_id,
                ingestion_run_id=context.ingestion_run_id,
                stage=stage,
                attempt_count=attempt,
                error_code=outcome.error_code or "stage_failed",
                error_message=outcome.error_message or "stage failed",
                original_stream_id=str(stream_id) if stream_id else None,
                correlation_id=context.correlation_id,
                payload={
                    "document_id": str(context.document_id),
                    "version_id": str(context.version_id),
                    "content_hash": context.content_hash,
                    "config_fingerprint": context.config_fingerprint,
                    "original_stream_id": str(stream_id) if stream_id else "",
                    "correlation_id": context.correlation_id or "",
                    "failed_stage": stage.value,
                    "attempt_count": attempt,
                },
            )
            return outcome, dead

    async def _persist_progress(
        self,
        run: IngestionRunRecord,
        stage_records: list[IngestionStageRecord],
        machine: IngestionStateMachine,
        stage: IngestionStageName,
    ) -> None:
        self._sync_records(stage_records, machine)
        run.status = machine.run_status
        run.worker_id = self._worker_id or run.worker_id
        run.heartbeat_at = datetime.now(UTC)
        if self._on_stage is None:
            return
        maybe = self._on_stage(run, stage_records, stage)
        if hasattr(maybe, "__await__"):
            await maybe

    @staticmethod
    def _machine_from_records(
        stage_records: list[IngestionStageRecord],
        *,
        run_status: IngestionRunStatus,
    ) -> IngestionStateMachine:
        return IngestionStateMachine(
            stages={
                record.stage: StageRecord(
                    stage=record.stage,
                    status=record.status,
                    attempt_count=record.attempt_count,
                    idempotency_key=record.idempotency_key,
                    config_fingerprint=record.config_fingerprint,
                    warning=record.warning,
                    error_code=record.error_code,
                    error_message=record.error_message,
                )
                for record in stage_records
            },
            run_status=run_status,
        )

    def _sync_records(
        self,
        stage_records: list[IngestionStageRecord],
        machine: IngestionStateMachine,
    ) -> None:
        by_stage = {record.stage: record for record in stage_records}
        now = datetime.now(UTC)
        for stage, record in machine.stages.items():
            persisted = by_stage[stage]
            persisted.status = record.status
            persisted.attempt_count = record.attempt_count
            persisted.idempotency_key = record.idempotency_key
            persisted.config_fingerprint = record.config_fingerprint
            persisted.warning = record.warning
            persisted.error_code = record.error_code
            persisted.error_message = record.error_message
            if record.status is StageStatus.RUNNING:
                persisted.started_at = persisted.started_at or now
                persisted.completed_at = None
                persisted.worker_id = self._worker_id
                persisted.heartbeat_at = now
            if record.status in {
                StageStatus.COMPLETED,
                StageStatus.COMPLETED_WITH_WARNINGS,
                StageStatus.FAILED,
                StageStatus.SKIPPED,
                StageStatus.CANCELLED,
            }:
                persisted.completed_at = persisted.completed_at or now
