"""Resumable ingestion stage orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from enterprise_rag.domain.ingestion.handlers import (
    StageContext,
    StageHandler,
    StageOutcome,
    StageOutcomeStatus,
)
from enterprise_rag.domain.ingestion.records import IngestionRunRecord, IngestionStageRecord
from enterprise_rag.domain.ingestion.retry import (
    DeadLetterRecord,
    RetryPolicy,
    is_retryable_exception,
)
from enterprise_rag.domain.ingestion.stages import (
    INGESTION_STAGE_ORDER,
    IngestionRunStatus,
    IngestionStageName,
    StageStatus,
)
from enterprise_rag.domain.ingestion.state_machine import (
    IngestionProgress,
    IngestionStateMachine,
    StageRecord,
)
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import IngestionError
from enterprise_rag.shared.logging import get_logger

logger = get_logger(__name__)


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
    ) -> None:
        self._handlers = dict(handlers)
        self._retry_policy = retry_policy or RetryPolicy()
        self._sleep = sleep_fn or asyncio.sleep

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

        for stage in INGESTION_STAGE_ORDER:
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

            if stop_after is stage:
                break

        self._sync_records(stage_records, machine)
        run.status = machine.run_status
        progress = machine.progress()
        run.pages_processed = progress.pages_processed
        run.elements_processed = progress.elements_processed
        run.retry_count = progress.retry_count
        run.latest_warning = progress.latest_warning
        if failed_stage is not None:
            record = machine.get_stage(failed_stage)
            run.error_code = record.error_code
            run.error_message = record.error_message
            run.completed_at = datetime.now(UTC)
        elif machine.run_status in {
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
    ) -> tuple[StageOutcome, DeadLetterRecord | None]:
        while True:
            machine.mark_running(
                stage,
                idempotency_key=idempotency_key,
                config_fingerprint=config_fingerprint,
            )
            attempt = machine.get_stage(stage).attempt_count
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
                maybe_awaitable = self._sleep(delay)
                if hasattr(maybe_awaitable, "__await__"):
                    await maybe_awaitable
                continue

            machine.mark_failed(
                stage,
                error_code=outcome.error_code or "stage_failed",
                error_message=outcome.error_message or "stage failed",
            )
            dead = DeadLetterRecord(
                tenant_id=context.tenant.tenant_id,
                ingestion_run_id=context.ingestion_run_id,
                stage=stage,
                attempt_count=attempt,
                error_code=outcome.error_code or "stage_failed",
                error_message=outcome.error_message or "stage failed",
                payload={
                    "document_id": str(context.document_id),
                    "version_id": str(context.version_id),
                    "content_hash": context.content_hash,
                    "config_fingerprint": context.config_fingerprint,
                },
            )
            return outcome, dead

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

    @staticmethod
    def _sync_records(
        stage_records: list[IngestionStageRecord],
        machine: IngestionStateMachine,
    ) -> None:
        by_stage = {record.stage: record for record in stage_records}
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
                persisted.started_at = persisted.started_at or datetime.now(UTC)
            if record.status in {
                StageStatus.COMPLETED,
                StageStatus.COMPLETED_WITH_WARNINGS,
                StageStatus.FAILED,
                StageStatus.SKIPPED,
                StageStatus.CANCELLED,
            }:
                persisted.completed_at = datetime.now(UTC)
