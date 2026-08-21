"""Callable / no-op stage handlers used by tests and scaffolding."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from enterprise_rag.domain.ingestion.handlers import StageContext, StageOutcome, StageOutcomeStatus
from enterprise_rag.domain.ingestion.stages import IngestionStageName


class NoOpStageHandler:
    """Marks a stage completed without side effects."""

    def __init__(self, stage: IngestionStageName, *, warning: str | None = None) -> None:
        self._stage = stage
        self._warning = warning

    @property
    def stage(self) -> IngestionStageName:
        return self._stage

    async def execute(self, context: StageContext) -> StageOutcome:
        _ = context
        if self._warning:
            return StageOutcome(
                status=StageOutcomeStatus.COMPLETED_WITH_WARNINGS,
                warning=self._warning,
            )
        return StageOutcome(status=StageOutcomeStatus.COMPLETED)


class CallableStageHandler:
    """Wrap an async callable as a stage handler."""

    def __init__(
        self,
        stage: IngestionStageName,
        fn: Callable[[StageContext], Awaitable[StageOutcome]],
    ) -> None:
        self._stage = stage
        self._fn = fn

    @property
    def stage(self) -> IngestionStageName:
        return self._stage

    async def execute(self, context: StageContext) -> StageOutcome:
        return await self._fn(context)


def default_noop_handlers(
    *,
    skip_communities: bool = True,
) -> dict[IngestionStageName, NoOpStageHandler]:
    """Build a full pipeline of no-op handlers for orchestration tests."""
    handlers: dict[IngestionStageName, NoOpStageHandler] = {}
    for stage in IngestionStageName:
        if skip_communities and stage is IngestionStageName.SUMMARIZE_COMMUNITIES:
            continue
        handlers[stage] = NoOpStageHandler(stage)
    return handlers
